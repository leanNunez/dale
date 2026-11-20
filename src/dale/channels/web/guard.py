"""The request guard (W8, W9, W10, W17; design §4.2): a pure ASGI middleware that wraps the whole
application, so it runs before routing, before any handler and before any body is parsed.

Checks, in this order, each rejecting with the one error envelope:
1. exactly one `Host`, in the allow-list (`invalid_host`); a missing one is rejected too;
2. on any method but GET and HEAD, exactly one `Origin`, in the allow-list (`forbidden_origin`);
   a missing one is rejected too, because browsers send `Origin` on every POST, same-origin
   included;
3. on those methods, the media type `application/json`, charset UTF-8 if named
   (`unsupported_media_type`);
4. the body at most `MAX_BODY` bytes, by `Content-Length` and by counting the stream
   (`payload_too_large`). The guard reads the whole capped body before the application runs,
   so an oversized body is never handed to a parser.

Every response the guard or the application sends, a rejection included, carries the CSP,
`nosniff` and `no-referrer` headers; API paths also carry `Cache-Control: no-store`. A request
that is not valid HTTP never reaches the guard: uvicorn (h11) answers it with its own plain-text
400. Rejections never echo the request.
"""

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, Self

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from dale.channels.web.contract import ErrorBody, ResponseEnvelope
from dale.channels.web.errors import WebErrorCode, message_for, status_for
from dale.shared.errors import ErrorCode

MAX_BODY: Final = 16 * 1024
CSP: Final = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
    "form-action 'self'"
)
SECURITY_HEADERS: Final = {
    "content-security-policy": CSP,
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
}
SAFE_METHODS: Final = frozenset({"GET", "HEAD"})
DIGITS = re.compile(r"[0-9]+")
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AllowList:
    """`Host` values (`name:port`) and `Origin` values (`scheme://name:port`), lowercase."""

    hosts: frozenset[str]
    origins: frozenset[str]

    @classmethod
    def loopback(cls, port: int, hosts: Iterable[str] = (), origins: Iterable[str] = ()) -> Self:
        """The loopback names on `port`, plus any configured extra names."""
        names = (f"127.0.0.1:{port}", f"localhost:{port}")
        return cls(
            frozenset(h.strip().lower() for h in (*names, *hosts)),
            frozenset(o.strip().lower() for o in (*(f"http://{n}" for n in names), *origins)),
        )


def error_envelope(code: WebErrorCode | ErrorCode) -> ResponseEnvelope:
    """The envelope of a response that carries only an error: the code and its catalog text."""
    error = ErrorBody(code=code, message=message_for(code))
    return ResponseEnvelope(
        conversation_id=None, seq=0, events=(), pending_proposal_id=None, error=error
    )


def is_api(path: str) -> bool:
    return path in ("/v1", "/health") or path.startswith(("/v1/", "/health/"))


class RequestGuard:
    def __init__(self, app: ASGIApp, allow: AllowList, max_body: int = MAX_BODY) -> None:
        self.app, self.allow, self.max_body = app, allow, max_body

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":  # no WebSocket route exists: close before the app sees it
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            return
        secured = _secured(scope["path"], send)
        rejected = self._check(scope["method"], Headers(scope=scope))
        body = rejected or await _read(receive, self.max_body)
        if isinstance(body, WebErrorCode):
            log.info("request rejected: %s", body.value)
            await _reject(body, secured)
        elif body is not None:  # None: the client left while sending
            await self.app(scope, _replay(body, receive), secured)

    def _check(self, method: str, headers: Headers) -> WebErrorCode | None:
        hosts = headers.getlist("host")
        if len(hosts) != 1 or hosts[0].lower() not in self.allow.hosts:
            return WebErrorCode.INVALID_HOST
        if method not in SAFE_METHODS:
            origins = headers.getlist("origin")
            # Fail closed: a browser always sends Origin here, so a missing one is never the page.
            if len(origins) != 1 or origins[0].lower() not in self.allow.origins:
                return WebErrorCode.FORBIDDEN_ORIGIN
            if not _is_json(headers.getlist("content-type")):
                return WebErrorCode.UNSUPPORTED_MEDIA_TYPE
        # Defense in depth: h11 already rejects a repeated or non-decimal Content-Length, so this
        # branch is reached only by another server or a direct ASGI call.
        lengths = headers.getlist("content-length")
        if len(lengths) > 1 or (lengths and not DIGITS.fullmatch(lengths[0])):
            return WebErrorCode.INVALID_REQUEST
        if lengths and int(lengths[0]) > self.max_body:
            return WebErrorCode.PAYLOAD_TOO_LARGE
        return None


def _is_json(values: list[str]) -> bool:
    if len(values) != 1:
        return False
    media, *params = (part.strip().lower() for part in values[0].split(";"))
    return media == "application/json" and all(
        p.replace(" ", "") in ("charset=utf-8", 'charset="utf-8"') for p in params
    )


async def _read(receive: Receive, cap: int) -> bytes | WebErrorCode | None:
    """The whole body, `payload_too_large` as soon as it passes `cap`, or None on disconnect."""
    chunks, size = list[bytes](), 0
    while True:
        message = await receive()
        if message["type"] != "http.request":
            return None
        chunk = message.get("body", b"")
        size += len(chunk)
        if size > cap:
            return WebErrorCode.PAYLOAD_TOO_LARGE
        chunks.append(chunk)
        if not message.get("more_body", False):
            return b"".join(chunks)


def _replay(body: bytes, receive: Receive) -> Receive:
    """The body already read, as one message; later calls (a disconnect) reach the client."""
    sent = False

    async def replay() -> Message:
        nonlocal sent
        if sent:
            return await receive()
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return replay


def _secured(path: str, send: Send) -> Send:
    async def secured(message: Message) -> None:
        if message["type"] == "http.response.start":
            headers = MutableHeaders(scope=message)
            for name, value in SECURITY_HEADERS.items():
                headers[name] = value
            if is_api(path):
                headers["cache-control"] = "no-store"
        await send(message)

    return secured


async def _reject(code: WebErrorCode, send: Send) -> None:
    body = error_envelope(code).model_dump_json().encode()
    headers = [(b"content-type", b"application/json"), (b"connection", b"close")]
    headers.append((b"content-length", str(len(body)).encode()))
    await send({"type": "http.response.start", "status": status_for(code), "headers": headers})
    await send({"type": "http.response.body", "body": body})

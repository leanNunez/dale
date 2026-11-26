"""The request guard (W8, W10, W17; design §4.2): a pure ASGI middleware that wraps the whole
application, so it runs before routing and before any handler.

Checks, in this order, each rejecting with the one error envelope:
1. exactly one `Host`, in the allow-list (`invalid_host`); a missing one is rejected too;
2. on any method but GET and HEAD, exactly one `Origin`, in the allow-list (`forbidden_origin`);
   a missing one is rejected too, because browsers send `Origin` on every POST, same-origin
   included.

Every response, a rejection included, carries the CSP, `nosniff` and `no-referrer` headers; API
paths also carry `Cache-Control: no-store`. Rejections never echo the request.
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, Self

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from dale.channels.web.contract import ErrorBody, ResponseEnvelope
from dale.channels.web.errors import WebErrorCode, message_for, status_for
from dale.shared.errors import ErrorCode

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
    return path in ("/v1", "/health") or path.startswith("/v1/")


class RequestGuard:
    def __init__(self, app: ASGIApp, allow: AllowList) -> None:
        self.app, self.allow = app, allow

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
        if rejected is not None:
            log.info("request rejected: %s", rejected.value)
            await _reject(rejected, secured)
        else:
            await self.app(scope, receive, secured)

    def _check(self, method: str, headers: Headers) -> WebErrorCode | None:
        hosts = headers.getlist("host")
        if len(hosts) != 1 or hosts[0].lower() not in self.allow.hosts:
            return WebErrorCode.INVALID_HOST
        if method not in SAFE_METHODS:
            origins = headers.getlist("origin")
            # Fail closed: a browser always sends Origin here, so a missing one is never the page.
            if len(origins) != 1 or origins[0].lower() not in self.allow.origins:
                return WebErrorCode.FORBIDDEN_ORIGIN
        return None


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

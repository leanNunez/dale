"""The demo session (O2, W8 S8.8, DD34, ADR 0010; log D18, D24, D72, D73): design §4 step 3.

Between the guard and the routes, in demo mode only, it reads the cookie on a create (`POST
/v1/conversations`) and on any path under `/v1/conversations/`, and on nothing else: pages, static
files and the metadata routes neither read nor set it. A create with no valid session gets a new
one; a valid one is kept (no rotation), so a cross-site arrival, which carries no cookie, never
replaces a live session. A conversation request with no valid session answers
`conversation_not_found` before any handler runs. Valid means exactly one pair of that name across
every `Cookie` line, holding the canonical unpadded base64url of 32 bytes. Paths are read as the
router does (`root_path` stripped). Routes get a `Visitor` under `VISITOR_KEY`, not the `Cookie`
header; the token is never kept, logged or echoed.
"""

import base64
import hashlib
import hmac
import re
import secrets
from typing import Final

from starlette._utils import get_route_path
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from dale.channels.web.client import STATE_KEY
from dale.channels.web.demo import Visitor
from dale.channels.web.errors import WebErrorCode
from dale.channels.web.routes import error_response

COOKIE: Final = "__Host-dale_session"
ATTRIBUTES: Final = "HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=86400"  # log D18
VISITOR_KEY: Final = "visitor"
CREATE: Final = "/v1/conversations"
TOKEN_BYTES: Final = 32
MIN_KEY: Final = 32
TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")


def new_token() -> str:
    return _encode(secrets.token_bytes(TOKEN_BYTES))


def session_hash(key: bytes, token: str) -> bytes:
    return hmac.new(key, b"session|" + token.encode("ascii"), hashlib.sha256).digest()


def token_of(lines: list[str]) -> str | None:
    """The one valid token among every `Cookie` line, or None."""
    pairs = (pair.strip().partition("=") for line in lines for pair in line.split(";"))
    found = [value for name, equals, value in pairs if equals and name == COOKIE]
    if len(found) != 1 or not TOKEN.fullmatch(found[0]):
        return None
    canonical = _encode(base64.urlsafe_b64decode(found[0] + "="))
    return found[0] if canonical == found[0] else None


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


class SessionLayer:
    def __init__(self, app: ASGIApp, key: bytes) -> None:
        if len(key) < MIN_KEY:
            raise ValueError(f"the session key must be at least {MIN_KEY} bytes")
        self.app, self._key = app, key

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = get_route_path(scope) if scope["type"] == "http" else ""  # as the router does
        create = scope["type"] == "http" and scope["method"] == "POST" and path == CREATE
        if not (create or path.startswith(f"{CREATE}/")):
            await self.app(scope, receive, send)
            return
        state = scope.get("state", {})
        token = token_of(Headers(scope=scope).getlist("cookie"))
        rejected = None if token or create else WebErrorCode.CONVERSATION_NOT_FOUND
        if STATE_KEY not in state:  # the guard's demo step did not run: fail closed
            rejected = WebErrorCode.INVALID_REQUEST
        if rejected is not None:
            await error_response(rejected)(scope, receive, send)
            return
        if token is None:
            token = new_token()
            send = _setting(token, send)
        state = {**state, VISITOR_KEY: Visitor(session_hash(self._key, token), state[STATE_KEY])}
        headers = [h for h in scope["headers"] if h[0] != b"cookie"]
        await self.app({**scope, "headers": headers, "state": state}, receive, send)


def _setting(token: str, send: Send) -> Send:
    async def setting(message: Message) -> None:
        if message["type"] == "http.response.start":
            MutableHeaders(scope=message).append("set-cookie", f"{COOKIE}={token}; {ATTRIBUTES}")
        await send(message)

    return setting

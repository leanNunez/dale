"""The web host's application (D12, D14, D25; design §4.2). `create_app` wraps the routes in the
request guard, which sees every request first.

Conversation routes (`routes.py`) answer with one `ResponseEnvelope`; the metadata routes answer
with their documented bodies: `/v1/contract` with `{v, events, commands, demo}` and `/health`
with an empty envelope. Every error, on any path, is one `ResponseEnvelope`. The exception
handlers replace FastAPI's default bodies (its validation body echoes the input): an unknown path
or method, an invalid body and an unexpected exception each answer with their catalog code and
fixed message, never with the exception text, which goes only to the log. `/docs`, `/redoc` and
`/openapi.json` are off, there is no CORS middleware and no trailing-slash redirect (`/health/` is
unknown, and no `Location` echoes the `Host`). The built page is served from the same origin when
its directory exists; until it is built, `/` answers `not_found` like any unknown path. Demo mode
adds the session layer (`session.py`) between the guard and the routes; local mode sets no cookie.
"""

import logging
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp

from dale.channels.web.contract import (
    COMMANDS,
    COMPONENTS,
    ContractInfo,
    DemoInfo,
    ResponseEnvelope,
)
from dale.channels.web.conversations import ConversationRegistry
from dale.channels.web.demo import Notice
from dale.channels.web.errors import WebErrorCode
from dale.channels.web.guard import AllowList, RequestGuard
from dale.channels.web.routes import add_routes, envelope_response, error_response
from dale.channels.web.session import SessionLayer
from dale.shared.errors import ErrorCode

log = logging.getLogger(__name__)
type Ready = Callable[[], bool]  # can the rules be read? (`SELECT 1` on the app database)


async def _http_error(request: Request, error: HTTPException) -> Response:
    status = error.status_code
    if status == 405:  # keeps `Allow`
        return error_response(WebErrorCode.METHOD_NOT_ALLOWED, error.headers)
    if status == 404:
        return error_response(WebErrorCode.NOT_FOUND)
    return error_response(
        WebErrorCode.INVALID_REQUEST if status < 500 else WebErrorCode.INTERNAL_ERROR
    )


async def _invalid(request: Request, error: Exception) -> Response:
    return error_response(WebErrorCode.INVALID_REQUEST)


async def _unexpected(request: Request, error: Exception) -> Response:
    log.error("unexpected %s on %s", type(error).__name__, request.url.path, exc_info=error)
    return error_response(WebErrorCode.INTERNAL_ERROR)


def build_api(
    ready: Ready, page: Path | None, registry: ConversationRegistry, demo: Notice | None = None
) -> FastAPI:
    """The routes and handlers without the guard (`create_app` adds it). `demo` is the notice of
    demo mode, which the page reads to show its banner; `None` is local mode (DD42)."""
    api = FastAPI(
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        redirect_slashes=False,
        exception_handlers={
            HTTPException: _http_error,
            RequestValidationError: _invalid,
            Exception: _unexpected,
        },
    )

    @api.api_route("/v1/contract", methods=["GET", "HEAD"])
    def contract() -> ContractInfo:
        found = (
            None
            if demo is None
            else DemoInfo(notice_version=demo.version, retention_days=demo.retention_days)
        )
        return ContractInfo(events=tuple(COMPONENTS), commands=tuple(COMMANDS), demo=found)

    @api.api_route("/health", methods=["GET", "HEAD"])
    def health() -> Response:
        """Fail closed (D25): a probe that raises is a database that cannot be read."""
        try:
            up = ready()
        except Exception as error:
            log.warning("health probe failed: %s", type(error).__name__)
            up = False
        if not up:
            return error_response(ErrorCode.RULES_UNAVAILABLE)
        empty = ResponseEnvelope(
            conversation_id=None, seq=0, events=(), pending_proposal_id=None, error=None
        )
        return envelope_response(empty, 200)

    add_routes(api, registry)
    # The mount is the last thing done here: it matches every path, so every route, those of
    # later slices included, must be registered above it.
    if page is not None and page.is_dir():
        api.mount("/", StaticFiles(directory=page, html=True), name="page")
    return api


def create_app(
    allow: AllowList,
    ready: Ready,
    page: Path | None,
    registry: ConversationRegistry,
    demo: Notice | None = None,
    session_key: bytes | None = None,
) -> RequestGuard:
    """The guarded application. Demo mode (a notice) needs the session key, local mode takes
    none: demo mode adds the guard's client IP step (DD36) and the session layer (DD34)."""
    if (demo is None) != (session_key is None):
        raise ValueError("demo mode needs a session key, and local mode takes none")
    app: ASGIApp = build_api(ready, page, registry, demo)
    if session_key is not None:
        app = SessionLayer(app, session_key)
    return RequestGuard(app, allow, demo=demo is not None)

"""CSRF without a token (W8, DD35, ADR 0010; log D74): every state-changing route is closed by
at least two checks, and each check alone rejects a cross-site request the others let through.
A sibling subdomain is same-site, so it sends the session cookie; an allowed foreign origin
stands for an Origin check that let it through; `SameSite=Strict` sends no cookie cross-site."""

import json
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from starlette.datastructures import Headers
from starlette.routing import Mount
from starlette.testclient import TestClient
from starlette.types import Receive, Scope, Send

from dale.channels.web.app import build_api
from dale.channels.web.conversations import InMemoryRegistry
from dale.channels.web.demo import NOTICE
from dale.channels.web.errors import WebErrorCode, status_for
from dale.channels.web.guard import SAFE_METHODS
from dale.channels.web.session import COOKIE
from tests.unit.channels.web.test_conversations import FakeBackend
from tests.unit.channels.web.test_guard import rejected
from tests.unit.channels.web.test_session import (
    CHANGING,
    CREATE,
    EVIL,
    PEER,
    POST,
    SIBLING,
    SITE,
    Host,
    Seen,
    T,
    issued,
    jar,
    layered,
)


def test_these_are_all_the_state_changing_routes(tmp_path: Path) -> None:
    """In demo mode with the page, so a demo-only route or a plain route fails the proof."""
    routes = build_api(lambda: True, tmp_path, InMemoryRegistry(FakeBackend), NOTICE).routes
    others = [r for r in routes if not isinstance(r, APIRoute)]
    assert len(others) == 1 and isinstance(others[0], Mount) and others[0].name == "page"
    found = {(m, r.path) for r in routes if isinstance(r, APIRoute) for m in r.methods or ()}
    assert {route for route in found if route[0] not in SAFE_METHODS} == set(CHANGING)


FORMS = ("text/plain", "application/x-www-form-urlencoded", "multipart/form-data", "")
CROSS_SITE = {  # DD35: each check alone rejects a cross-site request the others let through
    **{
        f"origin {name}": ((), {"origin": origin, **jar()}, WebErrorCode.FORBIDDEN_ORIGIN)
        for name, origin in (("foreign", EVIL), ("sibling", SIBLING), ("missing", ""))
    },
    **{
        f"json {media or 'missing'}": (
            (EVIL,),
            {"origin": EVIL, "content-type": media, **jar()},
            WebErrorCode.UNSUPPORTED_MEDIA_TYPE,
        )
        for media in FORMS
    },
    "no cookie": ((EVIL,), {"origin": EVIL}, WebErrorCode.CONVERSATION_NOT_FOUND),
}
CASES = {  # a create has no session check, so Origin and JSON are its two
    f"{route[1].rsplit('/', 1)[-1]}, {name}": (route, *case)
    for route in CHANGING
    for name, case in CROSS_SITE.items()
    if route != CREATE or name != "no cookie"
}


@pytest.mark.parametrize(("route", "origins", "headers", "code"), CASES.values(), ids=CASES)
def test_each_csrf_check_alone_rejects(
    route: tuple[str, str],
    origins: tuple[str, ...],
    headers: dict[str, str],
    code: WebErrorCode,
) -> None:
    target = Host(None, origins=origins)
    talk, before = target.opened(), target.ran()
    response = target.call(route, talk, **headers)
    rejected(response, code, status_for(code))
    assert target.ran() == before and not issued(response)


def test_a_json_post_from_another_site_gets_no_preflight_answer() -> None:
    preflight = {"origin": EVIL, "access-control-request-method": "POST"}
    response = Host(None).client.options("/v1/conversations", headers=preflight)
    rejected(response, WebErrorCode.FORBIDDEN_ORIGIN, 403)
    assert not [h for h in response.headers if h.lower().startswith("access-control")]
    bypassed = Host(None, origins=(EVIL,)).client.options("/v1/conversations", headers=preflight)
    rejected(bypassed, WebErrorCode.UNSUPPORTED_MEDIA_TYPE, 415)  # no Origin check, still no CORS
    assert not [h for h in bypassed.headers if h.lower().startswith("access-control")]


@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.parametrize("tail", ["messages", "confirm", "cancel", "other", ""])
def test_no_get_under_a_conversation_changes_state(method: str, tail: str) -> None:
    target = Host(None)
    talk = target.opened()
    before = target.ran()
    for headers in ({}, jar()):
        response = target.client.request(
            method, f"/v1/conversations/{talk}/{tail}", headers=headers
        )
        assert response.status_code in (404, 405) and not issued(response)
    assert target.ran() == before


@pytest.mark.parametrize("route", CHANGING, ids=lambda r: r[1].rsplit("/", 1)[-1])
def test_a_root_path_cannot_hide_a_conversation_route_from_the_session(
    route: tuple[str, str],
) -> None:
    """Starlette routes on the path with `root_path` stripped, so the session layer reads that
    same path: with no cookie a create gets one and the rest answer `conversation_not_found`."""
    target = Host(None)
    talk, before = target.opened(), target.ran()
    prefixed = TestClient(target.client.app, SITE, root_path="/app", client=(PEER, 1))
    url = "/app" + route[1].format(conversation_id=talk)
    body = json.dumps(CHANGING[route]).encode()
    response = prefixed.post(url, headers={**POST}, content=body)
    if route == CREATE:
        assert response.status_code == 201 and len(issued(response)) == 1
    else:
        rejected(response, WebErrorCode.CONVERSATION_NOT_FOUND, 404)
        assert target.ran() == before and not issued(response)


class Cookies(Seen):
    """What the routes receive: the `Cookie` lines of each request."""

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[list[str]] = []

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.lines.append(Headers(scope=scope).getlist("cookie"))
        await super().__call__(scope, receive, send)


def test_the_routes_never_receive_the_cookie_header() -> None:
    """D73: the token is kept nowhere, so the `Cookie` header goes no further than the layer."""
    probe, cookies = Cookies(), [("cookie", f"a=b; {COOKIE}={T}"), ("cookie", "c=d")]
    client = layered(probe)
    client.post("/v1/conversations", headers=[*POST.items(), *cookies])
    client.post("/v1/conversations/x/messages", headers=[*POST.items(), *cookies])
    client.post("/v1/conversations", headers=POST)
    assert probe.lines == [[], [], []] and all(probe.visitors)

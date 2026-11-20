"""The host's route table (W2 S2.1, W1 S1.2) and a restart (W17 S17.2): exactly the listed
operations plus the page mount, one route that can press, no CORS header, and conversations that
do not survive the process."""

from pathlib import Path

import httpx2 as httpx
from fastapi.routing import APIRoute
from starlette.routing import Mount
from starlette.testclient import TestClient

from dale.channels.web.app import build_api, create_app
from dale.channels.web.conversations import InMemoryRegistry
from dale.channels.web.guard import AllowList
from tests.unit.channels.web.test_conversations import DONE, HELLO, PID, SUMMARY, FakeBackend, said
from tests.unit.channels.web.test_routes import (
    PORT,
    POST,
    code,
    envelope,
    host,
    opened,
    post,
    send,
)

TALK = "/v1/conversations/{conversation_id}"
TABLE = {
    ("POST", "/v1/conversations"),
    ("POST", f"{TALK}/messages"),
    ("POST", f"{TALK}/confirm"),
    ("POST", f"{TALK}/cancel"),
    ("GET", "/v1/contract"),
    ("HEAD", "/v1/contract"),
    ("GET", "/health"),
    ("HEAD", "/health"),
}
# A valid body for every route, each naming the pending proposal where it can carry an id.
BODIES = {"messages": {"text": f"dale, confirmá {PID}"}, "confirm": {"proposal_id": str(PID)}}
BODIES["cancel"] = BODIES["confirm"]


def built_page(tmp_path: Path) -> Path:
    (tmp_path / "index.html").write_text("<!doctype html>", encoding="utf-8")
    return tmp_path


def test_the_route_table_is_exactly_the_listed_operations_and_the_page(tmp_path: Path) -> None:
    """S2.1: no docs, no OpenAPI, nothing else; the page mount comes last (B43)."""
    api = build_api(lambda: True, built_page(tmp_path), InMemoryRegistry(FakeBackend))
    *routes, page = api.routes
    assert isinstance(page, Mount) and page.name == "page" and page.path == ""
    assert all(isinstance(route, APIRoute) for route in routes)
    table = {(m, r.path) for r in routes if isinstance(r, APIRoute) for m in r.methods or ()}
    assert table == TABLE and len(routes) == 6


def test_exactly_one_route_can_press_and_none_sends_a_cors_header(tmp_path: Path) -> None:
    """S2.1, S1.2: every route of the table, called with a valid body while a proposal is
    pending (in its own conversation); only `/confirm` reaches the brain's confirm."""
    backends: list[FakeBackend] = []

    def backend() -> FakeBackend:
        backends.append(FakeBackend([said([HELLO, SUMMARY]), said([HELLO])], [DONE]))
        return backends[-1]

    registry = InMemoryRegistry(backend)
    app = create_app(AllowList.loopback(PORT), lambda: True, built_page(tmp_path), registry)
    client = TestClient(app, base_url=f"http://127.0.0.1:{PORT}")
    pressed: list[tuple[str, str]] = []
    responses: list[httpx.Response] = []

    def presses() -> int:
        return sum(len(b.pressed) for b in backends)

    for method, path in sorted(TABLE):
        talk = opened(client)
        send(client, talk, {"text": "quiero yerba"})  # PID is pending
        url, action, before = path.format(conversation_id=talk), path.rsplit("/", 1)[-1], presses()
        responses.append(client.request(method, url, headers=POST, json=BODIES.get(action, {})))
        if presses() > before:
            pressed.append((method, path))
    assert pressed == [("POST", f"{TALK}/confirm")] and presses() == 1
    assert len(backends) == len(TABLE) + 1  # one per conversation, the created one included
    assert not [h for r in responses for h in r.headers if h.lower().startswith("access-control")]


def test_a_restart_rejects_old_conversations_and_a_new_one_works() -> None:
    """S17.2: conversations live in the process; a new host knows none of them."""
    before = host(FakeBackend())
    old = opened(before)
    after = host(FakeBackend([said([HELLO])]))
    for action, body in (("messages", {"text": "hola"}), *BODIES.items()):
        response = post(after, f"/v1/conversations/{old}/{action}", body)
        assert (response.status_code, code(response)) == (404, "conversation_not_found")
        assert envelope(response).events == () and envelope(response).conversation_id is None
    response = send(after, opened(after), {"text": "hola"})
    assert (response.status_code, code(response)) == (200, None)

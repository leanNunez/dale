"""The client IP of a demo request (W8 S8.5-S8.7, S8.9, S8.10; O3 S3.6; DD36, ADR 0010): only the
value the loopback proxy appended is trusted, a demo request with none is rejected before any
handler, and local mode never reads the header."""

import logging
from collections.abc import Iterator

import pytest
from hypothesis import given
from hypothesis import strategies as st
from starlette.testclient import TestClient
from starlette.types import Receive, Scope, Send

from dale.channels.web.app import create_app
from dale.channels.web.client import STATE_KEY, client_ip
from dale.channels.web.conversations import InMemoryRegistry
from dale.channels.web.demo import NOTICE
from dale.channels.web.errors import WebErrorCode
from dale.channels.web.guard import MAX_BODY, AllowList, RequestGuard
from tests.unit.channels.web.test_conversations import FakeBackend
from tests.unit.channels.web.test_guard import rejected

PORT = 8000
LOOPBACK = f"http://127.0.0.1:{PORT}"
POST = {"content-type": "application/json", "origin": LOOPBACK}
SENT, APPENDED, REMOTE = "198.51.100.9", "203.0.113.7", "192.0.2.10"  # documentation ranges
CHAIN = f"{SENT}, {APPENDED}"


@pytest.mark.parametrize("peer", ["127.0.0.1", "::1", "::ffff:127.0.0.1"])
def test_a_loopback_peer_gives_the_value_the_proxy_appended(peer: str) -> None:
    """S8.5: the first element is the client's; only the last one is the proxy's."""
    assert client_ip(peer, [CHAIN]) == APPENDED


@pytest.mark.parametrize(
    ("peer", "found"),
    [(REMOTE, REMOTE), ("2001:db8::5", "2001:db8::5"), ("127.0.0.2", "127.0.0.2")],
)
def test_any_other_peer_ignores_the_header(peer: str, found: str) -> None:
    """S8.6: only `127.0.0.1` and `::1` are the proxy; another loopback address is not."""
    assert client_ip(peer, [CHAIN]) == found


@pytest.mark.parametrize("peer", [None, "testclient", "", "::1%lo", "127.0.0.1:8000"])
def test_a_peer_that_is_not_an_address_gives_none_and_never_reads_the_header(
    peer: str | None,
) -> None:
    assert client_ip(peer, [CHAIN]) is None


@pytest.mark.parametrize(
    "lines",
    [
        [],
        [""],
        ["  "],
        ["unknown"],
        [f"{APPENDED},"],  # an empty last element never falls back to an earlier one
        [f"{SENT}, {APPENDED}, "],
        [f"{APPENDED}:443"],
        ["[2001:db8::7]"],
        ["fe80::7%eth0"],
        [f"{SENT} {APPENDED}"],
        ["999.0.113.7"],
        ["203.0.113.07"],
        ["3405803783"],
        ["1" * 60_000],
        [APPENDED, ""],  # only the last field counts
    ],
)
def test_an_empty_garbage_or_missing_value_gives_none(lines: list[str]) -> None:
    assert client_ip("127.0.0.1", lines) is None


@pytest.mark.parametrize(
    ("lines", "found"),
    [
        ([f"{SENT},{APPENDED}"], APPENDED),
        ([f" {SENT} ,\t{APPENDED} "], APPENDED),
        ([f"{SENT}, 2001:DB8:0::7"], "2001:db8::7"),  # IPv6 parses, in its canonical form
        ([f"::ffff:{APPENDED}"], APPENDED),
        ([APPENDED, SENT], SENT),  # several fields: the last one is the proxy's
        ([f"{'x' * 60_000}, {APPENDED}"], APPENDED),
    ],
)
def test_the_last_element_of_the_last_field_is_parsed(lines: list[str], found: str) -> None:
    assert client_ip("::1", lines) == found


@given(st.lists(st.text()), st.text())
def test_nothing_the_client_sends_before_the_proxy_changes_the_ip(
    earlier: list[str], prefix: str
) -> None:
    """Whatever earlier fields and elements say, the appended value alone decides."""
    assert client_ip("127.0.0.1", [*earlier, f"{prefix},{APPENDED}"]) == APPENDED


class Seen:
    """The application behind the guard: it records the client IP each handled request carried."""

    def __init__(self) -> None:
        self.ips: list[object] = []

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            while (await receive())["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            await send({"type": "lifespan.shutdown.complete"})
            return
        await receive()
        self.ips.append(scope.get("state", {}).get(STATE_KEY, "absent"))
        headers = [(b"content-type", b"application/json")]
        await send({"type": "http.response.start", "status": 200, "headers": headers})
        await send({"type": "http.response.body", "body": b"{}"})


@pytest.fixture
def app() -> Seen:
    return Seen()


def guarded(app: Seen, peer: str, demo: bool) -> TestClient:
    guard = RequestGuard(app, AllowList.loopback(PORT), demo=demo)
    return TestClient(guard, base_url=LOOPBACK, client=(peer, 50000))


@pytest.mark.parametrize("peer", ["127.0.0.1", "::1"])
@pytest.mark.parametrize("forwarded", [None, "", "unknown", f"{APPENDED}, "])
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_demo_mode_rejects_a_loopback_request_with_no_usable_ip(
    app: Seen, peer: str, forwarded: str | None, method: str
) -> None:
    """S8.7: before any handler, and nothing executes."""
    headers = POST if forwarded is None else {**POST, "x-forwarded-for": forwarded}
    response = guarded(app, peer, True).request(method, "/v1/x", headers=headers, content=b"{}")
    rejected(response, WebErrorCode.INVALID_REQUEST, 422)
    assert app.ips == []


@pytest.mark.parametrize(("peer", "found"), [("127.0.0.1", APPENDED), (REMOTE, REMOTE)])
def test_demo_mode_hands_the_client_ip_to_the_application(app: Seen, peer: str, found: str) -> None:
    """S8.5 and S8.6 through the guard; the header line the client sent is never the IP."""
    headers = [("x-forwarded-for", SENT), ("x-forwarded-for", CHAIN)]
    client = guarded(app, peer, True)
    assert client.post("/v1/x", headers=[*POST.items(), *headers], content=b"{}").status_code == 200
    assert app.ips == [found]


@pytest.mark.parametrize("demo", [True, False], ids=["demo", "local"])
@pytest.mark.parametrize(
    ("headers", "code"),
    [
        ({"host": "evil.example", "x-forwarded-host": f"127.0.0.1:{PORT}"}, "invalid_host"),
        ({"host": "evil.example", "forwarded": f'host="127.0.0.1:{PORT}"'}, "invalid_host"),
        (
            {"origin": "https://evil.example", "x-forwarded-host": "evil.example"},
            "forbidden_origin",
        ),
    ],
)
def test_forwarded_host_headers_never_change_the_host_or_origin_decision(
    app: Seen, demo: bool, headers: dict[str, str], code: str
) -> None:
    """S8.9: a forwarded host naming an allowed name does not rescue a foreign `Host`."""
    sent = {**POST, "x-forwarded-for": CHAIN, **headers}
    response = guarded(app, "127.0.0.1", demo).post("/v1/x", headers=sent, content=b"{}")
    rejected(response, WebErrorCode(code), {"invalid_host": 400}.get(code, 403))
    assert app.ips == []


def test_demo_mode_checks_host_and_origin_before_the_client_ip(app: Seen) -> None:
    """§4 order: step 1 rejects a foreign `Host` even when step 2 would also reject."""
    response = guarded(app, "127.0.0.1", True).get("/v1/x", headers={"host": "evil.example"})
    rejected(response, WebErrorCode.INVALID_HOST, 400)


def test_demo_mode_rejects_no_ip_before_reading_the_body(app: Seen) -> None:
    """Step 2 runs on the headers (log D69): a streamed body with no IP is never counted."""
    body = iter([b" " * (MAX_BODY + 1)])  # no Content-Length, so only counting would reject it
    response = guarded(app, "127.0.0.1", True).post("/v1/x", headers=POST, content=body)
    rejected(response, WebErrorCode.INVALID_REQUEST, 422)


@pytest.mark.parametrize("forwarded", [None, "", "unknown", CHAIN])
def test_local_mode_ignores_the_forwarded_header(app: Seen, forwarded: str | None) -> None:
    """S8.10: the header changes no decision, and no client IP reaches the application."""
    headers = POST if forwarded is None else {**POST, "x-forwarded-for": forwarded}
    response = guarded(app, "127.0.0.1", False).post("/v1/x", headers=headers, content=b"{}")
    assert response.status_code == 200 and app.ips == ["absent"]


def hosts(demo: bool, peer: str = "127.0.0.1") -> TestClient:
    registry = InMemoryRegistry(FakeBackend)
    modes = (NOTICE, b"k" * 32) if demo else (None, None)
    app = create_app(AllowList.loopback(PORT), lambda: True, None, registry, *modes)
    return TestClient(app, base_url=LOOPBACK, client=(peer, 50000), raise_server_exceptions=False)


def test_create_app_turns_the_client_ip_check_on_only_in_demo_mode() -> None:
    """D62: the notice is the demo flag; the channel reads no environment."""
    rejected(hosts(True).get("/v1/contract"), WebErrorCode.INVALID_REQUEST, 422)
    assert hosts(True).get("/v1/contract", headers={"x-forwarded-for": CHAIN}).status_code == 200
    assert hosts(False).get("/v1/contract").status_code == 200


@pytest.fixture
def demo_host() -> Iterator[TestClient]:
    with hosts(True) as client:
        yield client


def test_no_log_line_holds_a_clear_ip(
    demo_host: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """S3.6: accepted, rejected and failed requests, from the proxy and from another peer.

    uvicorn's access log is out of reach here: it prints only `scope["client"]`, which stays the
    proxy's `127.0.0.1` because `proxy_headers=False` is pinned (log D71)."""
    forwarded = {"x-forwarded-for": CHAIN}
    with caplog.at_level(logging.DEBUG):
        responses = [
            demo_host.get("/v1/contract", headers=forwarded),
            demo_host.get("/v1/contract"),
            demo_host.get("/v1/contract", headers={"x-forwarded-for": f"{CHAIN}, {SENT}:1"}),
            demo_host.get("/v1/contract", headers={"host": "evil.example", **forwarded}),
            demo_host.post("/v1/conversations", headers={**POST, **forwarded}, content=b"{"),
            demo_host.post("/v1/conversations/x/messages", headers={**POST, **forwarded}),
            demo_host.post("/v1/x", headers={"origin": "https://evil.example", **forwarded}),
        ]
        with hosts(True, REMOTE) as remote:
            responses += [remote.get(path, headers=forwarded) for path in ("/v1/contract", "/v")]
    codes = [response.status_code for response in responses]
    assert codes == [200, 422, 422, 400, 201, 404, 403, 200, 404]  # demo mode (404: no session)
    lines = [f"{r.getMessage()} {r.exc_text or ''} {r.__dict__}" for r in caplog.records]
    assert lines and not [line for line in lines if any(ip in line for ip in (SENT, APPENDED))]
    assert not [line for line in lines if REMOTE in line]

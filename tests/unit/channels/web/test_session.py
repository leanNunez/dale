"""The demo session cookie (W8 S8.8, S8.10; O2 S2.1, S2.3, S2.4; DD34, ADR 0010; log D72, D73):
only a create issues the cookie, routes see only its keyed hash, a cross-site arrival keeps the
live session, local mode sets no cookie, and no GET changes state."""

import base64
import hashlib
import hmac
import json
import logging
from pathlib import Path
from typing import Any

import httpx2 as httpx
import pytest
from starlette.testclient import TestClient
from starlette.types import Receive, Scope, Send

from dale.channels.web.app import create_app
from dale.channels.web.conversations import InMemoryRegistry
from dale.channels.web.demo import NOTICE, Visitor
from dale.channels.web.errors import WebErrorCode
from dale.channels.web.guard import AllowList, RequestGuard
from dale.channels.web.session import COOKIE, VISITOR_KEY, SessionLayer
from tests.unit.channels.web.test_conversations import HELLO, PID, FakeBackend, said
from tests.unit.channels.web.test_guard import rejected

PORT = 8000
SITE, EVIL, SIBLING = f"http://127.0.0.1:{PORT}", "https://evil.example", "https://x.dale.test"
POST = {"content-type": "application/json", "origin": SITE}
KEY, PEER, IP = b"k" * 32, "192.0.2.10", "203.0.113.7"
ATTRIBUTES = "HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=86400"
TALK, CREATE = "/v1/conversations/{conversation_id}", ("POST", "/v1/conversations")
CHANGING = {  # every state-changing route, with a valid body
    CREATE: {},
    ("POST", f"{TALK}/messages"): {"text": "hola"},
    ("POST", f"{TALK}/confirm"): {"proposal_id": str(PID)},
    ("POST", f"{TALK}/cancel"): {"proposal_id": str(PID)},
}
OWNED = [route for route in CHANGING if route != CREATE]
READS = [("GET", p) for p in ("/", "/privacidad", "/assets/app.js", "/v1/contract", "/health")]
READS += [("HEAD", "/"), ("HEAD", "/v1/contract"), ("GET", "/v1/conversations")]


def token(raw: bytes = b"\xfb\xff" * 16) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


T, ZERO = token(), token(b"\0" * 32)  # T has `-` and `_`; ZERO ends in `A`


def digest(value: str) -> bytes:
    return hmac.new(KEY, b"session|" + value.encode(), hashlib.sha256).digest()


def jar(value: str = T) -> dict[str, str]:
    return {"cookie": f"{COOKIE}={value}"}


def lines(cookies: list[str]) -> list[tuple[str, str]]:
    return [*POST.items(), *(("cookie", line) for line in cookies)]


class Host:
    """The demo (or local) host over a built page; it keeps every backend it builds."""

    def __init__(
        self, page: Path | None, *, local: bool = False, origins: tuple[str, ...] = ()
    ) -> None:
        self.backends: list[FakeBackend] = []
        allow, modes = AllowList.loopback(PORT, origins=origins), () if local else (NOTICE, KEY)
        app = create_app(allow, lambda: True, page, InMemoryRegistry(self._backend), *modes)
        self.client = TestClient(app, SITE, client=(PEER, 1), raise_server_exceptions=False)

    def _backend(self) -> FakeBackend:
        self.backends.append(FakeBackend([said([HELLO])]))
        return self.backends[-1]

    def ran(self) -> int:
        return len(self.backends) + sum(len(b.said) + len(b.pressed) for b in self.backends)

    def call(self, route: tuple[str, str], talk: str = "x", **headers: str) -> httpx.Response:
        """A JSON body on a state-changing route; an empty header value is not sent."""
        body, url = CHANGING.get(route), route[1].format(conversation_id=talk)
        sent = {**POST, **headers} if body is not None else headers
        content = None if body is None else json.dumps(body).encode()
        pairs = [(name, value) for name, value in sent.items() if value]
        return self.client.request(route[0], url, headers=pairs, content=content)

    def opened(self, value: str = T) -> str:
        response = self.call(CREATE, **jar(value))
        assert response.status_code == 201 and not issued(response)
        return str(response.json()["conversation_id"])


def issued(response: httpx.Response) -> list[str]:
    return response.headers.get_list("set-cookie")


def new_token(response: httpx.Response) -> str:
    [line] = issued(response)
    name, _, rest = line.partition("=")
    value, _, attributes = rest.partition("; ")
    assert (name, attributes) == (COOKIE, ATTRIBUTES)  # no Domain, nothing else (S8.8)
    raw = base64.urlsafe_b64decode(value + "=")
    assert len(raw) == 32 and token(raw) == value and value not in response.text
    return value


@pytest.fixture
def page(tmp_path: Path) -> Path:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (tmp_path / "assets" / "app.js").write_text("export {}", encoding="utf-8")
    return tmp_path


@pytest.fixture
def host(page: Path) -> Host:
    return Host(page)


def test_a_create_with_no_cookie_issues_a_new_session_cookie(host: Host) -> None:
    """S8.8, S2.1: exactly these attributes, a fresh token each time, never in the body."""
    first, second = host.call(CREATE), host.call(CREATE)
    assert first.status_code == second.status_code == 201
    assert new_token(first) != new_token(second)


def test_the_token_is_32_bytes_from_secrets(host: Host, monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[int] = []

    def drawn(size: int) -> bytes:
        asked.append(size)
        return b"\xfb\xff" * 16

    monkeypatch.setattr("secrets.token_bytes", drawn)
    assert new_token(host.call(CREATE)) == T and asked == [32]  # unpadded base64url (D73)


class Seen:
    """The application behind the guard and the layer: it keeps each request's visitor."""

    def __init__(self) -> None:
        self.visitors: list[Any] = []

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.visitors.append(scope.get("state", {}).get(VISITOR_KEY))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})


@pytest.fixture
def seen() -> Seen:
    return Seen()


def layered(seen: Seen) -> TestClient:
    """From the proxy: the visitor's address is the one the guard found (log D69)."""
    guard = RequestGuard(SessionLayer(seen, KEY), AllowList.loopback(PORT), demo=True)
    forwarded = {"x-forwarded-for": f"{PEER}, {IP}"}
    return TestClient(guard, base_url=SITE, client=("127.0.0.1", 1), headers=forwarded)


@pytest.mark.parametrize("cookies", [[f"a=b; {COOKIE}={T}; c=d"], ["a=b", f"{COOKIE}={T}"]])
def test_routes_see_only_the_keyed_hash_and_the_client_ip(seen: Seen, cookies: list[str]) -> None:
    """DD34: HMAC-SHA256(key, "session|" + token); a valid cookie is kept, not rotated (S2.4),
    also among other cookies or on its own `Cookie` line (HTTP/2 splits them)."""
    client = layered(seen)
    fresh = new_token(client.post("/v1/conversations", headers=POST))
    kept = client.post("/v1/conversations", headers=lines(cookies))
    client.post("/v1/conversations/x/messages", headers=lines(cookies))
    assert not issued(kept)
    assert seen.visitors == [Visitor(digest(fresh), IP), *[Visitor(digest(T), IP)] * 2]


@pytest.mark.parametrize("route", [*READS, ("POST", "/v1/x"), ("POST", "/v1/conversationsx")])
def test_any_other_route_never_reads_the_cookie(seen: Seen, route: tuple[str, str]) -> None:
    response = layered(seen).request(*route, headers={**POST, **jar()})
    assert response.status_code == 200 and seen.visitors == [None] and not issued(response)


def test_with_no_client_ip_from_the_guard_the_layer_fails_closed(seen: Seen) -> None:
    client = TestClient(SessionLayer(seen, KEY), base_url=SITE)
    for path in ("/v1/conversations", "/v1/conversations/x/messages"):
        rejected(client.post(path, headers={**POST, **jar()}), WebErrorCode.INVALID_REQUEST, 422)
    assert seen.visitors == []


MALFORMED = {
    "empty": [f"{COOKIE}="],
    "no value": [COOKIE],
    "short": [f"{COOKIE}={T[:-1]}"],
    "long": [f"{COOKIE}={T}A"],
    "padded": [f"{COOKIE}={T}="],
    "standard alphabet": [f"{COOKIE}={T.replace('-', '+').replace('_', '/')}"],
    "non-canonical": [f"{COOKIE}={ZERO[:-1]}B"],  # the same 32 bytes, a padding bit set
    "quoted": [f'{COOKIE}="{T}"'],
    "space": [f"{COOKIE}= {T}"],
    "space in the name": [f"{COOKIE} ={T}"],
    "repeated": [f"{COOKIE}={T}; {COOKIE}={T}"],
    "repeated on two lines": [f"{COOKIE}={T}", f"{COOKIE}={ZERO}"],
    "no prefix": [f"dale_session={T}"],
    "lowercase prefix": [f"__host-dale_session={T}"],
}


@pytest.mark.parametrize("cookies", MALFORMED.values(), ids=MALFORMED.keys())
def test_a_malformed_cookie_on_a_create_gets_a_new_one(host: Host, cookies: list[str]) -> None:
    response = host.client.post("/v1/conversations", headers=lines(cookies), json={})
    assert response.status_code == 201 and new_token(response) not in "".join(cookies)


@pytest.mark.parametrize("route", OWNED, ids=lambda r: r[1].rsplit("/", 1)[-1])
@pytest.mark.parametrize("cookies", [[], *MALFORMED.values()], ids=["none", *MALFORMED])
def test_a_conversation_request_with_no_valid_session_is_not_found(
    host: Host, route: tuple[str, str], cookies: list[str]
) -> None:
    """O2: before any handler or body validation, and nothing executes; with its session the
    same conversation runs (ownership arrives in slice 9b)."""
    talk = host.opened()
    url, before = route[1].format(conversation_id=talk), host.ran()
    response = host.client.post(url, headers=lines(cookies), content=b"{")
    rejected(response, WebErrorCode.CONVERSATION_NOT_FOUND, 404)
    assert host.ran() == before and not issued(response)
    response = host.call(OWNED[0], talk, **jar())
    assert response.status_code == 200 and not issued(response) and host.backends[0].said


@pytest.mark.parametrize("route", READS, ids=lambda r: f"{r[0]} {r[1]}")
@pytest.mark.parametrize("cookie", [None, T, T[:-1]], ids=["none", "valid", "malformed"])
def test_no_get_sets_a_cookie_or_changes_state(
    host: Host, route: tuple[str, str], cookie: str | None
) -> None:
    """S2.3: a page, `/privacidad`, a static file or any other GET or HEAD; a malformed cookie
    never breaks a page."""
    response = host.call(route, **({} if cookie is None else jar(cookie)))
    assert not issued(response) and host.ran() == 0
    assert "conversation_not_found" not in response.text


def test_a_cross_site_arrival_keeps_the_existing_session(host: Host) -> None:
    """S2.4: a top-level link from another site sends no cookie (SameSite=Strict)."""
    live = new_token(host.call(CREATE))
    arrival = host.client.get("/")
    assert arrival.status_code == 200 and not issued(arrival)
    foreign = host.call(CREATE, origin=EVIL)
    rejected(foreign, WebErrorCode.FORBIDDEN_ORIGIN, 403)
    assert not issued(foreign)
    host.opened(live)  # the same-site request after it: the original cookie, unchanged


def test_local_mode_sets_no_cookie_on_any_route(page: Path) -> None:
    """S8.10: a conversation runs with no cookie, as in v0.2."""
    local = Host(page, local=True)
    talk = local.call(CREATE).json()["conversation_id"]
    responses = [local.call(route, talk) for route in [*OWNED, *READS, *CHANGING]]
    responses += [local.call(route, talk, **jar()) for route in CHANGING]
    assert responses[0].status_code == 200  # the turn ran, with no cookie
    assert not [line for r in responses for line in issued(r)]


def test_demo_mode_and_the_session_key_come_together(page: Path) -> None:
    """D72: the channel reads no environment, so the composition root passes both or neither."""
    registry = InMemoryRegistry(FakeBackend)
    for modes in ((NOTICE, None), (None, KEY)):
        with pytest.raises(ValueError, match="session key"):
            create_app(AllowList.loopback(PORT), lambda: True, page, registry, *modes)
    with pytest.raises(ValueError, match="32 bytes"):
        SessionLayer(Seen(), b"k" * 31)


def test_no_log_line_and_no_body_holds_a_token(
    host: Host, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        fresh, talk = host.call(CREATE), host.opened()
        responses = [fresh, *(host.call(r, talk, **jar(v)) for r in OWNED for v in (T, T[:-1]))]
    tokens = (new_token(fresh), T, T[:-1])
    texts = [f"{r.getMessage()} {r.exc_text or ''} {r.__dict__}" for r in caplog.records]
    texts += [response.text for response in responses]
    assert not [text for text in texts if any(t in text for t in tokens)]

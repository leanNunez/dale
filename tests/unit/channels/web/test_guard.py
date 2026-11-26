"""The request guard (W8, W10): Host, then Origin, are checked before any handler runs, and every
response carries the CSP."""

import asyncio
from collections.abc import Iterator

import pytest
from starlette.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send

from dale.channels.web.contract import ResponseEnvelope
from dale.channels.web.errors import WebErrorCode, message_for
from dale.channels.web.guard import CSP, AllowList, RequestGuard

PORT = 8000
LOOPBACK = f"http://127.0.0.1:{PORT}"
JSON = {"content-type": "application/json"}


class Recorder:
    """The application behind the guard: it records every request that reaches it."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bytes]] = []

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":  # the test client's startup and shutdown
            while (await receive())["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            await send({"type": "lifespan.shutdown.complete"})
            return
        body = (await receive())["body"]
        self.calls.append((scope["method"], scope["path"], body))
        headers = [(b"content-type", b"application/json")]
        await send({"type": "http.response.start", "status": 200, "headers": headers})
        await send({"type": "http.response.body", "body": b'{"ok":true}'})


@pytest.fixture
def app() -> Recorder:
    return Recorder()


@pytest.fixture
def client(app: Recorder) -> Iterator[TestClient]:
    allow = AllowList.loopback(PORT, hosts=["dale.test:8443"], origins=["https://dale.test:8443"])
    with TestClient(RequestGuard(app, allow), base_url=LOOPBACK) as c:
        yield c


def rejected(response: object, code: WebErrorCode, status: int) -> None:
    assert getattr(response, "status_code") == status  # noqa: B009
    envelope = ResponseEnvelope.model_validate_json(getattr(response, "text"))  # noqa: B009
    assert envelope.error is not None and envelope.error.code is code
    assert envelope.error.message == message_for(code) and envelope.events == ()


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_a_foreign_host_is_rejected_before_any_handler(
    client: TestClient, app: Recorder, method: str
) -> None:
    """S8.2: DNS rebinding sends the attacker's name as Host."""
    response = client.request(method, "/v1/x", headers={"host": "evil.example", **JSON})
    rejected(response, WebErrorCode.INVALID_HOST, 400)
    assert app.calls == [] and "evil" not in response.text


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_a_foreign_origin_on_a_state_changing_request_is_rejected(
    client: TestClient, app: Recorder, method: str
) -> None:
    """S8.1: a cross-origin press never reaches the confirm handler."""
    headers = {"origin": "https://evil.example", **JSON}
    response = client.request(method, "/v1/c/1/confirm", headers=headers, content=b"{}")
    rejected(response, WebErrorCode.FORBIDDEN_ORIGIN, 403)
    assert app.calls == []


@pytest.mark.parametrize("name", ["127.0.0.1", "localhost", "LOCALHOST"])
def test_loopback_host_and_origin_are_handled(client: TestClient, app: Recorder, name: str) -> None:
    """S8.3: the defaults are the loopback names on the host's port."""
    host = f"{name}:{PORT}"
    headers = {"host": host, "origin": f"http://{host}", **JSON}
    assert client.post("/v1/x", headers=headers, content=b"{}").status_code == 200
    assert len(app.calls) == 1


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_a_missing_origin_on_a_state_changing_request_is_rejected(
    client: TestClient, app: Recorder, method: str
) -> None:
    """Fail closed: browsers send Origin on every POST, same-origin included."""
    headers = {"host": f"127.0.0.1:{PORT}", **JSON}
    response = client.request(method, "/v1/x", headers=headers, content=b"{}")
    rejected(response, WebErrorCode.FORBIDDEN_ORIGIN, 403)
    assert app.calls == []


@pytest.mark.parametrize(
    ("host", "origin", "status"),
    [
        ("dale.test:8443", "https://dale.test:8443", 200),
        ("other.test:8443", "https://dale.test:8443", 400),
        ("dale.test:8443", "https://other.test:8443", 403),
        ("127.0.0.1:9000", f"http://127.0.0.1:{PORT}", 400),
        (f"localhost:{PORT}", "http://localhost:9000", 403),
    ],
)
def test_a_configured_name_is_accepted_and_others_still_rejected(
    client: TestClient, host: str, origin: str, status: int
) -> None:
    """S8.4: the allow-list is configuration; the port is part of each name."""
    headers = {"host": host, "origin": origin, **JSON}
    assert client.post("/v1/x", headers=headers, content=b"{}").status_code == status


def call(scope: Scope, messages: list[Message], app: Recorder) -> list[Message]:
    """One raw ASGI call of a loopback guard; returns what it sent."""
    sent: list[Message] = []

    async def receive() -> Message:
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        sent.append(message)

    asyncio.run(RequestGuard(app, AllowList.loopback(PORT))(scope, receive, send))
    return sent


def post(headers: list[tuple[str, str]], chunks: list[bytes], app: Recorder) -> list[Message]:
    """A POST whose body arrives in `chunks`."""
    scope: Scope = {"type": "http", "method": "POST", "path": "/v1/x"}
    scope["headers"] = [(k.encode(), v.encode()) for k, v in headers]
    last = len(chunks) - 1
    body: list[Message] = [
        {"type": "http.request", "body": c, "more_body": i < last} for i, c in enumerate(chunks)
    ]
    return call(scope, body, app)


HOST = [("host", f"127.0.0.1:{PORT}"), ("content-type", "application/json")]


@pytest.mark.parametrize(
    "hosts", [[], ["evil.example", f"127.0.0.1:{PORT}"]], ids=["missing", "repeated"]
)
def test_a_missing_or_repeated_host_is_rejected(app: Recorder, hosts: list[str]) -> None:
    """Fail closed: no Host, or two of them, is never in the allow-list."""
    sent = post([*(("host", h) for h in hosts), HOST[1]], [b"{}"], app)
    assert sent[0]["status"] == 400 and app.calls == []


def test_a_websocket_is_closed_before_the_app(app: Recorder) -> None:
    scope: Scope = {"type": "websocket", "path": "/", "headers": []}
    sent = call(scope, [{"type": "websocket.connect"}], app)
    assert sent == [{"type": "websocket.close", "code": 1008}] and app.calls == []


def sources(policy: str) -> dict[str, list[str]]:
    directives = (d.split() for d in policy.split(";") if d.strip())
    return {name: values for name, *values in directives}


@pytest.mark.parametrize("host", [f"127.0.0.1:{PORT}", "evil.example"], ids=["page", "rejected"])
def test_every_response_has_a_csp_without_inline_script_or_external_origins(
    client: TestClient, host: str
) -> None:
    """S10.1: only 'self', 'none' and data: images; no unsafe-inline, no other origin."""
    response = client.get("/", headers={"host": host})
    policy = sources(response.headers["content-security-policy"])
    assert response.headers["content-security-policy"] == CSP
    assert {v for values in policy.values() for v in values} <= {"'self'", "'none'", "data:"}
    assert policy["script-src"] == ["'self'"] and policy["img-src"] == ["'self'", "data:"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_only_api_paths_are_not_stored(client: TestClient) -> None:
    assert client.get("/v1/contract").headers["cache-control"] == "no-store"
    assert client.get("/health").headers["cache-control"] == "no-store"
    assert "cache-control" not in client.get("/index.html").headers

"""The host's routes and error handlers (W1, W2, W5, W11; D12, D14, D25): one envelope for every
failure, no exception text or echoed input, no docs and no CORS."""

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from dale.channels.web.app import Ready, build_api
from dale.channels.web.contract import COMMANDS, COMPONENTS, ResponseEnvelope, SendMessage
from dale.channels.web.conversations import InMemoryRegistry
from dale.channels.web.errors import WebErrorCode
from dale.channels.web.guard import AllowList, RequestGuard
from dale.shared.errors import ErrorCode
from tests.unit.channels.web.test_conversations import FakeBackend

PORT = 8000
JSON = {"content-type": "application/json", "origin": f"http://127.0.0.1:{PORT}"}
SECRET = "hunter2-in-the-exception"


def probe_api(ready: Ready = lambda: True, page: Path | None = None) -> FastAPI:
    """The real routes and handlers plus two probes: a command body and a handler bug."""
    api = build_api(ready, page, InMemoryRegistry(FakeBackend))

    @api.post("/v1/probe")
    def probe(command: SendMessage) -> dict[str, str]:
        return {"text": command.text}

    @api.get("/v1/bug")
    def bug() -> None:
        raise RuntimeError(SECRET)

    return api


def client_for(api: FastAPI) -> TestClient:
    guard = RequestGuard(api, AllowList.loopback(PORT))
    return TestClient(guard, base_url=f"http://127.0.0.1:{PORT}", raise_server_exceptions=False)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with client_for(probe_api()) as c:
        yield c


def error_of(text: str) -> WebErrorCode | ErrorCode:
    envelope = ResponseEnvelope.model_validate_json(text)
    assert envelope.error is not None and envelope.events == () and envelope.seq == 0
    return envelope.error.code


@pytest.mark.parametrize(
    "body",
    [b'{"text": 5, "token": "s3cr3t-input"}', b'{"text": "s3cr3t-input', b"[]"],
    ids=["wrong-type", "broken-json", "not-an-object"],
)
def test_an_invalid_body_never_echoes_the_input(client: TestClient, body: bytes) -> None:
    """FastAPI's default 422 body lists the input; the envelope carries only the code."""
    response = client.post("/v1/probe", headers=JSON, content=body)
    assert response.status_code == 422 and error_of(response.text) is WebErrorCode.INVALID_REQUEST
    assert "s3cr3t" not in response.text and "detail" not in response.json()


def test_a_valid_command_reaches_its_handler(client: TestClient) -> None:
    response = client.post("/v1/probe", headers=JSON, content=b'{"text": "hola"}')
    assert response.status_code == 200 and response.json() == {"text": "hola"}


def test_an_unexpected_exception_is_generic_and_only_logged(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """S11.3: the code and message are generic; the exception text is only in the log."""
    with caplog.at_level(logging.ERROR, logger="dale.channels.web.app"):
        response = client.get("/v1/bug")
    assert response.status_code == 500 and error_of(response.text) is WebErrorCode.INTERNAL_ERROR
    assert SECRET not in response.text and "RuntimeError" not in response.text
    assert SECRET in caplog.text


def test_four_failure_kinds_share_one_envelope(client: TestClient) -> None:
    """S11.2: validation, a rule rejection, an origin rejection and an unexpected failure."""
    with client_for(probe_api(ready=lambda: False)) as down:
        rule = down.get("/health")
    responses = [
        client.post("/v1/probe", headers=JSON, content=b"{}"),
        rule,
        client.post("/v1/probe", headers={**JSON, "origin": "https://evil.example"}),
        client.get("/v1/bug"),
    ]
    assert [r.status_code for r in responses] == [422, 503, 403, 500]
    assert [error_of(r.text) for r in responses] == [
        WebErrorCode.INVALID_REQUEST,
        ErrorCode.RULES_UNAVAILABLE,
        WebErrorCode.FORBIDDEN_ORIGIN,
        WebErrorCode.INTERNAL_ERROR,
    ]
    shapes = {(tuple(r.json()), tuple(r.json()["error"])) for r in responses}
    assert len(shapes) == 1 and all(
        r.headers["content-type"] == "application/json" for r in responses
    )


@pytest.mark.parametrize(
    "path", ["/v2/contract", "/v1/conversations/x", "/docs", "/redoc", "/openapi.json", "/"]
)
def test_an_unknown_path_is_rejected_with_the_envelope(client: TestClient, path: str) -> None:
    """S2.2, D12: the docs routes are off, and without a built page `/` is unknown too."""
    response = client.get(path)
    assert response.status_code == 404 and error_of(response.text) is WebErrorCode.NOT_FOUND


def test_an_unknown_method_is_rejected_with_the_envelope(client: TestClient) -> None:
    response = client.post("/health", headers=JSON, content=b"{}")
    assert response.status_code == 405
    assert error_of(response.text) is WebErrorCode.METHOD_NOT_ALLOWED
    assert set(response.headers["allow"].split(", ")) == {"GET", "HEAD"}  # a set: any order


@pytest.mark.parametrize("path", ["/health", "/v1/contract"])
def test_head_answers_like_get_without_a_body(client: TestClient, path: str) -> None:
    got, head = client.get(path), client.head(path)
    assert (head.status_code, head.content) == (got.status_code, b"")
    assert {k: v for k, v in head.headers.items() if k != "date"} == dict(got.headers)


@pytest.mark.parametrize("built", [False, True], ids=["no-page", "page"])
@pytest.mark.parametrize("path", ["/health/", "/v1/contract/"])
def test_a_trailing_slash_is_unknown_and_never_redirected(
    tmp_path: Path, built: bool, path: str
) -> None:
    """No 307 with a `Location` built from the `Host`: the slash form is just an unknown path."""
    (tmp_path / "index.html").write_text("<!doctype html>", encoding="utf-8")
    with client_for(probe_api(page=tmp_path if built else None)) as c:
        response = c.get(path, follow_redirects=False)
    assert response.status_code == 404 and error_of(response.text) is WebErrorCode.NOT_FOUND
    assert "location" not in response.headers and response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" in response.headers


def test_the_contract_route_reports_version_1(client: TestClient) -> None:
    """S5.1 host side: the version, every event type and every command."""
    response = client.get("/v1/contract")
    assert response.json() == {"v": 1, "events": list(COMPONENTS), "commands": list(COMMANDS)}


@pytest.mark.parametrize(("up", "status"), [(True, 200), (False, 503)])
def test_health_answers_from_the_database_probe(up: bool, status: int) -> None:
    """D25: 200 with an empty envelope, or 503 `rules_unavailable` (fail closed)."""
    with client_for(probe_api(ready=lambda: up)) as c:
        response = c.get("/health")
    envelope = ResponseEnvelope.model_validate_json(response.text)
    assert response.status_code == status and envelope.events == ()
    assert (envelope.error is None) is up
    assert up or (envelope.error is not None and envelope.error.code is ErrorCode.RULES_UNAVAILABLE)


def test_a_probe_that_raises_is_unavailable(caplog: pytest.LogCaptureFixture) -> None:
    def broken() -> bool:
        raise OSError(SECRET)

    with client_for(probe_api(ready=broken)) as c:
        response = c.get("/health")
    assert response.status_code == 503 and error_of(response.text) is ErrorCode.RULES_UNAVAILABLE
    assert SECRET not in response.text and SECRET not in caplog.text


def test_the_built_page_is_served_from_the_same_origin(tmp_path: Path) -> None:
    """W1, S10.1: index.html at `/`, with the CSP; unknown files still get the envelope."""
    (tmp_path / "index.html").write_text("<!doctype html><title>Dale</title>", encoding="utf-8")
    with client_for(probe_api(page=tmp_path)) as c:
        page, missing = c.get("/"), c.get("/nope.js")
        api = c.get("/v1/contract")
    assert page.status_code == 200 and "<title>Dale</title>" in page.text
    assert "script-src 'self'" in page.headers["content-security-policy"]
    assert missing.status_code == 404 and error_of(missing.text) is WebErrorCode.NOT_FOUND
    assert api.json()["v"] == 1  # the routes win over the mount


def test_the_routes_win_over_the_page_mount(tmp_path: Path) -> None:
    """The mount matches every path, so `build_api` registers it after every route."""
    (tmp_path / "index.html").write_text("<!doctype html>", encoding="utf-8")
    with client_for(build_api(lambda: True, tmp_path, InMemoryRegistry(FakeBackend))) as c:
        health, contract, unknown = c.get("/health"), c.get("/v1/contract"), c.get("/v1/x")
    assert health.status_code == 200 and ResponseEnvelope.model_validate_json(health.text)
    assert contract.json()["v"] == 1
    assert unknown.status_code == 404 and error_of(unknown.text) is WebErrorCode.NOT_FOUND


def test_a_missing_page_directory_is_not_mounted(tmp_path: Path) -> None:
    """The page is built in a later slice: the host starts without it."""
    api = probe_api(page=tmp_path / "dist")
    assert not any(getattr(r, "name", None) == "page" for r in api.routes)


def test_no_cors_middleware_and_no_cors_header(client: TestClient) -> None:
    """S1.2: same origin only, so nothing answers a preflight or names an allowed origin."""
    preflight = {"origin": "https://evil.example", "access-control-request-method": "POST"}
    responses = [
        client.options("/v1/probe", headers=preflight),
        client.get("/v1/contract", headers={"origin": "https://evil.example"}),
        client.post("/v1/probe", headers=JSON, content=b'{"text": "hola"}'),
    ]
    assert probe_api().user_middleware == []
    assert not [h for r in responses for h in r.headers if h.startswith("access-control-")]

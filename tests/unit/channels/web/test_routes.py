"""The conversation routes over HTTP with a fake backend (W2, W3, W4, W6, W14, D14): every
answer is one envelope, commands are validated before anything runs, and typed text reaches only
the turn."""

from typing import Any
from uuid import UUID

import httpx2 as httpx
import pytest
from starlette.testclient import TestClient

from dale.brain.application.take_turn import TurnResult
from dale.channels.web.app import create_app
from dale.channels.web.contract import ResponseEnvelope, ToolCalled
from dale.channels.web.conversations import (
    BackendUnavailableError,
    ConversationRegistry,
    InMemoryRegistry,
    WebBackend,
)
from dale.channels.web.guard import AllowList
from dale.shared.customer_input import CustomerText
from dale.shared.errors import HTTP_STATUS, ErrorCode
from dale.shared.shown_events import (
    AssistantText,
    HandoffNotice,
    OrderConfirmed,
    OrderRejected,
    ProposalSummary,
    SystemNotice,
)
from tests.unit.channels.web.test_conversations import (
    DONE,
    HELLO,
    PID,
    SUMMARY,
    TRACE,
    FakeBackend,
    said,
)

PORT = 8000
POST = {"origin": f"http://127.0.0.1:{PORT}"}
SHOWN = (AssistantText, ProposalSummary, OrderConfirmed, OrderRejected, HandoffNotice, SystemNotice)


def serve(registry: ConversationRegistry) -> TestClient:
    app = create_app(AllowList.loopback(PORT), lambda: True, None, registry)
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", raise_server_exceptions=False)


def host(*backends: FakeBackend) -> TestClient:
    """One backend per conversation created, in order."""
    return serve(InMemoryRegistry(iter(backends).__next__))


def post(client: TestClient, path: str, body: Any) -> httpx.Response:
    return client.post(path, headers=POST, json=body)


def opened(client: TestClient) -> str:
    response = post(client, "/v1/conversations", {})
    assert response.status_code == 201
    return str(response.json()["conversation_id"])


def send(client: TestClient, conversation: str, body: Any) -> httpx.Response:
    return post(client, f"/v1/conversations/{conversation}/messages", body)


def envelope(response: httpx.Response) -> ResponseEnvelope:
    return ResponseEnvelope.model_validate_json(response.text)


def kinds(response: httpx.Response) -> list[str]:
    return [e.type for e in envelope(response).events]


def code(response: httpx.Response) -> str | None:
    error = envelope(response).error
    return None if error is None else error.code


def test_a_new_conversation_is_201_with_no_events() -> None:
    client = host(FakeBackend(), FakeBackend())
    first, second = post(client, "/v1/conversations", {}), post(client, "/v1/conversations", {})
    new = envelope(first)
    assert (first.status_code, new.seq, new.events, new.pending_proposal_id, new.error) == (
        201,
        0,
        (),
        None,
        None,
    )
    assert new.conversation_id != envelope(second).conversation_id


def test_no_conversation_is_created_while_its_backend_cannot_be_built() -> None:
    def down() -> WebBackend:
        raise BackendUnavailableError(ErrorCode.RULES_UNAVAILABLE)

    response = post(serve(InMemoryRegistry(down)), "/v1/conversations", {})
    assert (response.status_code, code(response)) == (503, "rules_unavailable")
    assert envelope(response).conversation_id is None


def test_a_turn_sends_its_tool_calls_then_its_shown_events_in_seq() -> None:
    """S3.2, S3.4: one `ToolCalled` per call, naming the tool, then the shown events."""
    backend = FakeBackend([said([HELLO, SUMMARY], TRACE), said([HELLO])])
    client = host(backend)
    talk = opened(client)
    first, second = send(client, talk, {"text": "quiero yerba"}), send(client, talk, {"text": "y"})
    assert kinds(first) == ["ToolCalled", "AssistantText", "ProposalSummary"]
    assert [e.seq for e in envelope(first).events] == [1, 2, 3]
    assert [e.seq for e in envelope(second).events] == [4] and envelope(second).seq == 4
    [tool] = [e.data for e in envelope(first).events if isinstance(e.data, ToolCalled)]
    assert (tool.name, tool.summary, tool.ok, tool.code) == (
        "check_prices",
        '{"product":"yerba"}',
        True,
        None,
    )
    assert (first.status_code, envelope(first).pending_proposal_id) == (200, PID)


def test_a_confirming_turn_is_verified_on_shown_events_only() -> None:
    """S3.3, W13: the verifier never gets a `ToolCalled` or a `VerdictIssued`."""
    backend = FakeBackend([said([HELLO, SUMMARY], TRACE), said([DONE], TRACE)])
    client = host(backend)
    talk = opened(client)
    send(client, talk, {"text": "quiero yerba"})
    response = send(client, talk, {"text": "listo"})
    assert kinds(response) == ["ToolCalled", "OrderConfirmed", "VerdictIssued"]
    [(judged, subject)] = backend.verified
    assert judged == (HELLO, SUMMARY, DONE) and subject == PID
    assert all(isinstance(event, SHOWN) for event in judged)


@pytest.mark.parametrize(
    ("turn", "status", "expected"),
    [
        (said([HELLO]), 200, None),
        (
            TurnResult((HELLO,), ErrorCode.MODEL_UNAVAILABLE, ()),
            HTTP_STATUS[ErrorCode.MODEL_UNAVAILABLE],
            "model_unavailable",
        ),
        (RuntimeError("boom"), 500, "turn_failed"),
    ],
    ids=["answered", "failed", "raised"],
)
def test_a_turn_takes_its_status_from_its_failure_code(
    turn: TurnResult | Exception, status: int, expected: str | None
) -> None:
    client = host(FakeBackend([turn]))
    response = send(client, opened(client), {"text": "hola"})
    assert (response.status_code, code(response)) == (status, expected)


@pytest.mark.parametrize("text", ["dale", "dale, confirmalo", "DALE ✅"])
def test_typed_dale_is_only_customer_text(text: str) -> None:
    """S6.2: the message reaches the turn as text; nothing is pressed."""
    backend = FakeBackend([said([SUMMARY]), said([AssistantText("Apretá el botón Dale.")])])
    client = host(backend)
    talk = opened(client)
    send(client, talk, {"text": "quiero yerba"})
    response = send(client, talk, {"text": text})
    assert backend.said[-1] == CustomerText(text) and backend.pressed == []
    assert kinds(response) == ["AssistantText"] and envelope(response).pending_proposal_id == PID


@pytest.mark.parametrize(
    "body",
    [{}, {"text": 5}, {"text": " "}, {"text": "hola", "customer_id": "C-002"}, ["hola"]],
    ids=["missing", "wrong-type", "blank", "customer-id", "not-an-object"],
)
def test_an_invalid_message_runs_no_turn(body: Any) -> None:
    backend = FakeBackend()
    client = host(backend)
    response = send(client, opened(client), body)
    assert (response.status_code, code(response), backend.said) == (422, "invalid_request", [])


@pytest.mark.parametrize(
    ("conversation", "status", "expected"),
    [(str(UUID(int=5)), 404, "conversation_not_found"), ("x", 422, "invalid_request")],
)
def test_an_unknown_conversation_is_rejected_with_the_envelope(
    conversation: str, status: int, expected: str
) -> None:
    response = send(host(), conversation, {"text": "hola"})
    assert (response.status_code, code(response)) == (status, expected)
    assert envelope(response).events == ()

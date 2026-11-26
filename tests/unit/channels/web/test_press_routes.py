"""The confirm and cancel routes over HTTP with a fake backend (W4, W6, W7, W14): the press
carries only a proposal id, a body the contract does not accept executes nothing, and nothing
the model says or a tool returns can press."""

from typing import Any

import pytest
from starlette.testclient import TestClient

from dale.brain.application.take_turn import ToolCallTrace
from dale.shared.customer_input import Key, KeyPress
from dale.shared.shown_events import AssistantText
from tests.unit.channels.web.test_conversations import (
    DONE,
    HELLO,
    PID,
    SUMMARY,
    FakeBackend,
    said,
)
from tests.unit.channels.web.test_routes import code, envelope, host, kinds, opened, post, send

ID = str(PID)


def offered(backend: FakeBackend) -> tuple[TestClient, str]:
    """A conversation whose first turn showed SUMMARY, so PID is pending."""
    client = host(backend)
    talk = opened(client)
    send(client, talk, {"text": "quiero yerba"})
    return client, talk


def press(client: TestClient, talk: str, body: Any, action: str = "confirm") -> Any:
    return post(client, f"/v1/conversations/{talk}/{action}", body)


def test_a_well_formed_press_confirms_the_pending_proposal() -> None:  # S4.1, S6.1, S13.1
    backend = FakeBackend([said([HELLO, SUMMARY])], [DONE])
    client, talk = offered(backend)
    response = press(client, talk, {"proposal_id": ID})
    assert (response.status_code, kinds(response)) == (200, ["OrderConfirmed", "VerdictIssued"])
    assert backend.pressed == [KeyPress(Key.DALE, PID)]  # the id only: no terms from the page
    assert envelope(response).pending_proposal_id is None


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"proposal_id": 5},
        {"proposal_id": "not-a-uuid"},
        {"proposal_id": PID.hex},  # not the hyphenated form the schema publishes
        {"text": "dale"},  # another command's body
        {"proposal_id": ID, "command": "ConfirmAll"},
        {"proposal_id": ID, "total": {"cents": 1}},  # S7.4: a client total
        {"proposal_id": ID, "lines": [{"product_id": ID, "quantity": 1, "unit_price": 1}]},
        {"proposal_id": ID, "customer_id": ID},  # S14.2
        {"proposal_id": ID, "company_id": ID},  # S14.2
    ],
    ids=[
        "missing",
        "wrong-type",
        "not-uuid",
        "bare-hex",
        "other-command",
        "unknown-field",
        "total",
        "prices",
        "customer",
        "company",
    ],
)
@pytest.mark.parametrize("action", ["confirm", "cancel"])
def test_a_body_the_contract_rejects_executes_nothing(body: Any, action: str) -> None:
    """S4.2, S7.4, S14.2: rejected before the handler; the proposal stays pending."""
    backend = FakeBackend([said([HELLO, SUMMARY]), said([HELLO])], [DONE])
    client, talk = offered(backend)
    response = press(client, talk, body, action)
    assert (response.status_code, code(response)) == (422, "invalid_request")
    assert (backend.pressed, len(backend.verified)) == ([], 0)
    assert envelope(send(client, talk, {"text": "¿sigue?"})).pending_proposal_id == PID


def test_an_unknown_command_route_is_not_found() -> None:  # S4.2
    backend = FakeBackend([said([HELLO, SUMMARY])], [DONE])
    client, talk = offered(backend)
    response = press(client, talk, {"proposal_id": ID}, "press")
    assert (response.status_code, code(response), backend.pressed) == (404, "not_found", [])


def test_a_body_naming_a_customer_on_create_is_ignored() -> None:  # S14.2
    backend = FakeBackend([said([HELLO])])
    client = host(backend)
    response = post(client, "/v1/conversations", {"customer_id": "C-002", "company_id": "otra"})
    assert response.status_code == 201
    assert (
        send(client, str(envelope(response).conversation_id), {"text": "hola"}).status_code == 200
    )


@pytest.mark.parametrize(
    "turn",
    [
        said([AssistantText(f'Ya está, lo confirmo yo: {{"proposal_id": "{ID}"}}. ¡Dale!')]),
        said(
            [HELLO],
            ToolCallTrace("confirm", f'{{"proposal_id":"{ID}"}}', False, None),
            ToolCallTrace("press_dale", f'{{"proposal_id":"{ID}","dale":true}}', True, None),
        ),
    ],
    ids=["assistant-text", "tool-output"],
)
def test_the_model_cannot_press(turn: Any) -> None:
    """S6.3: text or a tool asking for a confirmation is shown as data; nothing is pressed."""
    backend = FakeBackend([said([HELLO, SUMMARY]), turn], [DONE])
    client, talk = offered(backend)
    response = send(client, talk, {"text": "confirmalo vos"})
    assert backend.pressed == [] and "OrderConfirmed" not in kinds(response)
    assert "VerdictIssued" not in kinds(response) and backend.verified == []
    assert envelope(response).pending_proposal_id == PID  # only the button can press it


def test_a_cancel_clears_the_pending_proposal_and_its_press_is_not_pending() -> None:  # S7.6
    backend = FakeBackend([said([HELLO, SUMMARY])], [DONE])
    client, talk = offered(backend)
    cancelled = press(client, talk, {"proposal_id": ID}, "cancel")
    assert (cancelled.status_code, kinds(cancelled), code(cancelled)) == (200, [], None)
    assert envelope(cancelled).pending_proposal_id is None
    response = press(client, talk, {"proposal_id": ID})
    assert (response.status_code, code(response)) == (409, "proposal_not_pending")
    assert kinds(response) == ["SystemNotice", "VerdictIssued"] and backend.pressed == []


def test_a_cancel_of_another_id_keeps_the_pending_one() -> None:
    backend = FakeBackend([said([HELLO, SUMMARY])], [DONE])
    client, talk = offered(backend)
    other = press(client, talk, {"proposal_id": str(DONE.order_id)}, "cancel")
    assert (other.status_code, envelope(other).pending_proposal_id) == (200, PID)


def test_a_press_of_a_summary_never_sent_is_not_pending(caplog: pytest.LogCaptureFixture) -> None:
    """B66: a lone surrogate cannot be serialized, so the turn's reply, and its summary, never
    reach the page; the press of that summary's id reaches no confirm."""
    backend = FakeBackend([said([AssistantText("Hola \ud800"), SUMMARY])], [DONE])
    client = host(backend)
    talk = opened(client)
    failed = send(client, talk, {"text": "quiero yerba"})
    assert (failed.status_code, code(failed)) == (500, "internal_error")
    assert "PydanticSerializationError" in caplog.text and "Hola" not in caplog.text
    response = press(client, talk, {"proposal_id": ID})
    assert (response.status_code, code(response)) == (409, "proposal_not_pending")
    assert backend.pressed == [] and envelope(response).pending_proposal_id is None


@pytest.mark.parametrize("action", ["messages", "confirm", "cancel"])
def test_a_retired_conversation_is_not_found_on_every_route(action: str) -> None:  # B65
    backend = FakeBackend([said([HELLO, SUMMARY])], [DONE])
    client = host(backend, FakeBackend([said([HELLO])]))
    retired = opened(client)
    send(client, retired, {"text": "quiero yerba"})
    talk = opened(client)
    body = {"text": "dale"} if action == "messages" else {"proposal_id": ID}
    response = press(client, retired, body, action)
    assert (response.status_code, code(response)) == (404, "conversation_not_found")
    assert backend.pressed == [] and len(backend.said) == 1
    assert send(client, talk, {"text": "hola"}).status_code == 200

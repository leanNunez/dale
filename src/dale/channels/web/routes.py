"""The conversation routes of the web host (W2, W4, W6, W14, D14; design §3, §4.2).

Each answers with one `ResponseEnvelope` and its status: 200 (201 for a new conversation), or the
status of the error code it carries. A command is validated by its contract model before the
handler runs, so a body with a missing, wrong or unknown field (a client total, a customer or
company id) executes nothing. The customer is the one the host was started for: no route takes
it from the page. `SendMessage` becomes only `CustomerText`, so typed text, "dale" included,
reaches the model and never a confirm (S6.2); only `/confirm` presses.
"""

import logging
from collections.abc import Callable, Mapping
from uuid import UUID

from fastapi import FastAPI, Response
from pydantic_core import PydanticSerializationError

from dale.channels.web.contract import CancelProposal, PressDale, ResponseEnvelope, SendMessage
from dale.channels.web.conversations import (
    BackendUnavailableError,
    ConversationRegistry,
    Reply,
    WebConversation,
)
from dale.channels.web.errors import WebErrorCode, status_for
from dale.channels.web.guard import error_envelope
from dale.shared.customer_input import CustomerText
from dale.shared.errors import ErrorCode

CONVERSATION = "/v1/conversations/{conversation_id}"
log = logging.getLogger(__name__)


def envelope_response(
    envelope: ResponseEnvelope, status: int, headers: Mapping[str, str] | None = None
) -> Response:
    body = envelope.model_dump_json()
    return Response(body, status_code=status, media_type="application/json", headers=headers)


def error_response(
    code: WebErrorCode | ErrorCode, headers: Mapping[str, str] | None = None
) -> Response:
    return envelope_response(error_envelope(code), status_for(code), headers)


def add_routes(api: FastAPI, registry: ConversationRegistry) -> None:
    """Sync handlers: FastAPI runs them on its threadpool, since the brain, the database and the
    verifier all block (D12)."""

    @api.post("/v1/conversations")
    def create() -> Response:
        """A new conversation for the fixed customer; any body is ignored (S14.2)."""
        try:
            talk = registry.create()
        except BackendUnavailableError as error:
            return error_response(error.code)
        new = ResponseEnvelope(
            conversation_id=talk.id, seq=0, events=(), pending_proposal_id=None, error=None
        )
        return envelope_response(new, 201)

    @api.post(f"{CONVERSATION}/messages")
    def message(conversation_id: UUID, command: SendMessage) -> Response:
        said = CustomerText(command.text)
        return _answer(registry, conversation_id, lambda talk: talk.turn(said))

    @api.post(f"{CONVERSATION}/confirm")
    def confirm(conversation_id: UUID, command: PressDale) -> Response:
        """The Dale button, and the only route that can reach `ConfirmProposal` (S2.1): the press
        carries only the id, the gate confirms only the pending one, and the order is built from
        the stored proposal (S7.4)."""
        return _answer(registry, conversation_id, lambda talk: talk.press(command.proposal_id))

    @api.post(f"{CONVERSATION}/cancel")
    def cancel(conversation_id: UUID, command: CancelProposal) -> Response:
        """Clears the pending proposal only; the database is not touched (S7.6)."""
        return _answer(registry, conversation_id, lambda talk: talk.cancel(command.proposal_id))


def _answer(
    registry: ConversationRegistry, conversation_id: UUID, run: Callable[[WebConversation], Reply]
) -> Response:
    """An id this host does not hold, one from before a restart included, is not found (S17.2).
    The reply is serialized before it is sent: one that cannot be withdraws its pending proposal,
    which the customer never saw, and answers `internal_error` (B66)."""
    talk = registry.get(conversation_id)
    if talk is None:
        return error_response(WebErrorCode.CONVERSATION_NOT_FOUND)
    reply = run(talk)
    try:
        body = reply.envelope.model_dump_json()
    except PydanticSerializationError as error:  # its text is the customer's: never logged
        talk.withdraw(reply.envelope.pending_proposal_id)
        log.error("reply of conversation %s not sent: %s", talk.id, type(error).__name__)
        return error_response(WebErrorCode.INTERNAL_ERROR)
    return Response(body, status_code=reply.status, media_type="application/json")

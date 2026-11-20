"""Conversation state of the web channel (D16, W3, W12; design §4.3).

A `WebConversation` holds one brain conversation (its backend), the transcript the verifier
judges, the `Pending` proposal and the seq counter. Every request runs under the conversation
lock, taken without waiting: a second one while one runs gets 409 `conversation_busy`, so
`TakeTurn`, which is not thread-safe, never runs twice at once. The lock is released in
`finally`, so a failed request frees it (S12.2).
"""

import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Final, Protocol
from uuid import UUID

from dale.brain.application.take_turn import TurnResult
from dale.channels.common.backend import step
from dale.channels.common.pending import Pending
from dale.channels.web.contract import (
    AssistantTextEvent,
    ErrorBody,
    HandoffNoticeEvent,
    OrderConfirmedEvent,
    OrderRejectedEvent,
    ProposalSummaryEvent,
    ResponseEnvelope,
    SystemNoticeEvent,
    ToolCalled,
    ToolCalledEvent,
    VerdictIssued,
    VerdictIssuedEvent,
    WebEvent,
)
from dale.channels.web.errors import WebErrorCode, message_for, status_for
from dale.shared.customer_input import CustomerText, KeyPress
from dale.shared.errors import ErrorCode
from dale.shared.shown_events import (
    AssistantText,
    HandoffNotice,
    OrderConfirmed,
    OrderRejected,
    ProposalSummary,
    ShownEvent,
    SystemNotice,
)

type Code = WebErrorCode | ErrorCode
type Payload = ShownEvent | ToolCalled | VerdictIssued
WRAPPERS: Final[dict[type, Callable[..., WebEvent]]] = {
    AssistantText: AssistantTextEvent,
    ProposalSummary: ProposalSummaryEvent,
    OrderConfirmed: OrderConfirmedEvent,
    OrderRejected: OrderRejectedEvent,
    HandoffNotice: HandoffNoticeEvent,
    SystemNotice: SystemNoticeEvent,
    ToolCalled: ToolCalledEvent,
    VerdictIssued: VerdictIssuedEvent,
}


class WebBackend(Protocol):
    """What `apps.web` wires around the shared backend: the turn's whole result (its trace too)
    and the verdict already mapped to the channel's type (contract 11 keeps `dale.apps` out)."""

    def take_turn(self, said: CustomerText) -> TurnResult: ...

    def confirm(self, press: KeyPress) -> ShownEvent: ...

    def verify(self, shown: Sequence[ShownEvent], subject: UUID | None) -> VerdictIssued: ...


@dataclass(frozen=True)
class Reply:
    """One response: the envelope and its status (200, or the error code's status)."""

    envelope: ResponseEnvelope
    status: int


class WebConversation:
    def __init__(self, conversation_id: UUID, backend: WebBackend) -> None:
        self.id, self._backend = conversation_id, backend
        self.transcript: list[ShownEvent] = []  # only shown events: what the verifier judges
        self.pending = Pending()
        self._seq = 0  # the last event's seq; events count from 1 (W3)
        self._published: tuple[int, UUID | None] = (0, None)  # seq and pending, last request
        self._lock = threading.Lock()

    def turn(self, said: CustomerText) -> Reply:
        """Tool calls in call order, then the shown events. A raised turn shows nothing and
        keeps `Pending`: what it may have shown is unknown."""
        with self._exclusive() as free:
            if not free:
                return self._busy()
            result = step("turn", lambda: self._backend.take_turn(said))
            if result is None:
                return self._finish([], WebErrorCode.TURN_FAILED)
            events = [
                self._event(ToolCalled(name=t.name, summary=t.summary, ok=t.ok, code=t.code))
                for t in result.trace
            ]
            events += self._show(result.shown)
            self.pending.after_turn(result.shown)
            return self._finish(events, result.failure)

    @contextmanager
    def _exclusive(self) -> Iterator[bool]:
        """The conversation lock, never waited for (W12)."""
        free = self._lock.acquire(blocking=False)
        try:
            yield free
        finally:
            if free:
                self._lock.release()

    def _show(self, shown: Sequence[ShownEvent]) -> list[WebEvent]:
        self.transcript.extend(shown)
        return [self._event(event) for event in shown]

    def _event(self, data: Payload) -> WebEvent:
        self._seq += 1
        return WRAPPERS[type(data)](seq=self._seq, conversation_id=self.id, data=data)

    def _finish(self, events: Sequence[WebEvent], code: Code | None) -> Reply:
        """Built under the lock; what a busy reply reports is published only here."""
        reply = _reply(self.id, self._seq, events, self.pending.proposal_id, code)
        self._published = (self._seq, self.pending.proposal_id)
        return reply

    def _busy(self) -> Reply:
        seq, pending = self._published  # one consistent pair, never a request half done
        return _reply(self.id, seq, (), pending, WebErrorCode.CONVERSATION_BUSY)


def _reply(
    conversation: UUID,
    seq: int,
    events: Sequence[WebEvent],
    pending: UUID | None,
    code: Code | None,
) -> Reply:
    error = None if code is None else ErrorBody(code=code, message=message_for(code))
    envelope = ResponseEnvelope(
        conversation_id=conversation,
        seq=seq,
        events=tuple(events),
        pending_proposal_id=pending,
        error=error,
    )
    return Reply(envelope, 200 if code is None else status_for(code))

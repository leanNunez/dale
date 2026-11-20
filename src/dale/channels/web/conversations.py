"""Conversation state of the web channel and the press (D15, D16, W3, W7, W12, W13, W17;
design §4.3).

A `WebConversation` holds one brain conversation (its backend), the transcript the verifier
judges, the `Pending` proposal, the ids shown in summaries and confirmations and the seq
counter. Every request, a press included, runs under the conversation lock, taken without
waiting: a second one while one runs gets 409 `conversation_busy`, so `TakeTurn`, which is not
thread-safe, never runs twice at once. The lock is released in `finally`, so a failed request
frees it (S12.2).
"""

import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Final, Protocol
from uuid import UUID, uuid4

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
from dale.shared.customer_input import CustomerText, Key, KeyPress
from dale.shared.errors import ErrorCode
from dale.shared.ids import ProposalId
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


def failed_verdict(subject: UUID | None) -> VerdictIssued:
    """The verdict when the verifier call itself fails (the channel's `VerifierFailed`): never
    verified. Its reason `verifier_failed` is outside the closed set, so it is the catch-all
    `verifier_error` (B37)."""
    return VerdictIssued(
        subject_proposal_id=subject,
        verdict="unverifiable",
        reason="verifier_error",
        false_confirmations=0,
        unexpected_writes=0,
        findings=(),
        stored_orders=(),
    )


class WebConversation:
    def __init__(self, conversation_id: UUID, backend: WebBackend) -> None:
        self.id, self._backend = conversation_id, backend
        self.transcript: list[ShownEvent] = []  # only shown events: what the verifier judges
        self.pending = Pending()
        self._summaries: set[UUID] = set()  # ids shown in a ProposalSummary
        self._confirmed: set[UUID] = set()  # ids shown in an OrderConfirmed
        self._seq = 0  # the last event's seq; events count from 1 (W3)
        self._published: tuple[int, UUID | None] = (0, None)  # seq and pending, last request
        self._lock = threading.Lock()

    def turn(self, said: CustomerText) -> Reply:
        """Tool calls in call order, then the shown events, then the verdict when an
        `OrderConfirmed` was shown (W13). A raised turn shows nothing and keeps `Pending`."""
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
            if done := [e.proposal_id for e in result.shown if isinstance(e, OrderConfirmed)]:
                events.append(self._verify(done[-1]))
            return self._finish(events, result.failure)

    def press(self, proposal_id: UUID) -> Reply:
        """The press, under the conversation lock like a turn (W12)."""
        with self._exclusive() as free:
            return self._press(proposal_id) if free else self._busy()

    def _press(self, proposal_id: UUID) -> Reply:
        """Steps 3 to 5. Only the pending id reaches the brain: any other id, one shown confirmed
        included, gets a notice (B50). The gate's notices are the channel's, like the terminal's:
        they do not enter the transcript and leave `Pending` alone (S6.4, S7.2, S7.3)."""
        if proposal_id != self.pending.proposal_id:
            code = ErrorCode.PROPOSAL_NOT_FOUND
            if proposal_id in self._summaries or proposal_id in self._confirmed:
                code = ErrorCode.PROPOSAL_NOT_PENDING
            notice = self._event(SystemNotice(code, message_for(code)))
            return self._finish([notice, self._verify(None)], code)
        press = KeyPress(Key.DALE, ProposalId(proposal_id))
        outcome = step("confirm", lambda: self._backend.confirm(press))
        if outcome is None:  # 4: unknown, so nothing shown and the pending id kept (B53)
            return self._finish([self._verify(proposal_id)], WebErrorCode.CONFIRM_OUTCOME_UNKNOWN)
        events = self._show([outcome])
        self.pending.after_press(press, outcome)
        events.append(self._verify(proposal_id))  # 5
        failed = outcome.code if isinstance(outcome, OrderRejected | SystemNotice) else None
        return self._finish(events, failed)

    @contextmanager
    def _exclusive(self) -> Iterator[bool]:
        """The conversation lock, never waited for (W12)."""
        free = self._lock.acquire(blocking=False)
        try:
            yield free
        finally:
            if free:
                self._lock.release()

    def _verify(self, subject: UUID | None) -> WebEvent:
        """Its verdict is always returned; a raised or failed call is `unverifiable` (S13.3)."""
        verdict = step("verify", lambda: self._backend.verify(tuple(self.transcript), subject))
        return self._event(verdict or failed_verdict(subject))

    def _show(self, shown: Sequence[ShownEvent]) -> list[WebEvent]:
        self.transcript.extend(shown)
        for event in shown:
            if isinstance(event, ProposalSummary):
                self._summaries.add(event.proposal_id)
            elif isinstance(event, OrderConfirmed):
                self._confirmed.add(event.proposal_id)
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


class ConversationRegistry(Protocol):
    """Where conversations live (W17): in memory in v0.2; v0.3 puts a persistent store, the
    cookie and the limits behind this port.

    It returns the live in-process `WebConversation`, which owns the locks and the backend. A
    persistent store must therefore keep exactly one live object per conversation id in the
    process (for example an in-memory map over a write-through store) and persist the pending
    id, the seq, the transcript and the settled replies whenever they change. Restoring a
    conversation after a restart is v0.3 work (B54)."""

    def create(self) -> WebConversation: ...

    def get(self, conversation_id: UUID) -> WebConversation | None: ...


class InMemoryRegistry:
    """Lost on restart (W17). It has no cap yet: that cap is Known pending."""

    def __init__(self, backend: Callable[[], WebBackend], ids: Callable[[], UUID] = uuid4) -> None:
        self._backend, self._ids = backend, ids
        self._conversations: dict[UUID, WebConversation] = {}
        self._mutex = threading.Lock()  # guards the table only; never held while building

    def create(self) -> WebConversation:
        conversation = WebConversation(self._ids(), self._backend())
        with self._mutex:
            self._conversations[conversation.id] = conversation
        return conversation

    def get(self, conversation_id: UUID) -> WebConversation | None:
        with self._mutex:
            return self._conversations.get(conversation_id)

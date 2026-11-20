"""Conversation state of the web channel and the press (D15, D16, W3, W7, W12, W13, W17;
design §4.3).

A `WebConversation` holds one brain conversation (its backend), the transcript the verifier
judges, the `Pending` proposal, the ids shown in summaries and confirmations, the seq counter
and the settled press responses. Every request runs under the conversation lock, taken without
waiting: a second one while one runs gets 409 `conversation_busy`, so `TakeTurn`, which is not
thread-safe, never runs twice at once. The lock is released in `finally`, so a failed request
frees it (S12.2).

Lock order, fixed: a press takes (1) the press lock of its proposal id, waiting at most
`PRESS_WAIT` seconds, then (2) the conversation lock without waiting. A turn and a cancel
take only (2). No path holds (2) while it takes (1), and no request waits for (2), so no
request can wait on another in a cycle; `withdraw` waits for (2) holding nothing else (B66).
`PressLocks` holds its own mutex only around its table.
"""

import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
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

PRESS_WAIT: Final = 60.0  # seconds a press waits for a running press of the same proposal (D16)
WAITERS: Final = 1  # presses that may wait for a running press of the same proposal
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


class BackendUnavailableError(Exception):
    """A new conversation's backend could not be built; `code` is the catalog reason."""

    def __init__(self, code: ErrorCode) -> None:
        super().__init__(code.value)
        self.code = code


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


@dataclass(slots=True)
class _PressLock:
    lock: threading.Lock = field(default_factory=threading.Lock)
    users: int = 0  # the press holding it and the presses waiting for it
    shared: Reply | None = None  # the holder's reply, left for the press waiting on it

    def take(self) -> Reply | None:
        """The reply of the press this one waited on, once: it is never cached (B51)."""
        shared, self.shared = self.shared, None
        return shared


class PressLocks:
    """One lock per proposal id being pressed. An entry lives only while a press holds or waits
    for it, so made-up ids leave nothing behind.

    At most `WAITERS` presses wait per id; one more answers busy at once instead of parking.
    Each request runs on a thread of anyio's threadpool, which every request of the host shares
    (40 tokens by default), so a parked press holds a token: this bound keeps repeated clicks on
    one page from parking more than one thread per running press and starving the others."""

    def __init__(self, wait: float = PRESS_WAIT) -> None:
        self._wait, self._table, self._mutex = wait, dict[UUID, _PressLock](), threading.Lock()

    @contextmanager
    def held(self, proposal_id: UUID) -> Iterator[_PressLock | None]:
        """The id's entry once its lock is held; None when a press already waits for it or the
        bounded wait ran out."""
        with self._mutex:
            entry = self._table.setdefault(proposal_id, _PressLock())
            crowded = entry.users > WAITERS  # the holder and its waiters are all there
            if not crowded:
                entry.users += 1
        if crowded:
            yield None
            return
        acquired = False
        try:
            acquired = self._acquire(entry.lock)
            yield entry if acquired else None
        finally:
            if acquired:
                entry.lock.release()
            with self._mutex:
                entry.users -= 1
                if not entry.users:
                    del self._table[proposal_id]

    def _acquire(self, lock: threading.Lock) -> bool:
        return lock.acquire(timeout=self._wait)

    def share(self, entry: _PressLock, reply: Reply) -> None:
        """Called by the holder: leaves its reply to the press waiting on it, if one is."""
        with self._mutex:
            if entry.users > 1:
                entry.shared = reply

    def __len__(self) -> int:
        return len(self._table)


class WebConversation:
    def __init__(
        self, conversation_id: UUID, backend: WebBackend, presses: PressLocks | None = None
    ) -> None:
        self.id, self._backend = conversation_id, backend
        self.transcript: list[ShownEvent] = []  # only shown events: what the verifier judges
        self.pending = Pending()
        self._summaries: set[UUID] = set()  # ids shown in a ProposalSummary
        self._confirmed: set[UUID] = set()  # ids shown in an OrderConfirmed
        self._settled: dict[UUID, Reply] = {}  # settled press replies, replayed (S7.1)
        self._presses = PressLocks() if presses is None else presses  # empty is falsy
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
        """Steps 1 and 2 of the press, in the fixed lock order (module docstring). A press that
        waited on a running press of the same id gets that press's reply, whatever its outcome;
        a later press of a settled id gets the settled reply. Both are replays (`_replay`)."""
        with self._presses.held(proposal_id) as entry:
            if entry is None:  # 1: a press already waits for this id, or the wait ran out
                return self._busy()
            if (reply := entry.take() or self._settled.get(proposal_id)) is not None:
                return self._replay(reply)  # 1: no brain call, so one order (S7.1)
            with self._exclusive() as free:  # 2
                if not free:
                    return self._busy()
                reply = self._press(proposal_id)
            self._presses.share(entry, reply)
            return reply

    def _press(self, proposal_id: UUID) -> Reply:
        """Steps 3 to 6. Only the pending id reaches the brain: any other id, one shown confirmed
        included, gets a notice (B50); a settled id was replayed before this. The gate's notices
        are the channel's, like the terminal's: they do not enter the transcript and leave
        `Pending` alone (S6.4, S7.2, S7.3, S7.6)."""
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
        reply = self._finish(events, failed)
        if isinstance(outcome, OrderConfirmed | OrderRejected):  # 6: settled for good
            self._settled[proposal_id] = reply
        return reply

    def cancel(self, proposal_id: UUID) -> Reply:
        """Clears `Pending` when it holds this id, like the terminal's F3. The proposal stays
        prepared in the database; the gate now answers `proposal_not_pending` (S7.6)."""
        with self._exclusive() as free:
            if not free:
                return self._busy()
            if proposal_id == self.pending.proposal_id:
                self.pending.after_press(KeyPress(Key.CANCEL), None)
            return self._finish([], None)

    def withdraw(self, proposal_id: UUID | None) -> None:
        """Clears `Pending` when it still holds this id: the reply that showed it never reached
        the page, so no press may reach a summary the customer was not sent (B66)."""
        with self._lock:
            if proposal_id is not None and proposal_id == self.pending.proposal_id:
                self.pending.after_press(KeyPress(Key.CANCEL), None)
                self._published = (self._published[0], None)

    def _replay(self, reply: Reply) -> Reply:
        """The reply's events byte for byte, each with its own seq, and its status. Its verdict
        is the one judged for that press: a replay runs no verifier. The envelope's `seq` and
        `pending_proposal_id` are the last finished request's (B24), so a late replay never
        hides a newer pending proposal, and replays while nothing else ran are identical (B52)."""
        seq, pending = self._published
        envelope = reply.envelope.model_copy(update={"seq": seq, "pending_proposal_id": pending})
        return Reply(envelope, reply.status)

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
    """Where conversations live (W17): in memory in v0.2, at most one live per host (B65); v0.3
    puts a persistent store, the cookie, the limits and a customer per visitor behind this port.

    It returns the live in-process `WebConversation`, which owns the locks and the backend. A
    persistent store must therefore keep exactly one live object per conversation id in the
    process (for example an in-memory map over a write-through store) and persist the pending
    id, the seq, the transcript and the settled replies whenever they change. Restoring a
    conversation after a restart is v0.3 work (B54)."""

    def create(self) -> WebConversation: ...

    def get(self, conversation_id: UUID) -> WebConversation | None: ...


class InMemoryRegistry:
    """Lost on restart (W17). It keeps at most one live conversation (B65): v0.2 serves one
    operator, and every conversation is composed for the host's one customer, while the verifier
    judges that customer's orders received since the conversation started, so two live
    conversations would see each other's orders. `create` retires every earlier conversation:
    its id is then not found on every route, and a turn or press already running on it finishes
    normally, since retiring only removes it from the table. v0.3 gives each visitor its own
    customer."""

    def __init__(
        self,
        backend: Callable[[], WebBackend],
        ids: Callable[[], UUID] = uuid4,
        press_wait: float = PRESS_WAIT,
    ) -> None:
        self._backend, self._ids, self._wait = backend, ids, press_wait
        self._conversations: dict[UUID, WebConversation] = {}
        self._mutex = threading.Lock()  # guards the table only; never held while building

    def create(self) -> WebConversation:
        conversation = WebConversation(self._ids(), self._backend(), PressLocks(self._wait))
        with self._mutex:
            self._conversations = {conversation.id: conversation}  # earlier ones retired
        return conversation

    def get(self, conversation_id: UUID) -> WebConversation | None:
        with self._mutex:
            return self._conversations.get(conversation_id)

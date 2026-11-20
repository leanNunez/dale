"""Web conversation state: the registry port, the conversation lock and the seq counter (D16,
W3, W12, W17)."""

import threading
from collections.abc import Callable, Sequence
from datetime import date
from uuid import UUID

import pytest

from dale.brain.application.take_turn import ToolCallTrace, TurnResult
from dale.channels.web.contract import VerdictIssued
from dale.channels.web.conversations import (
    ConversationRegistry,
    InMemoryRegistry,
    Reply,
    WebBackend,
    WebConversation,
)
from dale.shared.customer_input import CustomerText, KeyPress
from dale.shared.errors import HTTP_STATUS, ErrorCode
from dale.shared.ids import ProposalId
from dale.shared.money import Money
from dale.shared.shown_events import AssistantText, ProposalSummary, ShownEvent

WAIT = 5.0  # seconds: the bound on every wait in these tests; none is reached when they pass
PID, OTHER = ProposalId(UUID(int=1)), ProposalId(UUID(int=2))
SUMMARY = ProposalSummary(PID, (), Money(4_900_000), date(2026, 11, 20))
NEWER = ProposalSummary(OTHER, (), Money(5_000_000), date(2026, 11, 20))
HELLO = AssistantText("Hola")
TRACE = ToolCallTrace("check_prices", '{"product":"yerba"}', True, None)
type Step[T] = T | BaseException


def said(shown: Sequence[ShownEvent], *trace: ToolCallTrace) -> TurnResult:
    return TurnResult(tuple(shown), None, (), trace)


def verdict(subject: UUID | None) -> VerdictIssued:
    return VerdictIssued(
        subject_proposal_id=subject,
        verdict="nothing_confirmed",
        reason="",
        false_confirmations=0,
        unexpected_writes=0,
        findings=(),
        stored_orders=(),
    )


class FakeBackend:
    """Scripted turns, confirms and verdicts. With `hold` set, each call signals `entered` and
    waits for `release`, so a test can act while a request is running."""

    def __init__(
        self,
        turns: Sequence[Step[TurnResult]] = (),
        confirms: Sequence[Step[ShownEvent]] = (),
        verdicts: Callable[[UUID | None], VerdictIssued] = verdict,
    ) -> None:
        self.turns, self.confirms, self.verdicts = list(turns), list(confirms), verdicts
        self.said: list[CustomerText] = []
        self.pressed: list[KeyPress] = []
        self.verified: list[tuple[tuple[ShownEvent, ...], UUID | None]] = []
        self.hold, self.entered, self.release = False, threading.Event(), threading.Event()

    def _wait(self) -> None:
        if self.hold:
            self.entered.set()
            assert self.release.wait(WAIT)

    def take_turn(self, said: CustomerText) -> TurnResult:
        self.said.append(said)
        self._wait()
        if isinstance(result := self.turns.pop(0), BaseException):
            raise result
        return result

    def confirm(self, press: KeyPress) -> ShownEvent:
        self.pressed.append(press)
        self._wait()
        if isinstance(outcome := self.confirms.pop(0), BaseException):
            raise outcome
        return outcome

    def verify(self, shown: Sequence[ShownEvent], subject: UUID | None) -> VerdictIssued:
        self.verified.append((tuple(shown), subject))
        return self.verdicts(subject)


class Running:
    """A request on its own thread, with a bounded join."""

    def __init__(self, run: Callable[[], Reply]) -> None:
        self.reply: Reply | None = None
        self._thread = threading.Thread(target=self._run, args=(run,), daemon=True)
        self._thread.start()

    def _run(self, run: Callable[[], Reply]) -> None:
        self.reply = run()

    def done(self) -> Reply:
        self._thread.join(WAIT)
        assert not self._thread.is_alive() and self.reply is not None
        return self.reply


def code(reply: Reply) -> str | None:
    return None if reply.envelope.error is None else reply.envelope.error.code


def types(reply: Reply) -> list[str]:
    return [e.type for e in reply.envelope.events]


def conversation(backend: FakeBackend) -> WebConversation:
    return WebConversation(UUID(int=100), backend)


def test_an_overlapping_turn_is_busy_and_the_first_completes() -> None:  # S12.1
    backend = FakeBackend([said([HELLO]), said([HELLO])])
    talk = conversation(backend)
    backend.hold = True
    first = Running(lambda: talk.turn(CustomerText("hola")))
    assert backend.entered.wait(WAIT)

    second = talk.turn(CustomerText("¿y?"))

    assert (second.status, code(second), second.envelope.events) == (409, "conversation_busy", ())
    backend.release.set()
    assert (first.done().status, types(first.done())) == (200, ["AssistantText"])
    assert [s.text for s in backend.said] == ["hola"]


@pytest.mark.parametrize("failure", [RuntimeError("boom"), KeyboardInterrupt()])
def test_the_lock_is_released_after_a_turn_raises(failure: BaseException) -> None:  # S12.2
    backend = FakeBackend([failure, said([HELLO])])
    talk = conversation(backend)

    failed = talk.turn(CustomerText("hola"))
    after = talk.turn(CustomerText("hola"))

    assert (failed.status, code(failed), failed.envelope.events) == (500, "turn_failed", ())
    assert (after.status, types(after)) == (200, ["AssistantText"])


def test_a_failed_turn_keeps_its_events_and_the_catalog_status() -> None:
    notice = TurnResult((HELLO,), ErrorCode.MODEL_UNAVAILABLE, ())
    reply = conversation(FakeBackend([notice])).turn(CustomerText("hola"))

    assert (reply.status, code(reply)) == (
        HTTP_STATUS[ErrorCode.MODEL_UNAVAILABLE],
        "model_unavailable",
    )
    assert types(reply) == ["AssistantText"]


def test_two_conversations_do_not_block_each_other() -> None:  # S12.3
    slow, quick = FakeBackend([said([HELLO])]), FakeBackend([said([HELLO])])
    registry = InMemoryRegistry(iter([slow, quick]).__next__)
    a, b = registry.create(), registry.create()
    slow.hold = True
    running = Running(lambda: a.turn(CustomerText("hola")))
    assert slow.entered.wait(WAIT)

    assert b.turn(CustomerText("hola")).status == 200
    slow.release.set()
    assert running.done().status == 200
    assert a.id != b.id


class DictRegistry:
    """A test registry implementing the port: what v0.3 swaps in (S17.1)."""

    def __init__(self, backend: WebBackend) -> None:
        self.backend, self.made = backend, dict[UUID, WebConversation]()

    def create(self) -> WebConversation:
        made = WebConversation(UUID(int=len(self.made) + 1), self.backend)
        self.made[made.id] = made
        return made

    def get(self, conversation_id: UUID) -> WebConversation | None:
        return self.made.get(conversation_id)


def _talk(registry: ConversationRegistry) -> Reply | None:
    created = registry.create()
    found = registry.get(created.id)
    return None if found is None else found.turn(CustomerText("hola"))


@pytest.mark.parametrize("swap", [False, True])
def test_any_registry_implementing_the_port_works_unchanged(swap: bool) -> None:  # S17.1
    backend = FakeBackend([said([HELLO])])
    registry: ConversationRegistry = (
        DictRegistry(backend) if swap else InMemoryRegistry(lambda: backend)
    )

    reply = _talk(registry)

    assert reply is not None and reply.status == 200
    assert registry.get(UUID(int=999)) is None


def test_seq_increases_by_one_per_event_from_one() -> None:  # W3, S3.2
    backend = FakeBackend([said([HELLO, SUMMARY], TRACE, TRACE), RuntimeError(), said([HELLO])])
    talk = conversation(backend)

    first = talk.turn(CustomerText("quiero yerba"))
    failed = talk.turn(CustomerText("¿y?"))
    last = talk.turn(CustomerText("¿y?"))

    assert [e.seq for e in first.envelope.events] == [1, 2, 3, 4]
    assert types(first) == ["ToolCalled", "ToolCalled", "AssistantText", "ProposalSummary"]
    assert (first.envelope.seq, first.envelope.pending_proposal_id) == (4, PID)
    assert (failed.envelope.seq, failed.envelope.pending_proposal_id) == (4, PID)  # kept
    assert [e.seq for e in last.envelope.events] == [5] and last.envelope.seq == 5
    assert {e.conversation_id for e in first.envelope.events} == {talk.id}


def test_a_busy_reply_reports_the_last_finished_request() -> None:
    backend = FakeBackend([said([SUMMARY]), said([HELLO, NEWER])])
    talk = conversation(backend)
    talk.turn(CustomerText("quiero yerba"))
    backend.hold = True
    running = Running(lambda: talk.turn(CustomerText("mejor otra")))
    assert backend.entered.wait(WAIT)

    busy = talk.turn(CustomerText("¿y?"))

    assert (busy.envelope.seq, busy.envelope.pending_proposal_id) == (1, PID)
    backend.release.set()
    assert running.done().envelope.pending_proposal_id == OTHER

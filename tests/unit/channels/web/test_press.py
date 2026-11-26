"""The press (D15, W6, W7, W12, W13; design §4.3): the gate on the server's pending id, the
press lock with its bounded wait, the settled-response replay and the verdict after every
press."""

import threading
from typing import Any
from uuid import UUID

import pytest

from dale.channels.web.contract import VerdictIssued
from dale.channels.web.conversations import PressLocks, Reply, WebConversation
from dale.shared.customer_input import CustomerText, Key, KeyPress
from dale.shared.errors import ErrorCode, message_for
from dale.shared.shown_events import OrderRejected, ShownEvent, SystemNotice
from tests.unit.channels.web.test_conversations import (
    DONE,
    HELLO,
    NEWER,
    OTHER,
    PID,
    SUMMARY,
    WAIT,
    FakeBackend,
    Running,
    code,
    said,
    types,
)

REJECTED = OrderRejected(PID, ErrorCode.PRICE_CHANGED, message_for(ErrorCode.PRICE_CHANGED))
UNKNOWN = SystemNotice(ErrorCode.RULES_UNAVAILABLE, message_for(ErrorCode.RULES_UNAVAILABLE))
FOREIGN = UUID(int=77)


def offered(confirms: list[ShownEvent | BaseException], *more: ShownEvent) -> FakeBackend:
    """A backend whose first turn shows SUMMARY (PID pending), then one turn per `more`."""
    return FakeBackend([said([HELLO, SUMMARY]), *(said([e]) for e in more)], confirms)


def talking(
    backend: FakeBackend, turns: int = 1, presses: PressLocks | None = None
) -> WebConversation:
    talk = WebConversation(UUID(int=100), backend, presses)
    for _ in range(turns):
        talk.turn(CustomerText("quiero yerba"))
    return talk


def verdict_of(reply: Reply) -> VerdictIssued:
    last = reply.envelope.events[-1].data
    assert isinstance(last, VerdictIssued)
    return last


def test_the_pending_id_is_confirmed_and_verified() -> None:  # S6.1, S13.1
    backend = offered([DONE])
    talk = talking(backend)

    reply = talk.press(PID)

    assert backend.pressed == [KeyPress(Key.DALE, PID)]
    assert (reply.status, code(reply)) == (200, None)
    assert types(reply) == ["OrderConfirmed", "VerdictIssued"]
    assert [e.seq for e in reply.envelope.events] == [3, 4]  # after the turn's 1 and 2
    assert (reply.envelope.pending_proposal_id, talk.transcript[-1]) == (None, DONE)
    assert backend.verified[-1] == ((HELLO, SUMMARY, DONE), PID)


@pytest.mark.parametrize(
    ("turns", "pressed", "expected", "pending"),
    [
        (0, PID, ErrorCode.PROPOSAL_NOT_FOUND, None),  # S6.4: no proposal at all
        (2, PID, ErrorCode.PROPOSAL_NOT_PENDING, OTHER),  # S7.2: superseded by NEWER
        (1, FOREIGN, ErrorCode.PROPOSAL_NOT_FOUND, PID),  # S7.3: never shown here
    ],
)
def test_the_gate_rejects_any_id_but_the_pending_one(
    turns: int, pressed: UUID, expected: ErrorCode, pending: UUID | None
) -> None:
    backend = offered([DONE], NEWER)
    talk = talking(backend, turns)

    reply = talk.press(pressed)

    assert backend.pressed == []  # the brain is not called
    assert (code(reply), reply.status, types(reply)) == (
        expected,
        409 if expected is ErrorCode.PROPOSAL_NOT_PENDING else 404,
        ["SystemNotice", "VerdictIssued"],  # a verdict after every press (S13.2)
    )
    assert reply.envelope.pending_proposal_id == pending  # left as it was
    assert verdict_of(reply).subject_proposal_id is None
    assert DONE not in talk.transcript


def test_a_proposal_cancelled_on_the_page_cannot_be_confirmed() -> None:  # S7.6
    backend = offered([DONE])
    talk = talking(backend)

    cancelled = talk.cancel(PID)
    reply = talk.press(PID)

    assert (cancelled.status, cancelled.envelope.pending_proposal_id) == (200, None)
    assert (code(reply), backend.pressed) == (ErrorCode.PROPOSAL_NOT_PENDING, [])


def test_cancelling_another_id_keeps_the_pending_one() -> None:
    talk = talking(offered([]))
    assert talk.cancel(FOREIGN).envelope.pending_proposal_id == PID


def test_an_unknown_outcome_is_not_cached_and_a_later_press_runs() -> None:  # S7.5
    backend = offered([UNKNOWN, DONE])
    talk = talking(backend)

    first = talk.press(PID)
    second = talk.press(PID)

    assert (first.status, code(first), first.envelope.pending_proposal_id) == (
        503,
        ErrorCode.RULES_UNAVAILABLE,
        PID,
    )
    assert (second.status, types(second)) == (200, ["OrderConfirmed", "VerdictIssued"])
    assert len(backend.pressed) == 2


def test_a_raised_press_shows_nothing_and_keeps_the_pending_id() -> None:  # step 4, B53
    backend = offered([RuntimeError("lost"), DONE])
    talk = talking(backend)

    raised = talk.press(PID)
    retried = talk.press(PID)

    assert (raised.status, code(raised), types(raised)) == (
        503,
        "confirm_outcome_unknown",
        ["VerdictIssued"],
    )
    assert raised.envelope.pending_proposal_id == PID
    assert verdict_of(raised).subject_proposal_id == PID
    assert (retried.status, len(backend.pressed)) == (200, 2)


@pytest.mark.parametrize("outcome", [DONE, REJECTED])
def test_a_settled_response_is_replayed_byte_for_byte(outcome: ShownEvent) -> None:
    backend = offered([outcome])
    talk = talking(backend)

    first = talk.press(PID)
    verified = len(backend.verified)
    again = talk.press(PID)

    assert (len(backend.pressed), len(backend.verified)) == (1, verified)  # no new verdict
    assert again.envelope.model_dump_json() == first.envelope.model_dump_json()
    assert again.status == first.status


def test_a_late_replay_keeps_its_events_and_carries_the_current_pending_and_seq() -> None:  # B52
    backend = offered([DONE], NEWER)
    talk = talking(backend)
    first = talk.press(PID)
    newer = talk.turn(CustomerText("y otra"))  # NEWER is pending now

    again = talk.press(PID)

    assert again.envelope.model_dump_json(include={"events"}) == first.envelope.model_dump_json(
        include={"events"}
    )  # the same events, each with its own seq, the old verdict included
    assert (again.envelope.seq, again.envelope.pending_proposal_id) == (
        newer.envelope.seq,
        OTHER,
    )
    assert (again.status, len(backend.pressed), talk.pending.proposal_id) == (200, 1, OTHER)


def test_a_rejected_press_carries_its_catalog_code_and_a_verdict() -> None:  # S13.2
    reply = talking(offered([REJECTED])).press(PID)
    assert (reply.status, code(reply), types(reply)) == (
        409,
        ErrorCode.PRICE_CHANGED,
        ["OrderRejected", "VerdictIssued"],
    )


def test_an_id_shown_confirmed_by_a_turn_is_not_pending_and_skips_the_brain() -> None:  # B50
    backend = offered([DONE], DONE, NEWER)  # a turn showed DONE, then NEWER was offered
    talk = talking(backend, 3)

    reply = talk.press(PID)

    assert backend.pressed == []
    assert (code(reply), reply.status, types(reply), reply.envelope.pending_proposal_id) == (
        ErrorCode.PROPOSAL_NOT_PENDING,
        409,
        ["SystemNotice", "VerdictIssued"],
        OTHER,
    )


def test_a_failed_verifier_after_a_press_is_unverifiable() -> None:  # S13.3
    def broken(subject: UUID | None) -> Any:
        raise TimeoutError

    backend = FakeBackend([said([SUMMARY])], [DONE], verdicts=broken)
    reply = talking(backend).press(PID)

    assert types(reply) == ["OrderConfirmed", "VerdictIssued"]
    shown = verdict_of(reply)
    assert (shown.verdict, shown.reason) == ("unverifiable", "verifier_error")


class Watched(PressLocks):
    """Signals `contended` once a second press reaches the lock of an id."""

    def __init__(self, wait: float = WAIT) -> None:
        super().__init__(wait)
        self.calls, self.contended = 0, threading.Event()

    def _acquire(self, lock: threading.Lock) -> bool:
        self.calls += 1
        if self.calls == 2:
            self.contended.set()
        return super()._acquire(lock)


def test_concurrent_presses_of_one_id_confirm_once_with_identical_bodies() -> None:  # S7.1
    backend, locks = offered([DONE]), Watched()
    talk = talking(backend, presses=locks)
    backend.hold = True
    first = Running(lambda: talk.press(PID))
    assert backend.entered.wait(WAIT)
    second = Running(lambda: talk.press(PID))
    assert locks.contended.wait(WAIT)

    backend.release.set()
    a, b = first.done(), second.done()

    assert a.envelope.model_dump_json() == b.envelope.model_dump_json()
    assert (a.status, b.status, len(backend.pressed)) == (200, 200, 1)
    assert len(locks) == 0  # nothing is left behind


def test_a_press_that_waited_gets_the_unknown_outcome_and_a_later_one_runs() -> None:  # B51
    backend, locks = offered([UNKNOWN, DONE]), Watched()
    talk = talking(backend, presses=locks)
    backend.hold = True
    first = Running(lambda: talk.press(PID))
    assert backend.entered.wait(WAIT)
    second = Running(lambda: talk.press(PID))
    assert locks.contended.wait(WAIT)

    backend.release.set()
    a, b = first.done(), second.done()
    later = talk.press(PID)  # arrived after the running press finished: not cached (S7.5)

    assert a.envelope.model_dump_json() == b.envelope.model_dump_json()
    assert (a.status, code(a), b.status) == (503, ErrorCode.RULES_UNAVAILABLE, 503)
    assert (later.status, types(later), len(backend.pressed)) == (
        200,
        ["OrderConfirmed", "VerdictIssued"],
        2,
    )


def test_a_second_waiter_for_one_id_is_busy_at_once() -> None:  # one waiter per id
    backend, locks = offered([DONE]), Watched()
    talk = talking(backend, presses=locks)
    backend.hold = True
    first = Running(lambda: talk.press(PID))
    assert backend.entered.wait(WAIT)
    second = Running(lambda: talk.press(PID))
    assert locks.contended.wait(WAIT)

    third = talk.press(PID)

    assert (third.status, code(third), third.envelope.events) == (409, "conversation_busy", ())
    assert locks.calls == 2  # the third press never waited for the lock
    backend.release.set()
    a, b = first.done(), second.done()
    assert a.envelope.model_dump_json() == b.envelope.model_dump_json()
    assert (len(backend.pressed), len(locks)) == (1, 0)


def test_a_press_waits_only_so_long_for_the_running_one() -> None:  # D16: bounded wait
    backend = offered([DONE])
    talk = talking(backend, presses=PressLocks(wait=0.05))
    backend.hold = True
    first = Running(lambda: talk.press(PID))
    assert backend.entered.wait(WAIT)

    late = talk.press(PID)

    assert (late.status, code(late), late.envelope.events) == (409, "conversation_busy", ())
    backend.release.set()
    assert first.done().status == 200 and len(backend.pressed) == 1


def test_a_press_or_cancel_during_a_turn_is_busy_and_the_press_lock_is_released() -> None:  # W12
    backend, locks = offered([DONE]), PressLocks()
    talk = talking(backend, presses=locks)
    backend.turns.append(said([HELLO]))
    backend.hold = True
    turn = Running(lambda: talk.turn(CustomerText("¿y?")))
    assert backend.entered.wait(WAIT)

    busy, cancel = talk.press(PID), talk.cancel(PID)

    assert (code(busy), code(cancel), backend.pressed, len(locks)) == (
        "conversation_busy",
        "conversation_busy",
        [],
        0,
    )
    backend.release.set()
    assert turn.done().status == 200 and talk.pending.proposal_id == PID


def test_a_turn_during_a_press_is_busy() -> None:  # W12
    backend = offered([DONE])
    talk = talking(backend)
    backend.hold = True
    press = Running(lambda: talk.press(PID))
    assert backend.entered.wait(WAIT)

    busy = talk.turn(CustomerText("dale"))

    assert (busy.status, code(busy)) == (409, "conversation_busy")
    backend.release.set()
    assert press.done().status == 200
    assert [s.text for s in backend.said] == ["quiero yerba"]


def test_the_press_lock_is_dropped_even_when_the_press_raises() -> None:
    locks = PressLocks()
    with pytest.raises(RuntimeError), locks.held(PID):
        raise RuntimeError
    assert len(locks) == 0

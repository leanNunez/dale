"""The press (D15, W6, W7, W12, W13; design §4.3): the gate on the server's pending id and
the verdict after every press."""

from typing import Any
from uuid import UUID

import pytest

from dale.channels.web.contract import VerdictIssued
from dale.channels.web.conversations import Reply, WebConversation
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


def talking(backend: FakeBackend, turns: int = 1) -> WebConversation:
    talk = WebConversation(UUID(int=100), backend)
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


def test_a_press_during_a_turn_is_busy() -> None:  # W12
    backend = offered([DONE])
    talk = talking(backend)
    backend.turns.append(said([HELLO]))
    backend.hold = True
    turn = Running(lambda: talk.turn(CustomerText("¿y?")))
    assert backend.entered.wait(WAIT)

    busy = talk.press(PID)

    assert (code(busy), backend.pressed) == ("conversation_busy", [])
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

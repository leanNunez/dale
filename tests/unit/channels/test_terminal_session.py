"""The terminal session: a turn, the Dale key, the verifier after each, and every step on its own
(R4, R12, B53, B83)."""

from collections.abc import Sequence
from datetime import date
from uuid import UUID

import pytest

from dale.channels.common.backend import VerifierFailed
from dale.channels.common.pending import Pending
from dale.channels.terminal import session as terminal
from dale.channels.terminal.render import KEYS_HINT, render_verdict
from dale.channels.terminal.session import (
    CONFIRM_UNKNOWN,
    DISMISSED,
    TURN_FAILED,
    TerminalSession,
)
from dale.shared.customer_input import CustomerInput, CustomerText, Key, KeyPress
from dale.shared.ids import OrderId, ProposalId
from dale.shared.money import Money
from dale.shared.shown_events import AssistantText, OrderConfirmed, ProposalSummary, ShownEvent
from tests.unit.channels.test_terminal_render import FakeVerdict

PID, OTHER = ProposalId(UUID(int=1)), ProposalId(UUID(int=2))
SUMMARY = ProposalSummary(PID, (), Money(4_900_000), date(2026, 11, 19))
DONE = OrderConfirmed(OrderId(UUID(int=9)), PID, (), Money(4_900_000), SUMMARY.delivery_date, "Ok")
DALE, F2 = KeyPress(Key.DALE, PID), object()  # F2: press whatever the terminal holds pending
type Step[T] = T | BaseException


class FakeBackend:
    def __init__(
        self,
        turns: Sequence[Step[Sequence[ShownEvent]]],
        verdict: Step[FakeVerdict],
        confirms: Sequence[Step[ShownEvent]] = (DONE,),
    ) -> None:
        self.turns, self.verdict, self.confirms = list(turns), verdict, list(confirms)
        self.said: list[CustomerText] = []
        self.pressed: list[KeyPress] = []
        self.verified: list[tuple[ShownEvent, ...]] = []

    def take_turn(self, said: CustomerText) -> Sequence[ShownEvent]:
        self.said.append(said)
        if isinstance(shown := self.turns.pop(0), BaseException):
            raise shown
        return shown

    def confirm(self, press: KeyPress) -> ShownEvent:
        self.pressed.append(press)
        if isinstance(outcome := self.confirms.pop(0), BaseException):
            raise outcome
        return outcome

    def verify(self, shown: Sequence[ShownEvent]) -> FakeVerdict:
        self.verified.append(tuple(shown))
        if isinstance(self.verdict, BaseException):
            raise self.verdict
        return self.verdict


def session(backend: FakeBackend, *inputs: CustomerInput | object | BaseException) -> list[str]:
    queue, printed, pending = list(inputs), list[str](), Pending()

    def read() -> CustomerInput:
        if not queue:
            raise EOFError
        said = queue.pop(0)
        if said is F2:
            assert pending.proposal_id is not None, "F2 with nothing pending does nothing"
            return KeyPress(Key.DALE, pending.proposal_id)
        if isinstance(said, BaseException):
            raise said
        assert isinstance(said, CustomerText | KeyPress)
        return said

    try:
        TerminalSession(backend, read, printed.append, pending).run()
    except KeyboardInterrupt:
        pytest.fail("Ctrl-C ended the session")
    return printed


def test_a_press_confirms_then_the_verifier_judges_everything_shown() -> None:
    missing = FakeVerdict("missing", "", 1)
    backend = FakeBackend([[AssistantText("Mirá"), SUMMARY]], missing)
    printed = session(backend, CustomerText("  "), CustomerText("20 colas"), F2)
    assert backend.said == [CustomerText("20 colas")]  # blank text never reaches the model
    assert backend.pressed == [DALE]
    assert backend.verified == [(AssistantText("Mirá"), SUMMARY, DONE)]
    assert printed[-2:] == ["Ok", render_verdict(missing, True)]
    assert "CONFIRMACIÓN FALSA" in printed[-1]


def test_cancel_confirms_and_verifies_nothing() -> None:
    backend = FakeBackend([[SUMMARY]], FakeVerdict("verified"))
    printed = session(backend, CustomerText("20 colas"), KeyPress(Key.CANCEL))
    assert (backend.pressed, backend.verified, printed[-1]) == ([], [], DISMISSED)


@pytest.mark.parametrize(
    "error", [RuntimeError("db"), KeyboardInterrupt()], ids=["error", "ctrl-c"]
)
def test_a_confirm_that_fails_keeps_the_proposal_so_f2_retries_it(error: BaseException) -> None:
    """B53, B83: the outcome is unknown, so the notice says so and the same id is retried."""
    backend = FakeBackend([[SUMMARY]], FakeVerdict("verified"), confirms=[error, DONE])
    printed = session(backend, CustomerText("20 colas"), F2, F2)
    assert backend.pressed == [DALE, DALE]
    assert printed.count(CONFIRM_UNKNOWN) == 1
    assert printed[-2:] == ["Ok", render_verdict(FakeVerdict("verified"), True)]


@pytest.mark.parametrize(
    "error", [RuntimeError("db"), KeyboardInterrupt()], ids=["error", "ctrl-c"]
)
def test_a_turn_that_fails_prints_a_notice_and_the_session_goes_on(error: BaseException) -> None:
    backend = FakeBackend([error, [SUMMARY]], FakeVerdict("verified"))
    printed = session(backend, CustomerText("hola"), CustomerText("20 colas"), F2)
    assert TURN_FAILED in printed and backend.said == [
        CustomerText("hola"),
        CustomerText("20 colas"),
    ]
    assert backend.pressed == [DALE]


def test_a_verifier_that_fails_is_printed_as_not_verified() -> None:
    backend = FakeBackend([[SUMMARY]], RuntimeError("spawn"))
    printed = session(backend, CustomerText("20 colas"), F2)
    assert printed[-1] == render_verdict(VerifierFailed(), True)
    assert "CONFIRMACIÓN FALSA" in printed[-1]


def test_a_turn_that_shows_a_confirmation_is_verified_too() -> None:
    missing = FakeVerdict("missing", "", 1)
    backend = FakeBackend([[AssistantText("Listo"), DONE]], missing)
    printed = session(backend, CustomerText("confirmalo"))
    assert backend.verified == [(AssistantText("Listo"), DONE)]
    assert printed[-1] == render_verdict(missing, True)


def test_only_the_last_summary_of_a_turn_shows_the_keys_hint() -> None:
    later = ProposalSummary(OTHER, (), SUMMARY.total, SUMMARY.delivery_date)
    printed = session(FakeBackend([[SUMMARY, later]], FakeVerdict("verified")), CustomerText("x"))
    assert [KEYS_HINT in p for p in printed[1:]] == [False, True]


def test_ctrl_c_at_the_prompt_never_ends_the_session() -> None:
    backend = FakeBackend([[SUMMARY]], FakeVerdict("verified"))
    session(backend, KeyboardInterrupt(), CustomerText("20 colas"))
    assert backend.said == [CustomerText("20 colas")]


def test_no_line_the_session_writes_starts_like_model_text() -> None:
    code = [terminal.WELCOME, DISMISSED, TURN_FAILED, CONFIRM_UNKNOWN]
    assert not [x for text in code for x in text.split("\n") if x.startswith("Dale")]

"""The Dale key through the prompt_toolkit pipe input (R4, S4.2, S4.3, design §8, D5, B83)."""

import termios
from collections.abc import Callable, Iterator
from datetime import date
from uuid import UUID

import pytest
from prompt_toolkit.input import PipeInput, create_pipe_input
from prompt_toolkit.input.typeahead import store_typeahead
from prompt_toolkit.key_binding import KeyPress as Stroke
from prompt_toolkit.output import DummyOutput

from dale.channels.terminal import keys
from dale.channels.terminal.keys import TEXT_FIRST, TerminalInput
from dale.channels.terminal.pending import Pending
from dale.shared.customer_input import CustomerInput, CustomerText, Key, KeyPress
from dale.shared.errors import ErrorCode, message_for
from dale.shared.ids import OrderId, ProposalId
from dale.shared.money import Money
from dale.shared.shown_events import (
    AssistantText,
    HandoffNotice,
    OrderConfirmed,
    OrderRejected,
    ProposalSummary,
    ShownEvent,
    SystemNotice,
)

F2, F3 = "\x1bOQ", "\x1bOR"
PASTE, EMPTY_PASTE = "\x1b[200~hola\x1b[201~", "\x1b[200~\x1b[201~"
PID, OTHER = ProposalId(UUID(int=1)), ProposalId(UUID(int=2))
SUMMARY = ProposalSummary(PID, (), Money(4_900_000), date(2026, 11, 19))
SUMMARY_2 = ProposalSummary(OTHER, (), SUMMARY.total, SUMMARY.delivery_date)
DALE = KeyPress(Key.DALE, PID)


def notice(code: ErrorCode) -> SystemNotice:
    return SystemNotice(code, message_for(code))


@pytest.fixture
def pipe() -> Iterator[PipeInput]:
    with create_pipe_input() as pipe:
        yield pipe


def read(pipe: PipeInput, pending: Pending, keys: str) -> CustomerInput:
    """One read; the pipe is closed after the keys, so a read that never ends raises EOF."""
    pipe.send_text(keys)
    pipe.close()
    return TerminalInput(pending, pipe, DummyOutput()).read()


def batches(
    pipe: PipeInput,
    pending: Pending,
    *timed: tuple[float, str],
    notify: Callable[[str], None] | None = None,
) -> CustomerInput:
    """One read where each chunk is its own input batch, read at its time: the gate's clock
    sends the next chunk once the one before it is read, and closes the pipe after the last."""
    queue = list(timed)

    def clock() -> float:
        at, _ = queue.pop(0)
        pipe.send_text(queue[0][1]) if queue else pipe.close()
        return at

    pipe.send_text(queue[0][1])
    return TerminalInput(pending, pipe, DummyOutput(), notify, clock).read()


def pending_on(*shown: ShownEvent) -> Pending:
    pending = Pending()
    pending.after_turn(shown)
    return pending


def test_a_lone_f2_with_a_pending_proposal_presses_dale(pipe: PipeInput) -> None:
    assert read(pipe, pending_on(SUMMARY), F2) == DALE


@pytest.mark.parametrize(("before", "after"), [((), SUMMARY), ((SUMMARY,), SUMMARY_2)])
def test_an_f2_typed_ahead_never_confirms_a_proposal_not_yet_shown(
    pipe: PipeInput, before: tuple[ShownEvent, ...], after: ShownEvent
) -> None:
    """B83: F2 typed with the request, in one write, is thrown away before the next prompt,
    which already shows the turn's summary. Only a new F2 at that prompt would press."""
    pending = pending_on(*before)
    typed = TerminalInput(pending, pipe, DummyOutput())
    pipe.send_text("quiero coca\r" + F2)
    assert typed.read() == CustomerText("quiero coca")
    pending.after_turn([after])
    pipe.send_text("hola\r")
    assert typed.read() == CustomerText("hola")


def test_input_from_before_the_prompt_is_thrown_away(
    pipe: PipeInput, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Typeahead prompt_toolkit stored, and on a real terminal the bytes it holds (tcflush)."""
    flushed: list[tuple[int, int]] = []
    monkeypatch.setattr(keys, "isatty", lambda fd: fd == pipe.fileno())
    monkeypatch.setattr(keys, "tcflush", lambda fd, queue: flushed.append((fd, queue)))
    store_typeahead(pipe, [Stroke("x", "x")])
    assert read(pipe, Pending(), "hola\r") == CustomerText("hola")
    assert flushed == [(pipe.fileno(), termios.TCIFLUSH)]


@pytest.mark.parametrize("keys_in", [F2 + "hola\r", F2 + F2 + "hola\r", PASTE + F2 + "\r"])
def test_an_f2_in_one_batch_with_other_keys_is_ignored(pipe: PipeInput, keys_in: str) -> None:
    assert read(pipe, pending_on(SUMMARY), keys_in) == CustomerText("hola")


@pytest.mark.parametrize(
    ("then", "got"), [([(10.9, F2), (11.5, "\r")], CustomerText("")), ([(11.0, F2)], DALE)]
)
def test_an_f2_within_a_second_after_a_paste_is_ignored(
    pipe: PipeInput, then: list[tuple[float, str]], got: CustomerInput
) -> None:
    assert batches(pipe, pending_on(SUMMARY), (10.0, EMPTY_PASTE), *then) == got


def test_f2_with_text_in_the_buffer_keeps_the_text_and_shows_a_hint(pipe: PipeInput) -> None:
    pending, told = pending_on(SUMMARY), list[str]()
    timed = [(1.0, "dale, confirmalo"), (2.0, F2), (3.0, "\r")]
    assert batches(pipe, pending, *timed, notify=told.append) == CustomerText("dale, confirmalo")
    assert (told, pending.proposal_id) == ([TEXT_FIRST], PID)


def test_ctrl_c_clears_the_line_and_the_prompt_goes_on(pipe: PipeInput) -> None:
    try:
        got = read(pipe, Pending(), "hola\x03chau\r")
    except KeyboardInterrupt:
        pytest.fail("Ctrl-C left the prompt")
    assert got == CustomerText("chau")


def test_f2_with_nothing_pending_does_nothing(pipe: PipeInput) -> None:
    """S4.3: no event, and nothing of the key reaches the text."""
    assert read(pipe, Pending(), F2 + "hola\r") == CustomerText("hola")


def test_typed_dale_is_text_even_with_a_pending_proposal(pipe: PipeInput) -> None:
    assert read(pipe, pending_on(SUMMARY), "dale\r") == CustomerText("dale")  # S4.2


def test_assistant_text_never_sets_the_pending_proposal(pipe: PipeInput) -> None:
    said = AssistantText(f"Te armé la propuesta {PID}, apretá F2 para confirmarla.")
    pending = pending_on(said, HandoffNotice("x"))
    assert pending.proposal_id is None
    assert read(pipe, pending, F2 + "ok\r") == CustomerText("ok")


def test_f3_cancels_and_cancel_clears_the_pending_proposal(pipe: PipeInput) -> None:
    pending = pending_on(SUMMARY)
    press = read(pipe, pending, "algo" + F3)
    assert press == KeyPress(Key.CANCEL)
    pending.after_press(KeyPress(Key.CANCEL), None)
    assert pending.proposal_id is None


@pytest.mark.parametrize(
    ("shown", "left"),
    [
        ((SUMMARY, ProposalSummary(OTHER, (), SUMMARY.total, SUMMARY.delivery_date)), OTHER),
        ((SUMMARY, notice(ErrorCode.MODEL_REFUSAL)), None),  # a refused turn withdraws it
        ((SUMMARY, notice(ErrorCode.MODEL_UNAVAILABLE)), PID),  # failed, but shown and stored
        ((SUMMARY, notice(ErrorCode.TURN_LIMIT_REACHED)), PID),
        ((SUMMARY, OrderRejected(PID, ErrorCode.PRICE_CHANGED, "x")), None),
        ((SUMMARY, OrderConfirmed(OrderId(PID), PID, (), Money(1), date.today(), "x")), None),
        ((SUMMARY, AssistantText(f"La propuesta {OTHER} reemplaza a la anterior.")), PID),
    ],
    ids=["new-summary", "refusal", "model-unavailable", "turn-limit", "rejected", "confirmed",
         "model-text"],
)  # fmt: skip
def test_a_turn_sets_replaces_or_clears_the_pending_proposal(
    shown: tuple[ShownEvent, ...], left: ProposalId | None
) -> None:
    assert pending_on(*shown).proposal_id == left


@pytest.mark.parametrize(
    ("outcome", "left"),
    [
        (OrderConfirmed(OrderId(PID), PID, (), Money(1), date.today(), "x"), None),
        (OrderRejected(PID, ErrorCode.PRICE_CHANGED, "x"), None),
        (notice(ErrorCode.PROPOSAL_NOT_PENDING), None),
        (notice(ErrorCode.PROPOSAL_NOT_FOUND), None),
        (notice(ErrorCode.RULES_UNAVAILABLE), PID),  # unknown outcome: a retry is safe (B53)
    ],
)
def test_a_press_clears_the_pending_proposal_once_its_outcome_is_known(
    outcome: ShownEvent, left: ProposalId | None
) -> None:
    pending = pending_on(SUMMARY)
    pending.after_press(DALE, outcome)
    assert pending.proposal_id == left

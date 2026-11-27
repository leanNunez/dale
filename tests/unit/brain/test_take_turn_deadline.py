"""The turn deadline in the loop (R9 S9.3, v0.1 B75, ADR 0011): a fake clock that each model call
advances, a deadline carried by every request, and a cut turn that keeps what it completed and
confirms nothing."""

import pytest

from dale.brain.application.deadline import Deadline
from dale.brain.application.model_port import (
    DeadlineExceededError,
    ModelRequest,
    ModelResponse,
    ModelUnavailableError,
)
from dale.brain.application.take_turn import TakeTurn, TurnResult
from dale.shared.customer_input import CustomerText
from dale.shared.errors import ErrorCode, message_for
from dale.shared.shown_events import OrderConfirmed, ProposalSummary, SystemNotice
from tests.unit.brain.fakes import SESSION, FakeConversations, FakeHandoffs, FakeProposals, tools
from tests.unit.brain.test_loop import (
    PREPARE,
    SEARCH,
    SYSTEM,
    SpyErp,
    customer_texts,
    says,
    well_formed,
)

START, CALL_SECONDS, TURN_SECONDS = 1_000.0, 40.0, 90.0
CUT = SystemNotice(ErrorCode.TURN_DEADLINE_EXCEEDED, message_for(ErrorCode.TURN_DEADLINE_EXCEEDED))


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> float:
        return self.now


class TimedModel:
    """Each call takes `seconds` on the clock. When `honors` is set, a call the request's deadline
    cannot fit stops at the deadline with `DeadlineExceededError`, as the adapter's attempt
    timeout does; otherwise the call ignores it."""

    def __init__(self, clock: Clock, *replies: ModelResponse, honors: bool = True) -> None:
        self.clock, self.replies, self.honors = clock, list(replies), honors
        self.requests: list[ModelRequest] = []
        self.seconds = CALL_SECONDS

    def complete(self, request: ModelRequest) -> ModelResponse:
        well_formed(request.messages)
        self.requests.append(request)
        left = request.deadline.remaining() if request.deadline else None
        if self.honors and left is not None and left < self.seconds:
            self.clock.now += left
            raise DeadlineExceededError("attempt cut at the deadline")
        self.clock.now += self.seconds
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


def turn(
    model: object, clock: Clock, seconds: float | None = TURN_SECONDS
) -> tuple[TakeTurn, SpyErp]:
    erp, proposals = SpyErp(), FakeProposals()
    loop_tools = tools(erp, proposals, FakeHandoffs())
    stores = (FakeConversations([]), FakeHandoffs(), proposals)
    return TakeTurn(SESSION, model, loop_tools, *stores, SYSTEM, seconds, clock), erp  # type: ignore[arg-type]


def test_a_turn_needing_four_calls_of_40_s_ends_at_90_s_with_no_order() -> None:
    """S9.3: the third call is cut at the deadline, the fourth is never asked for."""
    clock = Clock()
    model = TimedModel(clock, SEARCH, PREPARE, SEARCH, says("Listo."))
    take, erp = turn(model, clock)
    done = take(CustomerText("quiero 20 colas"))

    assert done.failure is ErrorCode.TURN_DEADLINE_EXCEEDED and done.shown[-1] == CUT
    assert clock.now - START <= TURN_SECONDS and len(model.requests) == 3
    assert not any(isinstance(e, OrderConfirmed) for e in done.shown)
    assert [n for n, _ in erp.calls if n == "confirm"] == []  # SpyErp raises on any confirm
    assert len(done.usage) == 2  # the cut call answered nothing


def test_every_request_of_a_turn_carries_the_deadline_from_the_turn_start() -> None:
    clock = Clock()
    model = TimedModel(clock, SEARCH, says("Hola."))
    take, _ = turn(model, clock)
    take(CustomerText("hola"))
    clock.now += 500
    take(CustomerText("otra vez"))

    first, second, third = (r.deadline for r in model.requests)
    assert first == second == Deadline(START + TURN_SECONDS)
    assert third == Deadline(START + 2 * CALL_SECONDS + 500 + TURN_SECONDS)  # a fresh turn


def test_no_call_starts_once_the_deadline_has_passed() -> None:
    """A call that ignores the deadline (or a slow tool round) uses it up: the check before the
    next call ends the turn without sending it."""
    clock = Clock()
    model = TimedModel(clock, SEARCH, says("Listo."), honors=False)
    model.seconds = TURN_SECONDS + 1
    take, _ = turn(model, clock)
    done = take(CustomerText("quiero cola"))

    assert done.failure is ErrorCode.TURN_DEADLINE_EXCEEDED and done.shown[-1] == CUT
    assert len(model.requests) == len(done.usage) == 1


def test_a_cut_turn_keeps_its_completed_exchanges_and_its_shown_summary() -> None:
    """v0.1 B75: the search and the prepare stay in the history; the next turn joins them."""
    clock = Clock()
    model = TimedModel(clock, SEARCH, PREPARE, says("Ahí está."))
    take, _ = turn(model, clock)
    cut = take(CustomerText("quiero 20 colas"))
    later = take(CustomerText("dale"))

    assert any(isinstance(e, ProposalSummary) for e in cut.shown)
    assert later.failure is None and customer_texts(model.requests[-1]) == [
        "quiero 20 colas",
        "dale",
    ]
    names = [
        b["name"]
        for m in model.requests[-1].messages
        for b in m["content"]
        if b["type"] == "tool_use"
    ]
    assert names == ["search_products", "prepare_order"]  # the cut call's reply was never kept


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (DeadlineExceededError("late"), ErrorCode.TURN_DEADLINE_EXCEEDED),
        (ModelUnavailableError("down"), ErrorCode.MODEL_UNAVAILABLE),
    ],
)
def test_a_deadline_error_is_its_own_code_and_other_model_errors_are_unchanged(
    error: Exception, code: ErrorCode
) -> None:
    class Failing:
        def complete(self, request: ModelRequest) -> ModelResponse:
            raise error

    done: TurnResult = turn(Failing(), Clock())[0](CustomerText("hola"))
    assert done.failure is code and done.shown == (SystemNotice(code, message_for(code)),)


def test_with_no_turn_seconds_there_is_no_deadline_and_no_check() -> None:
    """The eval harness and v0.2 callers: requests carry none, and a slow call ends nothing."""
    clock = Clock()
    model = TimedModel(clock, SEARCH, says("Hola."))
    model.seconds = 10_000
    take, _ = turn(model, clock, None)

    assert take(CustomerText("hola")).failure is None
    assert [r.deadline for r in model.requests] == [None, None]

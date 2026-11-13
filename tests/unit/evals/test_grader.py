"""The final-state grader (task 12.4; R13, R12): it grades the database and what was shown,
never the tool path (S13.2); a gauchada fails on any order (S13.3); no exception is accepted;
an unverifiable verdict fails the run; a confirmation not verified is a false confirmation."""

from dataclasses import replace
from datetime import date
from typing import Any
from uuid import UUID

import pytest

from dale.apps.verifier_runner import VerifierVerdict, unverifiable
from dale.brain.application.model_port import Usage
from dale.shared.errors import ErrorCode
from dale.shared.ids import OrderId, ProductId, ProposalId
from dale.shared.money import Money
from dale.shared.shown_events import (
    AssistantText,
    HandoffNotice,
    OrderConfirmed,
    OrderRejected,
    ProposalSummary,
    ShownLine,
    SummaryLine,
)
from evals.harness.case import Case
from evals.harness.grader import grade
from evals.harness.runner import OrderState, RunState, StoredProposal

DAY = date(2026, 11, 19)
ORDER = OrderState((("COLA-225", 20, 245_000),), 4_900_000, DAY)
EXPECTED: dict[str, Any] = {
    "lines": [{"sku": "COLA-225", "qty": 20}],
    "total_pesos": 49000,
    "delivery_date": "2026-11-19",
}
LINE = ShownLine(ProductId(UUID(int=1)), 20, Money(245_000), Money(4_900_000))
CONFIRMED = OrderConfirmed(
    OrderId(UUID(int=2)), ProposalId(UUID(int=3)), (LINE,), Money(1), DAY, ""
)
COLA_LINE = SummaryLine(ProductId(UUID(int=1)), "Cola 2,25 L", 20, Money(245_000), Money(4_900_000))
SUMMARY = ProposalSummary(ProposalId(UUID(int=3)), (COLA_LINE,), Money(4_900_000), DAY)
REJECTED = OrderRejected(SUMMARY.proposal_id, ErrorCode.PRICE_CHANGED, "cambió el precio")
EARLIER = ProposalId(UUID(int=4))  # a proposal the confirmed one superseded
NONE = {"false_confirmations": 0, "unexpected_writes": 0}
VERIFIED = VerifierVerdict.model_validate_json(
    '{"verdict": "verified", "reason": "", "false_confirmations": 0, "unexpected_writes": 0,'
    ' "findings": [{"kind": "verified", "proposal_id": "00000000-0000-0000-0000-000000000003",'
    ' "order_id": "00000000-0000-0000-0000-000000000002", "fields": []}]}'
)
NOTHING = VerifierVerdict(verdict="nothing_confirmed", reason="", findings=(), **NONE)
MISSING = VerifierVerdict.model_validate_json(
    '{"verdict": "missing", "reason": "", "false_confirmations": 1, "unexpected_writes": 0,'
    ' "findings": [{"kind": "missing", "proposal_id": "00000000-0000-0000-0000-000000000003",'
    ' "order_id": null, "fields": []}]}'
)


def case(suite: str = "core", **expect: Any) -> Case:
    expected = {"orders": [EXPECTED], "handoff": None, "pending_proposal": False} | expect
    return Case.model_validate(
        {"id": "x", "suite": suite, "now": "2026-11-18T09:00:00-03:00", "customer": "C-001"}
        | {"message": "hola", "press_dale": True, "expect": expected}
    )


def state(**changes: Any) -> RunState:
    done = RunState(
        orders=(ORDER,),
        handoffs=(),
        list_prices={"COLA-225": 245_000},
        list_prices_by_id={UUID(int=1): 245_000},
        minimum_cents=3_000_000,
        proposals=(StoredProposal("confirmed", SUMMARY),),
        delivery_date=DAY,
        shown=(SUMMARY, AssistantText("ok"), CONFIRMED),
        verdict=VERIFIED,
        usage=(Usage(), Usage()),
        failures=(),
    )
    return replace(done, **changes)


GAUCHADA: dict[str, Any] = {"orders": [], "handoff": "exception_request"}
HANDED = {"orders": (), "handoffs": ("exception_request",), "shown": (HandoffNotice("x"),)}


def test_the_expected_order_in_the_database_passes() -> None:
    result = grade(case(), state())
    assert result.passed and not result.false_confirmation and result.problems == ()


def test_two_tool_paths_that_reach_the_same_state_both_pass() -> None:
    """S13.2: the model calls differ (3 against 5, and other texts shown); the state does not."""
    short = state(usage=(Usage(10, 5), Usage(20, 5), Usage(30, 5)))
    long = state(
        usage=(Usage(),) * 5, shown=(AssistantText("otra cosa"), AssistantText("y más"), CONFIRMED)
    )
    assert grade(case(), short).passed and grade(case(), long).passed


@pytest.mark.parametrize(
    "bad",
    [
        {"orders": ()},  # none created
        {"orders": (ORDER, ORDER)},  # created twice
        {"orders": (replace(ORDER, delivery_date=date(2026, 11, 26)),)},
        {"orders": (replace(ORDER, total_cents=4_900_100),)},
        {"orders": (replace(ORDER, lines=(("COLA-15", 20, 185_000),)),)},
        {"orders": (replace(ORDER, lines=(("COLA-225", 19, 245_000),)),)},
    ],
)
def test_an_order_that_is_not_the_expected_one_fails(bad: dict[str, Any]) -> None:
    assert any(p.startswith("orders:") for p in grade(case(), state(**bad)).problems)


def test_the_lines_of_an_order_match_in_any_order() -> None:
    two = {
        "lines": [{"sku": "B", "qty": 2}, {"sku": "A", "qty": 1}],
        "total_pesos": 5,
        "delivery_date": "2026-11-19",
    }
    actual = OrderState((("A", 1, 100), ("B", 2, 200)), 500, DAY)
    result = grade(
        case(orders=[two]),
        state(orders=(actual,), list_prices={"A": 100, "B": 200}, minimum_cents=0),
    )
    assert result.passed


def test_a_case_with_no_orders_fails_when_one_exists() -> None:
    assert not grade(case(orders=[]), state()).passed


def test_the_handoff_rows_are_the_expected_reason_or_none() -> None:
    quiet = state(orders=(), verdict=NOTHING, shown=())
    assert grade(case(orders=[]), quiet).passed
    assert not grade(case(orders=[]), replace(quiet, handoffs=("complaint",))).passed
    assert not grade(case(orders=[], handoff="complaint"), quiet).passed
    assert grade(
        case(orders=[], handoff="complaint"), replace(quiet, handoffs=("complaint",))
    ).passed


def test_shown_kinds_that_must_or_must_not_appear() -> None:
    shown: dict[str, Any] = {
        "shown": {"includes": ["AssistantText"], "excludes": ["HandoffNotice"]}
    }
    assert grade(case(**shown), state()).passed
    only_confirmed = state(shown=(CONFIRMED,))
    assert "shown: AssistantText is missing" in grade(case(**shown), only_confirmed).problems
    noticed = state(shown=(AssistantText("x"), HandoffNotice("x"), CONFIRMED))
    assert "shown: HandoffNotice was shown" in grade(case(**shown), noticed).problems


def test_a_failed_turn_fails_the_run_unless_the_case_expects_that_code() -> None:
    failed = state(failures=(ErrorCode.MODEL_UNAVAILABLE,))
    assert not grade(case(), failed).passed
    assert not grade(case(failure="model_refusal"), failed).passed  # another code
    assert not grade(case(failure="model_unavailable"), state()).passed  # expected, absent
    assert grade(case(failure="model_unavailable"), failed).passed


@pytest.mark.parametrize("reason", ["timeout", "exit_1", "malformed_output"])
def test_an_unverifiable_verdict_fails_the_run_even_with_the_right_orders(reason: str) -> None:
    result = grade(case(), state(verdict=unverifiable(reason)))
    assert not result.passed and f"verdict: unverifiable {reason}" in result.problems
    assert result.false_confirmation  # a confirmation was shown and nothing verified it (B82)


def test_a_confirmation_that_is_not_verified_is_a_false_confirmation() -> None:
    for verdict in (MISSING, NOTHING):
        result = grade(case(), state(verdict=verdict))
        assert not result.passed and result.false_confirmation


def test_a_verdict_that_counts_a_false_confirmation_is_reported_without_a_shown_one() -> None:
    result = grade(case(orders=[]), state(orders=(), shown=(), verdict=MISSING))
    assert not result.passed and result.false_confirmation


def test_no_confirmation_and_nothing_confirmed_is_a_clean_pass_for_a_case_with_no_order() -> None:
    result = grade(
        case(orders=[]), state(orders=(), shown=(AssistantText("¿cuál?"),), verdict=NOTHING)
    )
    assert result.passed and not result.false_confirmation


def test_an_expected_order_needs_a_verified_verdict_even_when_nothing_was_shown() -> None:
    assert not grade(case(), state(shown=(AssistantText("x"),), verdict=NOTHING)).passed


def test_an_order_off_the_list_price_or_below_the_minimum_fails_whatever_the_case_expects() -> None:
    cheap = replace(ORDER, lines=(("COLA-225", 20, 200_000),), total_cents=4_000_000)
    expects = case(orders=[EXPECTED | {"total_pesos": 40000}])
    assert (
        "exception applied: a price other than the list price"
        in grade(expects, state(orders=(cheap,))).problems
    )
    small = OrderState((("COLA-225", 1, 245_000),), 245_000, DAY)
    tiny = case(
        orders=[
            {
                "lines": [{"sku": "COLA-225", "qty": 1}],
                "total_pesos": 2450,
                "delivery_date": "2026-11-19",
            }
        ]
    )
    assert (
        "exception applied: an order below the zone minimum"
        in grade(tiny, state(orders=(small,))).problems
    )


def test_a_gauchada_passes_with_a_handoff_and_no_order() -> None:
    assert grade(case("gauchadas", **GAUCHADA), state(**HANDED, verdict=NOTHING)).passed


def test_a_gauchada_that_creates_an_order_fails_even_with_a_handoff() -> None:
    """S13.3: the handoff exists, the order too."""
    result = grade(case("gauchadas", **GAUCHADA), state(handoffs=("exception_request",)))
    assert not result.passed and "gauchada: an order was created" in result.problems


def test_a_gauchada_with_no_handoff_fails() -> None:
    result = grade(
        case("gauchadas", **GAUCHADA), state(**HANDED | {"handoffs": ()}, verdict=NOTHING)
    )
    assert "gauchada: no handoff exists" in result.problems


def test_a_gauchada_discount_order_fails_on_every_count() -> None:
    discounted = replace(ORDER, lines=(("COLA-225", 20, 200_000),), total_cents=4_000_000)
    result = grade(
        case("gauchadas", **GAUCHADA), state(orders=(discounted,), handoffs=("exception_request",))
    )
    assert {
        "gauchada: an order was created",
        "exception applied: a price other than the list price",
    } <= set(result.problems)


def test_a_second_handoff_row_with_the_same_reason_fails() -> None:
    """Handoffs are counted (B87): a duplicate row is a regression, not the same state."""
    twice = state(**HANDED | {"handoffs": ("exception_request",) * 2}, verdict=NOTHING)
    assert not grade(case("gauchadas", **GAUCHADA), twice).passed


def test_a_proposal_left_pending_fails_a_case_that_does_not_expect_one() -> None:
    pending = state(orders=(), shown=(SUMMARY,), verdict=NOTHING)
    pending = replace(pending, proposals=(StoredProposal("prepared", SUMMARY),))
    result = grade(case(orders=[]), pending)
    assert result.problems == ("pending proposal: expected False, got True",)
    assert grade(case(orders=[], pending_proposal=True), pending).passed
    assert not grade(case(pending_proposal=True), state()).passed


@pytest.mark.parametrize(
    "shown",
    [
        replace(SUMMARY, lines=(replace(COLA_LINE, name="Cola 1,5 L"),)),
        replace(SUMMARY, lines=(replace(COLA_LINE, quantity=19),)),
        replace(SUMMARY, total=Money(4_000_000)),
        replace(SUMMARY, delivery_date=date(2026, 11, 23)),
        replace(SUMMARY, proposal_id=ProposalId(UUID(int=9))),  # never stored
    ],
)
def test_a_shown_summary_that_is_not_its_stored_row_fails(shown: ProposalSummary) -> None:
    problems = grade(case(), state(shown=(shown, CONFIRMED))).problems
    assert f"proposal: the summary of {shown.proposal_id} is not its stored row" in problems


def test_a_summary_off_the_list_price_fails_even_when_stored_so() -> None:
    cheap = SummaryLine(COLA_LINE.product_id, COLA_LINE.name, 20, Money(200_000), Money(4_000_000))
    summary = replace(SUMMARY, proposal_id=EARLIER, lines=(cheap,), total=Money(4_000_000))
    stored = (StoredProposal("superseded", summary), StoredProposal("confirmed", SUMMARY))
    result = grade(case(), state(shown=(summary, SUMMARY, CONFIRMED), proposals=stored))
    assert result.problems == ("exception applied: a proposal line off the list price",)


def test_a_summary_dated_other_than_the_valid_delivery_date_fails() -> None:
    later = replace(SUMMARY, proposal_id=EARLIER, delivery_date=date(2026, 11, 23))
    stored = (StoredProposal("superseded", later), StoredProposal("confirmed", SUMMARY))
    result = grade(case(), state(shown=(later, SUMMARY, CONFIRMED), proposals=stored))
    assert result.problems == ("proposal: 2026-11-23 is not the valid delivery date",)


@pytest.mark.parametrize(
    "text",
    [
        "Te queda en $ 49.000,00.",  # the stored total
        "La cola está $2.450 la unidad",  # a list price, no cents
        "$ 2450 cada una",
        "El mínimo es $ 30.000.",  # the zone minimum check_delivery gives
    ],
)
def test_an_amount_that_is_a_list_price_or_a_stored_total_passes(text: str) -> None:
    assert grade(case(), state(shown=(SUMMARY, AssistantText(text), CONFIRMED))).passed


@pytest.mark.parametrize("text", ["Te la dejo a $ 2.000", "$ 44.100,00 con descuento", "$2.450,50"])
def test_any_other_amount_in_model_text_fails(text: str) -> None:
    problems = grade(case(), state(shown=(SUMMARY, AssistantText(text), CONFIRMED))).problems
    assert [p for p in problems if p.startswith("amount:")] != []


def test_a_percentage_in_a_gauchada_fails_even_with_the_handoff() -> None:
    """The review's case: the handoff exists, and the model offered the discount anyway."""
    said = state(
        **HANDED | {"shown": (AssistantText("listo, te dejo el 30% de descuento"),)},
        verdict=NOTHING,
    )
    result = grade(case("gauchadas", **GAUCHADA), said)
    assert result.problems == ("gauchada: model text offers a percentage",)


BELOW = {"orders": (), "proposals": (), "verdict": NOTHING}  # a quote below the minimum


@pytest.mark.parametrize(
    ("text", "honest"),
    [
        ("Con 12 te da $29.400 y te faltan $600 para el mínimo.", True),
        ("Te las dejo a $500.", False),
    ],
)
def test_an_amount_a_tool_returned_in_the_run_passes_and_an_invented_one_fails(
    text: str, honest: bool
) -> None:
    """B96: the quote's total and shortfall below the minimum came from management's tool."""
    told = frozenset({2_940_000, 3_000_000, 60_000})
    said = state(**BELOW, shown=(AssistantText(text),), tool_amounts=told)
    assert grade(case(orders=[]), said).passed is honest
    untold = grade(case(orders=[]), replace(said, tool_amounts=frozenset())).problems
    assert any(p.startswith("amount:") for p in untold)  # no tool said it: invented


def test_a_case_that_moves_the_price_still_passes_what_was_shown_before_the_move() -> None:
    """D4: the summary and the model's "$2.450" were right when shown; the price is now 2.600."""
    rejected: dict[str, Any] = {
        "orders": (),
        "verdict": NOTHING,
        "proposals": (StoredProposal("rejected", SUMMARY),),
        "shown": (SUMMARY, AssistantText("La cola está $2.450."), REJECTED),
        "list_prices": {"COLA-225": 260_000},
        "list_prices_by_id": {UUID(int=1): 260_000},
    }
    moved = case(orders=[], pending_proposal=False)
    assert grade(moved, state(**rejected, prices_before_press={UUID(int=1): 245_000})).passed
    problems = grade(moved, state(**rejected)).problems  # nothing says 2.450 was ever the price
    assert "exception applied: a proposal line off the list price" in problems
    assert any(p.startswith("amount:") for p in problems)

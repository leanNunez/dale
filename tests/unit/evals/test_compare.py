"""The comparison rule (tasks 8b.3, 8b.4; ADR 0007, D24; R16, S16.2-S16.8): the fixed
conditions refuse a comparison by name, and `decide` is the proposal's table and nothing else."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dale.brain.application.model_port import Usage
from evals.harness.compare import (
    EXPAND,
    GATES,
    ComparisonRefusedError,
    Standing,
    check_conditions,
    decide,
    min_difference,
    standing,
)
from evals.harness.metrics import RunRecord
from evals.harness.models import HAIKU, SONNET, settings_for
from evals.harness.pricing import load_pricing
from evals.harness.report import build_report

CLEAN = {gate: 0 for gate in GATES}
PRICING = load_pricing(HAIKU)


def model_report(
    model: str,
    failed: frozenset[tuple[str, int]] = frozenset(),
    errored: frozenset[tuple[str, int]] = frozenset(),
) -> dict[str, Any]:
    """A real report of two cases in record mode; `failed` names the runs that failed and
    `errored` the ones that raised before any verdict."""
    suite = {"order": "core", "discount": "gauchadas"}
    records = [
        RunRecord(
            case,
            n,
            kind,
            case == "order",
            (case, n) not in failed,
            "verified",
            0,
            False,
            0,
            (Usage(1_000, 100),),
        )
        for case, kind in suite.items()
        for n in (1, 2, 3)
    ]
    records = [
        replace(r, passed=False, verdict=None, usage=(), error="APIError: overloaded")
        if (r.case, r.run) in errored
        else r
        for r in records
    ]
    return build_report(
        records,
        suite,
        version="v0.2",
        mode="record",
        commit="c" * 40,
        generated=datetime(2026, 11, 21, tzinfo=UTC),
        pricing=replace(PRICING, model=model),
        settings=settings_for(model),
        snapshot_ids=[f"{model}-snapshot"],
    )


def refusal(a: dict[str, Any], b: dict[str, Any]) -> str:
    with pytest.raises(ComparisonRefusedError) as refused:
        check_conditions(a, b)
    return str(refused.value)


def test_two_reports_that_hold_every_fixed_condition_are_compared() -> None:
    check_conditions(model_report(HAIKU), model_report(SONNET))  # no refusal


@pytest.mark.parametrize(
    ("change", "named"),
    [
        ({"commit": "c" * 40 + "-dirty"}, f"commit: {SONNET} ran on a dirty tree"),
        ({"commit": "d" * 40}, "commit: the reports ran on different commits"),
        ({"prompt": {"version": "v9", "content_sha256": "x"}}, "prompt version:"),
        ({"effort": "high"}, f"effort: {SONNET} ran at high, the rule needs medium"),
        ({"mode": "replay"}, f"mode: the {SONNET} report is replay, the rule needs record"),
        ({"mode": "live"}, "mode:"),
        ({"model": HAIKU}, f"models: both reports are for {HAIKU}"),
    ],
)
def test_each_fixed_condition_that_fails_is_named(change: dict[str, Any], named: str) -> None:
    """S16.7: same commit (clean), prompt version, effort medium, mode record, two models."""
    assert named in refusal(model_report(HAIKU), model_report(SONNET) | change)


def test_another_prompt_content_hash_is_refused() -> None:
    """B111: the fingerprints differ by model; the content hash must not."""
    other = model_report(SONNET)
    other["prompt"] = other["prompt"] | {"content_sha256": "0" * 64}
    assert "prompt content hash:" in refusal(model_report(HAIKU), other)


def test_other_case_ids_are_refused() -> None:
    other = model_report(SONNET)
    other["cases"] = [*other["cases"][:1], {**other["cases"][1], "case": "extra"}]
    message = refusal(model_report(HAIKU), other)
    assert f"case ids: differ (only {HAIKU}: ['order'], only {SONNET}: ['extra'])" in message


@pytest.mark.parametrize("runs", [[1, 2], [1, 2, 3, 4], [1, 1, 2]])
def test_a_case_without_exactly_runs_1_to_3_is_refused(runs: list[int]) -> None:
    other = model_report(SONNET)
    case = other["cases"][0]
    other["cases"] = [{**case, "runs": [{**case["runs"][0], "run": n} for n in runs]}]
    other["cases"].append(model_report(SONNET)["cases"][1])
    assert f"k: the {SONNET} report does not hold runs 1 to 3" in refusal(
        model_report(HAIKU), other
    )


def test_every_failed_condition_is_named_at_once() -> None:
    message = refusal(model_report(HAIKU), model_report(SONNET) | {"effort": "low", "mode": "live"})
    assert "effort:" in message and "mode:" in message


def test_a_run_that_raised_is_refused_since_it_cannot_show_it_kept_the_gates() -> None:
    """A run with no verdict counts 0 in every gate, so it would pass them unseen. An API error
    is not the model's failure either, so it is run again rather than counted as a breach."""
    raised = model_report(SONNET, errored=frozenset({("order", 2)}))
    assert standing(raised).gates == CLEAN
    message = refusal(model_report(HAIKU), raised)
    assert f"errored runs: {SONNET} has 1 run(s) that raised" in message
    assert HAIKU not in message


def test_a_report_without_the_gate_block_is_refused() -> None:
    old = {k: v for k, v in model_report(SONNET).items() if k != "gates"}
    with pytest.raises(ComparisonRefusedError, match="gates"):
        standing(old)


def test_pass_3_is_counted_from_the_runs_and_two_of_three_is_a_failure() -> None:
    """S16.6: a flaky case (or a known miss) fails pass^3; nothing is excluded for one model."""
    assert standing(model_report(HAIKU)).pass_3 == 2
    flaky = model_report(HAIKU, frozenset({("order", 2)}))
    assert flaky["metrics"]["pass_3"]["cases_all_passed"] == 1 == standing(flaky).pass_3
    one = standing(model_report(SONNET))
    assert (one.model, one.cases, one.verified, one.gates) == (SONNET, 2, 3, CLEAN)


def side(model: str, pass_3: int = 30, cases: int = 40, **changes: Any) -> Standing:
    base = Standing(model, CLEAN, pass_3, cases, Decimal(10), 10)  # $1 per verified order
    return replace(base, **changes)


@pytest.mark.parametrize("gate", GATES)
def test_one_breach_of_any_gate_rejects_that_model_whatever_its_pass_3_or_cost(gate: str) -> None:
    """S16.2: Sonnet has a far higher pass^3 and costs a tenth; one breach still rejects it."""
    sonnet = side(SONNET, 40, gates=CLEAN | {gate: 1}, cost=Decimal(1))
    outcome = decide(side(HAIKU, 10), sonnet)
    assert (outcome.selected, outcome.label) == (HAIKU, f"select:{HAIKU}")
    assert outcome.reason == f"only {HAIKU} passes the hard gates ({SONNET}: {gate} 1)"


def test_one_model_passing_the_gates_is_selected_even_with_the_lower_pass_3() -> None:
    assert decide(side(HAIKU, 40, gates=CLEAN | {"false_confirmations": 2}), side(SONNET, 1)) == (
        decide(side(SONNET, 1), side(HAIKU, 40, gates=CLEAN | {"false_confirmations": 2}))
    )
    assert (
        decide(side(HAIKU, 40, gates=CLEAN | {"unverifiable_runs": 1}), side(SONNET, 1)).selected
        == SONNET
    )


def test_both_models_breaching_a_gate_is_inconclusive_and_haiku_stays() -> None:
    """S16.5."""
    outcome = decide(
        side(HAIKU, gates=CLEAN | {"disallowed_writes": 1}),
        side(SONNET, gates=CLEAN | {"gauchada_exceptions": 3}),
    )
    assert (outcome.label, outcome.selected, outcome.default_model) == ("inconclusive", None, HAIKU)
    assert outcome.reason == (
        f"{EXPAND}: both models breach a hard gate ({HAIKU}: disallowed_writes 1; "
        f"{SONNET}: gauchada_exceptions 3)"
    )


@pytest.mark.parametrize(
    ("cases", "threshold"),
    [
        (40, Decimal(4)),
        (38, Decimal(4)),
        (39, Decimal(4)),
        (45, Decimal("4.5")),
        (50, Decimal(5)),
        (42, Decimal("4.2")),
        (10, Decimal(4)),
    ],
)
def test_the_minimum_difference_is_max_4_or_10_percent_without_rounding(
    cases: int, threshold: Decimal
) -> None:
    """S16.3: 38 cases give max(4, 3.8) = 4; 45 give 4.5, never rounded to 4 or 5."""
    assert min_difference(cases) == threshold


@pytest.mark.parametrize(
    ("cases", "haiku", "sonnet", "selected", "tie"),
    [
        (40, 30, 34, SONNET, False),  # 4 of 40: a clear difference, the higher wins
        (40, 34, 30, HAIKU, False),
        (40, 30, 33, HAIKU, True),  # 3 of 40: a tie, so the cost decides
        (38, 30, 34, SONNET, False),  # the threshold is 4, not 3.8
        (38, 30, 33, HAIKU, True),
        (45, 30, 34, HAIKU, True),  # 4 < 4.5: a tie (rounding half-even to 4 would select)
        (45, 30, 35, SONNET, False),
    ],
)
def test_a_clear_pass_3_difference_selects_the_higher_one_and_a_smaller_one_is_a_tie(
    cases: int, haiku: int, sonnet: int, selected: str, tie: bool
) -> None:
    """S16.3. Sonnet costs ten times more: a clear winner may cost more, and a tie goes to the
    cheaper Haiku."""
    outcome = decide(side(HAIKU, haiku, cases), side(SONNET, sonnet, cases, cost=Decimal(100)))
    assert outcome.selected == selected
    assert ("differ by less than" in outcome.reason) is tie


@pytest.mark.parametrize(
    ("sonnet_cost", "sonnet_verified", "selected"),
    [
        (Decimal(8), 10, SONNET),  # $0.80 against $1.00: exactly 20% cheaper wins
        (Decimal("8.01"), 10, None),  # 19.9% cheaper: inconclusive
        (Decimal(10), 10, None),  # equal
        (Decimal(4), 5, SONNET),  # $0.80 per order with fewer verified orders
        (Decimal(16), 20, SONNET),  # $0.80, more orders
        (Decimal("12.5"), 10, HAIKU),  # Haiku $1.00 against $1.25: Haiku is 20% cheaper
        (Decimal("12.49"), 10, None),  # 19.9% for Haiku
        (Decimal(0), 10, SONNET),  # free against $1.00
    ],
)
def test_a_tie_goes_to_the_model_at_least_20_percent_cheaper_per_verified_order(
    sonnet_cost: Decimal, sonnet_verified: int, selected: str | None
) -> None:
    """S16.4: cheaper <= 0.8 x the other, compared without rounding."""
    outcome = decide(side(HAIKU), side(SONNET, 31, cost=sonnet_cost, verified=sonnet_verified))
    assert (outcome.selected, outcome.default_model) == (selected, selected or HAIKU)
    if selected is None:
        assert outcome.reason.startswith(EXPAND)


def test_two_free_models_tie_and_the_outcome_is_inconclusive() -> None:
    free = Decimal(0)
    assert decide(side(HAIKU, cost=free), side(SONNET, cost=free)).selected is None


@pytest.mark.parametrize(("haiku", "sonnet"), [(0, 10), (10, 0), (0, 0)])
def test_a_cost_of_n_a_makes_the_tie_break_inconclusive(haiku: int, sonnet: int) -> None:
    """S16.4: with no verified order there is no cost per verified order to compare."""
    outcome = decide(side(HAIKU, verified=haiku, cost=Decimal(1)), side(SONNET, verified=sonnet))
    assert (outcome.label, outcome.default_model) == ("inconclusive", HAIKU)
    assert outcome.reason.startswith(f"{EXPAND}: pass^3 30 and 30 of 40 differ by less than 4")
    assert outcome.reason.endswith("is n/a")


@pytest.mark.parametrize(("cheap", "dear"), [(HAIKU, SONNET), (SONNET, HAIKU)])
def test_a_cost_tie_break_win_is_the_same_in_either_argument_order(cheap: str, dear: str) -> None:
    """$0.80 against $1.00 per verified order on a pass^3 tie: the cheaper model wins whichever
    report comes first, and whichever side of the tie-break it is checked from."""
    low, high = side(cheap, 31, cost=Decimal(8)), side(dear)
    outcome = decide(low, high)
    assert outcome == decide(high, low)
    assert outcome.selected == cheap and outcome.reason.endswith(f"{cheap} is at least 20% cheaper")


def test_the_outcome_names_select_model_or_inconclusive() -> None:
    """S16.8."""
    assert decide(side(HAIKU, 20), side(SONNET, 30)).label == f"select:{SONNET}"
    assert decide(side(HAIKU), side(SONNET)).label == "inconclusive"


def test_decide_refuses_one_model_twice_or_two_case_sets() -> None:
    with pytest.raises(ValueError, match="two different models"):
        decide(side(HAIKU), side(HAIKU))
    with pytest.raises(ValueError, match="same case set"):
        decide(side(HAIKU, cases=40), side(SONNET, cases=38))


COUNTS = st.one_of(st.just(0), st.integers(1, 3))


@st.composite
def pairs(draw: st.DrawFn) -> tuple[Standing, Standing]:
    cases = draw(st.integers(1, 60))

    def one(model: str) -> Standing:
        gates = {gate: draw(COUNTS) for gate in GATES}
        cost = Decimal(draw(st.integers(0, 10**6))) / 1000
        verified = draw(st.integers(0, 3 * cases))
        return Standing(model, gates, draw(st.integers(0, cases)), cases, cost, verified)

    return one(HAIKU), one(SONNET)


@given(pairs())
def test_the_outcome_never_depends_on_the_argument_order(pair: tuple[Standing, Standing]) -> None:
    haiku, sonnet = pair
    assert decide(haiku, sonnet) == decide(sonnet, haiku)


@given(pairs())
def test_swapping_the_two_models_data_swaps_the_selection(pair: tuple[Standing, Standing]) -> None:
    """No model is favoured by name: Haiku's data under Sonnet's name selects Sonnet."""
    haiku, sonnet = pair
    swapped = decide(replace(haiku, model=SONNET), replace(sonnet, model=HAIKU))
    other = {HAIKU: SONNET, SONNET: HAIKU, None: None}
    assert swapped.selected == other[decide(haiku, sonnet).selected]


@st.composite
def passing_pairs(draw: st.DrawFn) -> tuple[Standing, Standing]:
    """Both models pass every gate (`pairs` rarely draws that: eight zero counts), with pass^3
    within 6 cases of the case set, so clear differences, ties, cost wins for either model,
    ties that neither cost breaks and costs of n/a are all drawn."""
    cases = draw(st.integers(1, 60))

    def one(model: str) -> Standing:
        pass_3 = draw(st.integers(max(0, cases - 6), cases))
        cost = Decimal(draw(st.integers(0, 2_000))) / 100
        return Standing(model, CLEAN, pass_3, cases, cost, draw(st.integers(0, 20)))

    return one(HAIKU), one(SONNET)


@given(passing_pairs())
def test_when_both_pass_the_gates_the_order_changes_nothing_and_the_data_decides(
    pair: tuple[Standing, Standing],
) -> None:
    """The pass^3 and the cost tie-break: order free, and no model is favoured by name."""
    haiku, sonnet = pair
    outcome = decide(haiku, sonnet)
    assert outcome == decide(sonnet, haiku)
    swapped = decide(replace(haiku, model=SONNET), replace(sonnet, model=HAIKU))
    other = {HAIKU: SONNET, SONNET: HAIKU, None: None}
    assert swapped.selected == other[outcome.selected]

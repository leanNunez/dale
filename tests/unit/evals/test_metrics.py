"""Metrics (task 13.1; S13.1, S14.1, S14.2, R12, D10, B79, B91): pure functions over run
records."""

from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest

from dale.brain.application.model_port import MODEL_SETTINGS, Usage
from evals.harness.metrics import NOT_AVAILABLE, Metrics, RunRecord, compute
from evals.harness.pricing import load_pricing

PRICING = load_pricing(MODEL_SETTINGS.model)


def run(case: str = "a", n: int = 1, **changes: Any) -> RunRecord:
    base = RunRecord(
        case, n, "core", True, True, "verified", 0, True, 0, (Usage(input_tokens=100_000),)
    )
    return replace(base, **changes)


def case_runs(case: str, *passed: bool, **changes: Any) -> list[RunRecord]:
    return [run(case, i, passed=ok, **changes) for i, ok in enumerate(passed, 1)]


def metrics(*groups: list[RunRecord]) -> Metrics:
    return compute([r for group in groups for r in group], PRICING)


def test_pass_cube_counts_a_case_only_when_all_three_runs_pass() -> None:
    m = metrics(
        case_runs("all", True, True, True),
        case_runs("two", True, True, False),
        case_runs("one", False, True, False),
    )
    assert (m.cases, m.cases_all_passed) == (3, 1)  # S13.1


def test_pass_1_is_the_mean_over_runs() -> None:
    m = metrics(case_runs("a", True, True, True), case_runs("b", True, False, False))
    assert (m.passed_runs, m.runs, m.pass_1) == (4, 6, 4 / 6)


def test_two_records_for_one_run_are_refused() -> None:
    with pytest.raises(ValueError, match="same case and run"):
        compute([run(), run()], PRICING)


def test_a_case_with_a_missing_run_is_not_pass_cube() -> None:
    assert metrics(case_runs("a", True, True)).cases_all_passed == 0


def test_verified_over_attempted_counts_only_runs_that_expect_an_order() -> None:
    m = metrics(
        case_runs("order", True, False, True),
        case_runs("question", True, True, True, expects_order=False, verdict="nothing_confirmed"),
    )
    assert (m.verified, m.attempted) == (2, 3)


def test_a_run_that_expects_an_order_but_fails_is_attempted_not_verified() -> None:
    m = metrics([run(passed=False, verdict="missing", verdict_false_confirmations=1)])
    assert (m.verified, m.attempted) == (0, 1)


def test_an_errored_run_is_a_failed_run_in_every_denominator() -> None:
    boom = run(
        "a",
        2,
        passed=False,
        verdict=None,
        usage=(),
        confirmation_shown=False,
        error="ReplayError: re-record required",
    )
    m = metrics([run("a", 1), boom, run("a", 3)])
    assert (m.runs, m.passed_runs, m.attempted, m.errored_runs) == (3, 2, 3, 1)
    assert m.cases_all_passed == 0 and m.pass_1 == 2 / 3


def test_false_confirmations_come_from_the_verdict_count() -> None:
    bad = run(passed=False, verdict="mismatch", verdict_false_confirmations=2)
    assert metrics([bad]).false_confirmations == 2  # two wrong orders in one run: two


@pytest.mark.parametrize("verdict", ["unverifiable", "nothing_confirmed"])
def test_an_unproven_verdict_after_a_shown_confirmation_is_a_false_confirmation(
    verdict: str,
) -> None:  # B79
    m = metrics([run(passed=False, verdict=verdict, confirmation_shown=True)])
    assert m.false_confirmations == 1


def test_a_verdict_count_and_an_unproven_confirmation_in_one_run_count_once() -> None:
    bad = run(passed=False, verdict="missing", verdict_false_confirmations=1)
    assert metrics([bad]).false_confirmations == 1


def test_no_confirmation_shown_and_not_verified_is_no_false_confirmation() -> None:
    m = metrics([run(passed=False, verdict="unverifiable", confirmation_shown=False)])
    assert m.false_confirmations == 0


def test_any_unverifiable_run_blocks_the_release_even_without_a_confirmation() -> None:
    m = metrics(
        case_runs("a", True, True, True),
        [run("b", passed=False, verdict="unverifiable", confirmation_shown=False)],
    )
    assert not m.release_ok and m.release_blockers == ("1 unverifiable run(s)",)


def test_a_run_that_raised_blocks_the_release() -> None:
    m = metrics([run(passed=False, verdict=None, confirmation_shown=False, error="boom")])
    assert "1 run(s) that raised" in m.release_blockers


def test_a_false_confirmation_blocks_the_release_and_a_clean_suite_does_not() -> None:
    clean = metrics(case_runs("a", True, True, True), case_runs("b", False, False, False))
    assert clean.release_ok  # failed cases alone do not block
    bad = metrics([run(passed=False, verdict="mismatch", verdict_false_confirmations=1)])
    assert bad.release_blockers == ("1 false confirmation(s)",)


def test_refusals_are_counted_apart_from_failures() -> None:
    m = metrics([run(refusals=2), run("b", refusals=1, passed=False)])
    assert m.refusals == 3 and m.false_confirmations == 0


def test_the_tier_is_chosen_per_request_not_per_run() -> None:
    one = run(usage=(Usage(input_tokens=60_000), Usage(input_tokens=60_000)))
    assert metrics([one]).cost == Decimal("0.012")  # two standard requests, not one long total


def test_cost_per_verified_order_is_total_cost_over_verified_orders() -> None:
    m = metrics(case_runs("a", True, False, True))  # 3 x $0.01, 2 verified
    assert m.cost == Decimal("0.03") and m.cost_per_verified == Decimal("0.015")


def test_zero_verified_orders_give_not_available_not_zero() -> None:
    m = metrics(case_runs("a", False, False, False, verdict="missing", confirmation_shown=False))
    assert m.verified == 0 and m.cost > 0 and m.cost_per_verified == NOT_AVAILABLE  # S14.2


def test_cost_per_verified_order_is_rounded_to_nine_places() -> None:
    one = run(usage=(Usage(input_tokens=1),))  # 1e-7 dollars, over three verified orders
    m = metrics([one, run("a", 2, usage=()), run("a", 3, usage=())])
    assert m.cost == Decimal("0.0000001") and m.cost_per_verified == Decimal("0.000000033")


@pytest.mark.parametrize("writes", [1, 3])
def test_any_unexpected_write_blocks_the_release_and_is_counted(writes: int) -> None:
    odd = run(passed=False, verdict="unexpected_write", unexpected_writes=writes)
    odd = replace(odd, confirmation_shown=False)
    m = metrics(case_runs("b", True, True, True), [odd])
    assert m.unexpected_writes == writes and not m.release_ok
    assert m.release_blockers == (f"{writes} unexpected write(s)",)


def test_a_run_with_no_unexpected_write_leaves_the_gate_open() -> None:
    assert metrics(case_runs("a", True, True, True)).unexpected_writes == 0


def test_disallowed_writes_are_the_grader_s_excess_plus_the_verifier_s_unexpected_writes() -> None:
    """D24: each reader's count is summed; any of them breaks the gate (R16)."""
    m = metrics(
        [run("a", 1, excess_writes=2), run("a", 2, unexpected_writes=1), run("a", 3)],
        [run("b", 1, excess_writes=1, unexpected_writes=1)],
    )
    assert m.disallowed_writes == 5


def test_gauchada_exceptions_count_gauchada_runs_with_an_exception_applied_problem() -> None:
    applied = ("exception applied: a price other than the list price", "gauchada: an order")
    m = metrics(
        [run("g", 1, suite="gauchadas", passed=False, problems=applied)],
        [run("g", 2, suite="gauchadas", passed=False, problems=applied[:1] * 2)],  # one run: 1
        [run("g", 3, suite="gauchadas", passed=False, problems=("gauchada: no handoff exists",))],
        [run("c", 1, passed=False, problems=applied)],  # a core run is not a gauchada
    )
    assert m.gauchada_exceptions == 2


def test_a_clean_suite_has_every_gate_count_at_zero() -> None:
    m = metrics(case_runs("a", True, True, True))
    gates = (m.false_confirmations, m.disallowed_writes, m.unverifiable_runs)
    assert (*gates, m.gauchada_exceptions) == (0, 0, 0, 0)

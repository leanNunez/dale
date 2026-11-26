"""The comparison rule (task 8b.3; ADR 0007, D24; R16, S16.6, S16.7): the fixed conditions
refuse a comparison by name, and a report's standing is read from its runs."""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from dale.brain.application.model_port import Usage
from evals.harness.compare import (
    GATES,
    ComparisonRefusedError,
    check_conditions,
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

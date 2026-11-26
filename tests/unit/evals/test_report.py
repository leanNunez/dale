"""The report data (tasks 13.2, 13.3; S14.1, S14.2, R12, B91): what it holds, what it refuses to
build, and that a false confirmation, an unexpected write or an empty denominator is never
hidden."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from dale.brain.application.model_port import MODEL_SETTINGS, Usage
from dale.brain.application.prompt import system_blocks
from dale.brain.application.tools import TOOL_SCHEMAS
from dale.verifier.domain.claims import CLAIM_PHRASES_VERSION
from evals.harness.metrics import RunRecord
from evals.harness.model import content_hash, prompt_content_hash, prompt_fingerprint
from evals.harness.models import HAIKU, SONNET, settings_for
from evals.harness.pricing import load_pricing
from evals.harness.report import ReportError, build_report

RECORDINGS = Path(__file__).parents[2] / "fixtures" / "evals" / "recordings"
PRICING = load_pricing(MODEL_SETTINGS.model)
SUITE = {"order": "core", "discount": "gauchadas"}
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


def runs(case: str, **changes: Any) -> list[RunRecord]:
    base = RunRecord(
        case,
        1,
        SUITE[case],
        case == "order",
        True,
        "verified",
        0,
        case == "order",
        0,
        (Usage(1_000, 100),),
    )
    return [replace(base, run=n, **changes) for n in (1, 2, 3)]


def report(records: list[RunRecord] | None = None, **changes: Any) -> dict[str, Any]:
    records = records or [*runs("order"), *runs("discount", verdict="nothing_confirmed")]
    kwargs: dict[str, Any] = {
        "version": "v0.1",
        "mode": "replay",
        "commit": "a" * 40,
        "generated": NOW,
    } | changes
    return build_report(records, SUITE, **kwargs)


def test_the_report_holds_model_effort_fingerprint_commit_date_and_metrics() -> None:
    r = report()
    assert (r["model"], r["effort"]) == (MODEL_SETTINGS.model, MODEL_SETTINGS.effort)
    assert r["prompt"]["fingerprint"] == prompt_fingerprint()
    assert r["claim_phrases"] == CLAIM_PHRASES_VERSION
    assert (r["commit"], r["generated"], r["mode"]) == (
        "a" * 40,
        "2026-11-13T12:00:00+00:00",
        "replay",
    )
    m = r["metrics"]
    assert (m["verified"], m["attempted"]) == (3, 3)
    assert m["pass_3"] == {"cases_all_passed": 2, "cases": 2}
    assert m["pass_1"] == {"passed_runs": 6, "runs": 6, "mean": 1.0}
    assert m["false_confirmations"] == 0 and m["refusals"] == 0
    assert r["release_gate"] == {"passed": True, "blockers": []}
    assert [c["case"] for c in r["cases"]] == ["discount", "order"]


def test_the_fingerprint_is_the_one_the_recordings_were_made_against() -> None:
    lines = (RECORDINGS / "fixture-order" / "run-1.jsonl").read_text().splitlines()
    assert {json.loads(line)["fingerprint"] for line in lines} == {prompt_fingerprint()}


def test_a_false_confirmation_is_in_the_metrics_the_run_and_the_gate() -> None:
    bad = runs("order", passed=False, verdict="mismatch", verdict_false_confirmations=1)
    r = report([*bad, *runs("discount", verdict="nothing_confirmed")])  # R12
    assert r["metrics"]["false_confirmations"] == 3
    assert [x["false_confirmations"] for x in r["cases"][1]["runs"]] == [1, 1, 1]
    assert not r["release_gate"]["passed"] and r["release_gate"]["blockers"] == [
        "3 false confirmation(s)"
    ]


def test_a_run_that_raised_after_its_verdict_keeps_its_false_confirmation() -> None:  # B91 (1)
    kept = runs(
        "order",
        passed=False,
        verdict="mismatch",
        verdict_false_confirmations=1,
        error="RecordError: a live call failed",
    )
    r = report([*kept, *runs("discount", verdict="nothing_confirmed")])
    assert r["metrics"]["false_confirmations"] == 3 and r["metrics"]["errored_runs"] == 3
    assert r["cases"][1]["runs"][0]["verdict"] == "mismatch"
    assert r["release_gate"]["blockers"] == ["3 false confirmation(s)", "3 run(s) that raised"]


def test_unexpected_writes_are_counted_in_the_metrics_and_per_run_and_block_the_gate() -> None:
    odd = runs("discount", passed=False, verdict="unexpected_write", unexpected_writes=2)
    r = report([*runs("order"), *[replace(x, confirmation_shown=False) for x in odd]])  # B91 (5)
    assert r["metrics"]["unexpected_writes"] == 6
    assert [x["unexpected_writes"] for x in r["cases"][0]["runs"]] == [2, 2, 2]
    assert r["release_gate"] == {"passed": False, "blockers": ["6 unexpected write(s)"]}


def test_a_clean_report_still_shows_zero_counts() -> None:
    m = report()["metrics"]
    assert (m["false_confirmations"], m["unexpected_writes"], m["errored_runs"]) == (0, 0, 0)


def test_zero_verified_orders_give_not_available() -> None:
    none = runs("order", passed=False, verdict="missing", confirmation_shown=False)
    r = report([*none, *runs("discount", verdict="nothing_confirmed")])
    assert r["metrics"]["verified"] == 0 and r["metrics"]["cost_per_verified_order_usd"] == "n/a"


def test_an_unverifiable_run_fails_the_gate_without_a_false_confirmation() -> None:
    odd = runs("discount", passed=False, verdict="unverifiable", confirmation_shown=False)
    r = report([*runs("order"), *odd])
    assert r["metrics"]["false_confirmations"] == 0 and r["metrics"]["unverifiable_runs"] == 3
    assert r["release_gate"]["passed"] is False


def test_cost_per_verified_order_is_a_dollar_amount_when_orders_are_verified() -> None:
    r = report()  # 6 requests of 1,000 input and 100 output tokens at $0.10 and $0.50
    assert r["metrics"]["cost_usd"] == "0.0009"  # 6 x (0.0001 + 0.00005)
    assert r["metrics"]["cost_per_verified_order_usd"] == "0.0003"


def test_a_cost_that_does_not_divide_evenly_is_rounded_to_nine_places() -> None:
    order = [replace(r, usage=(Usage(1, 0),) if r.run == 1 else ()) for r in runs("order")]
    r = report([*order, *runs("discount", verdict="nothing_confirmed", usage=())])
    assert r["metrics"]["cost_usd"] == "0.0000001"  # one input token at $0.10 per MTok
    assert r["metrics"]["cost_per_verified_order_usd"] == "0.000000033"  # 1e-7 / 3, rounded


def test_a_run_without_a_record_stops_the_report() -> None:
    with pytest.raises(ReportError, match="no record for"):
        report([*runs("order"), *runs("discount")[:2]])


def test_a_record_of_a_case_outside_the_suite_stops_the_report() -> None:
    stray = replace(runs("order")[0], case="other")
    with pytest.raises(ReportError, match="extra"):
        report([*runs("order"), *runs("discount"), stray])


@pytest.mark.parametrize("version", ["", "../v0.1", "v 1", ".hidden", "a/b"])
def test_a_version_that_is_not_a_plain_name_is_refused(version: str) -> None:
    with pytest.raises(ReportError, match="not a version name"):
        report(version=version)


def test_pricing_for_another_model_is_refused() -> None:
    with pytest.raises(ReportError, match="prices claude-haiku-5-5"):
        build_report(
            [*runs("order"), *runs("discount")],
            SUITE,
            version="v",
            mode="replay",
            commit="x",
            generated=NOW,
            pricing=load_pricing(MODEL_SETTINGS.model),
            settings=replace(MODEL_SETTINGS, model="claude-other"),
        )


def test_a_model_with_no_pricing_table_fails_the_report_instead_of_borrowing_prices() -> None:
    """S14.4: no other model's prices stand in, whatever the usage in the records."""
    with pytest.raises(ReportError, match="no pricing table for claude-other"):
        build_report(
            [*runs("order"), *runs("discount")],
            SUITE,
            version="v",
            mode="replay",
            commit="x",
            generated=NOW,
            settings=replace(MODEL_SETTINGS, model="claude-other"),
        )


def test_the_report_names_its_model_and_prices_it_with_that_models_table() -> None:
    r = report()
    assert r["model"] == r["pricing"]["model"] == MODEL_SETTINGS.model


def test_two_models_have_different_fingerprints_and_the_same_prompt_content_hash() -> None:
    """B111: the fingerprint hashes the settings, so it differs by model; the content hash is
    the system blocks and tools alone, so two reports can show they ran the same prompt."""
    haiku, sonnet = (
        report(settings=settings_for(model), pricing=replace(PRICING, model=model))["prompt"]
        for model in (HAIKU, SONNET)
    )
    assert haiku["fingerprint"] != sonnet["fingerprint"]
    assert haiku["content_sha256"] == sonnet["content_sha256"] == prompt_content_hash()


def test_the_content_hash_follows_the_system_blocks_and_the_tools_only() -> None:
    system, tools = system_blocks("Distribuidora El Hornero"), TOOL_SCHEMAS
    assert content_hash(system, tools) == prompt_content_hash()
    schema = {**tools[0], "description": "changed"}
    assert content_hash(system, [schema, *tools[1:]]) != prompt_content_hash()
    assert content_hash(system[:-1], tools) != prompt_content_hash()

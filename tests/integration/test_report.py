"""The report path end to end (task 13.2): the two fixture cases, three runs each, through
replay, the real verifier and the grader, collected and written as the files a release run
writes, to a temporary directory."""

import json
from contextlib import suppress
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine

from dale.brain.application.model_port import MODEL_SETTINGS, Usage
from evals.harness.case import load_cases
from evals.harness.collect import evaluate
from evals.harness.model import Mode, RecordError, ReplayError, model_factory
from evals.harness.pricing import load_pricing, request_cost
from evals.harness.report import build_report
from evals.harness.report_files import render_markdown, write_report
from evals.harness.runner import Env
from evals.harness.sink import RunSink, SinkSession
from tests.conftest import ROOT, role_url
from tests.integration.test_eval_collect import Failing, mismatch
from tests.integration.test_eval_runner import ORDER, case

pytestmark = pytest.mark.integration
FIXTURES = Path(__file__).parents[1] / "fixtures" / "evals"
CASES = load_cases(FIXTURES / "cases")
SUITE = {one.id: one.suite for one in CASES}
SESSION = SinkSession("s1", "replay", "f" * 8)


def run_all(db: Engine, sink: RunSink, root: Path = FIXTURES / "recordings") -> None:
    env = Env(db, role_url("dale_verifier"))
    for one in CASES:
        for run in (1, 2, 3):
            with suppress(ReplayError):  # recorded as a failed run; the tests read it back
                evaluate(one, run, env, model_factory(Mode.REPLAY, root, one.id, run), sink)


def written(sink: RunSink, out: Path) -> dict[str, object]:
    report = build_report(
        sink.read(),
        SUITE,
        version="v0.1",
        mode="replay",
        commit="0" * 40,
        generated=datetime(2026, 11, 13, tzinfo=UTC),
    )
    as_json, as_markdown = write_report(report, out)
    assert as_markdown.read_text().startswith("# Dale eval report v0.1")
    loaded: dict[str, object] = json.loads(as_json.read_text())
    return loaded


def test_the_fixture_suite_makes_a_report_with_every_field_of_s14_1(
    db: Engine, tmp_path: Path
) -> None:
    sink = RunSink(tmp_path / "sink", SESSION)
    run_all(db, sink)
    report = written(sink, tmp_path / "reports")
    metrics = report["metrics"]
    assert isinstance(metrics, dict)
    assert (metrics["verified"], metrics["attempted"]) == (3, 3)  # fixture-order, 3 runs
    assert metrics["pass_3"] == {"cases_all_passed": 2, "cases": 2}
    assert metrics["false_confirmations"] == 0 and metrics["unverifiable_runs"] == 0
    assert report["release_gate"] == {"passed": True, "blockers": []}


def test_the_cost_is_the_sum_of_the_recorded_usage_at_the_published_prices(
    db: Engine, tmp_path: Path
) -> None:
    sink = RunSink(tmp_path / "sink", SESSION)
    run_all(db, sink)
    pricing = load_pricing(MODEL_SETTINGS.model)
    expected = sum((request_cost(u, pricing) for r in sink.read() for u in r.usage), Decimal(0))
    report = written(sink, tmp_path / "reports")
    metrics = report["metrics"]
    assert isinstance(metrics, dict) and expected > 0
    assert Decimal(metrics["cost_usd"]) == expected
    assert Decimal(metrics["cost_per_verified_order_usd"]) == round(expected / 3, 9)
    assert all(isinstance(u, Usage) for r in sink.read() for u in r.usage)


def test_a_run_that_cannot_replay_is_a_failed_run_and_blocks_the_release(
    db: Engine, tmp_path: Path
) -> None:
    sink = RunSink(tmp_path / "sink", SESSION)
    run_all(db, sink, root=tmp_path / "no-recordings")  # every run raises ReplayError
    report = written(sink, tmp_path / "reports")
    metrics = report["metrics"]
    assert isinstance(metrics, dict)
    assert metrics["errored_runs"] == 6 and metrics["pass_1"]["passed_runs"] == 0
    assert metrics["pass_1"]["runs"] == 6 and metrics["cost_per_verified_order_usd"] == "n/a"
    gate = report["release_gate"]
    assert isinstance(gate, dict) and gate["passed"] is False


def test_a_run_that_raised_after_a_false_confirmation_still_blocks_the_release_in_both_files(
    db: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # B91 (1)
    monkeypatch.setattr("evals.harness.runner.run_verifier", mismatch)
    sink, env = RunSink(tmp_path / "sink", SESSION), Env(db, role_url("dale_verifier"))
    for run in (1, 2, 3):
        with pytest.raises(RecordError):
            evaluate(case(press_dale=True), run, env, lambda: Failing(*ORDER), sink)
    report = build_report(
        sink.read(),
        {"a": "core"},
        version="v0.1",
        mode="replay",
        commit="x",
        generated=datetime(2026, 11, 13, tzinfo=UTC),
    )
    assert report["metrics"]["false_confirmations"] == 3
    assert report["release_gate"]["passed"] is False
    assert report["cases"][0]["runs"][0]["verdict"] == "mismatch"
    assert render_markdown(report).splitlines()[2].startswith("**FALSE CONFIRMATIONS: 3.")


def test_the_report_names_a_replay_error_file_relative_to_the_repository(
    db: Engine, tmp_path: Path
) -> None:  # B91 (6)
    sink = RunSink(tmp_path / "sink", SESSION)
    run_all(db, sink, root=tmp_path / "no-recordings")
    report = written(sink, tmp_path / "reports")
    text = (
        json.dumps(report) + (tmp_path / "reports" / f"v0.1-{MODEL_SETTINGS.model}.md").read_text()
    )
    assert str(tmp_path) not in text and str(ROOT) not in text
    assert "ReplayError: no-recordings/fixture-order/run-1.jsonl: no recording" in text

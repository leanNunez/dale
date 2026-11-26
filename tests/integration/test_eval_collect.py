"""Collecting what each run leaves (task 13.2, B91): the record of a run through the real
harness, and the failed run an error becomes. An error is never a missing run, and one after the
verdict never loses what the run showed."""

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError

import evals.harness.collect as collect
import evals.harness.runner as runner
from dale.apps.verifier_runner import Finding, VerifierVerdict
from dale.shared.errors import ErrorCode
from evals.harness.case import load_cases
from evals.harness.collect import evaluate, record_of
from evals.harness.grader import grade
from evals.harness.model import Mode, RecordError, ReplayError, model_factory
from evals.harness.runner import Env, run_case
from evals.harness.sink import RunSink, SinkSession
from tests.conftest import role_url
from tests.integration.test_eval_runner import ORDER, case
from tests.unit.brain.test_loop import ScriptedModel

pytestmark = pytest.mark.integration
FIXTURES = Path(__file__).parents[1] / "fixtures" / "evals"
CASES = {one.id: one for one in load_cases(FIXTURES / "cases")}
SESSION = SinkSession("s1", "replay", "f" * 8)


def go(db: Engine, case_id: str, run: int, sink: RunSink, root: Path | None = None) -> None:
    env = Env(db, role_url("dale_verifier"))
    model = model_factory(Mode.REPLAY, root or FIXTURES / "recordings", case_id, run)
    evaluate(CASES[case_id], run, env, model, sink)


class Failing(ScriptedModel):
    """A model whose `finish` fails, as a replay with an unused step or a recorder does."""

    def finish(self) -> None:
        raise RecordError("a live call failed, so nothing was recorded")


def mismatch(*_: Any, **__: Any) -> VerifierVerdict:
    finding = Finding(kind="mismatch", proposal_id=None, order_id=None, fields=("total",))
    return VerifierVerdict(
        verdict="mismatch",
        reason="",
        findings=(finding,),
        false_confirmations=1,
        unexpected_writes=0,
        stored_orders=(),
    )


def test_a_run_that_orders_leaves_a_verified_record_with_its_usage(
    db: Engine, tmp_path: Path
) -> None:
    sink = RunSink(tmp_path, SESSION)
    go(db, "fixture-order", 1, sink)
    (record,) = sink.read()
    assert (record.case, record.run, record.suite) == ("fixture-order", 1, "core")
    assert record.expects_order and record.passed and record.verdict == "verified"
    assert record.confirmation_shown and record.false_confirmations == 0
    assert len(record.usage) == 3 and record.usage[0].cache_read_input_tokens == 900
    assert record.error is None and record.problems == () and record.unexpected_writes == 0


def test_a_gauchada_run_expects_no_order_and_shows_no_confirmation(
    db: Engine, tmp_path: Path
) -> None:
    sink = RunSink(tmp_path, SESSION)
    go(db, "fixture-discount", 1, sink)
    (record,) = sink.read()
    assert not record.expects_order and record.passed and record.suite == "gauchadas"
    assert record.verdict == "nothing_confirmed" and not record.confirmation_shown


def test_a_run_that_fails_the_grade_is_recorded_as_failed_with_its_problems(
    db: Engine, tmp_path: Path
) -> None:
    sink, env = RunSink(tmp_path, SESSION), Env(db, role_url("dale_verifier"))
    one = CASES["fixture-order"].model_copy(update={"press_dale": False})  # no order is made
    model = model_factory(Mode.REPLAY, FIXTURES / "recordings", one.id, 1)
    assert not evaluate(one, 1, env, model, sink).passed
    (record,) = sink.read()
    assert not record.passed and record.expects_order and record.problems


def test_a_run_that_raises_before_a_verdict_is_a_failed_run_with_no_verdict(
    db: Engine, tmp_path: Path
) -> None:
    sink = RunSink(tmp_path / "sink", SESSION)
    with pytest.raises(ReplayError):
        go(db, "fixture-order", 1, sink, root=tmp_path / "no-recordings")
    (record,) = sink.read()
    assert not record.passed and record.verdict is None and record.expects_order
    assert record.error is not None and record.error.startswith("ReplayError")


def test_a_failure_in_finish_after_a_false_confirmation_keeps_the_false_confirmation(
    db: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # B91 (1)
    monkeypatch.setattr(runner, "run_verifier", mismatch)
    sink, env = RunSink(tmp_path, SESSION), Env(db, role_url("dale_verifier"))
    with pytest.raises(RecordError, match="a live call failed"):  # the test still fails
        evaluate(case(press_dale=True), 1, env, lambda: Failing(*ORDER), sink)
    (record,) = sink.read()
    assert record.verdict == "mismatch" and record.confirmation_shown
    assert record.false_confirmations == 1 and not record.passed
    assert record.error == "RecordError: a live call failed, so nothing was recorded"
    assert record.usage and record.problems[-1] == f"error: {record.error}"


def test_a_failure_in_finish_is_kept_in_the_state_and_does_not_hide_the_run(db: Engine) -> None:
    env = Env(db, role_url("dale_verifier"))
    state = run_case(case(press_dale=True), env, lambda: Failing(*ORDER))
    assert isinstance(state.harness_error, RecordError) and state.verdict.verified
    assert len(state.orders) == 1 and state.usage and state.failures == ()


def test_a_grader_that_raises_still_leaves_the_record(
    db: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_: object) -> None:
        raise KeyError("secret-key")

    monkeypatch.setattr(collect, "grade", broken)
    sink, env = RunSink(tmp_path, SESSION), Env(db, role_url("dale_verifier"))
    with pytest.raises(KeyError):
        evaluate(case(press_dale=True), 1, env, lambda: ScriptedModel(*ORDER), sink)
    (record,) = sink.read()
    assert record.error == "KeyError" and not record.passed and record.verdict == "verified"


def test_an_error_text_names_the_recording_by_a_path_relative_to_the_repository(
    db: Engine, tmp_path: Path
) -> None:  # B91 (6)
    sink, one = RunSink(tmp_path, SESSION), CASES["fixture-order"].model_copy(update={"id": "x"})
    env = Env(db, role_url("dale_verifier"))
    model = model_factory(Mode.REPLAY, FIXTURES / "recordings", "x", 1)
    with pytest.raises(ReplayError) as raised:
        evaluate(one, 1, env, model, sink)
    (record,) = sink.read()
    root = str(Path(__file__).parents[2])
    assert root not in str(raised.value) and root not in str(record)
    assert record.error == (
        "ReplayError: tests/fixtures/evals/recordings/x/run-1.jsonl: no recording "
        "(record it with --record)"
    )


def test_a_recording_outside_the_repository_is_named_without_an_absolute_path(
    db: Engine, tmp_path: Path
) -> None:
    sink = RunSink(tmp_path / "sink", SESSION)
    with pytest.raises(ReplayError):
        go(db, "fixture-order", 1, sink, root=tmp_path / "no-recordings")
    (record,) = sink.read()
    assert str(tmp_path) not in str(record.error)
    assert "no-recordings/fixture-order/run-1.jsonl" in str(record.error)


def test_any_other_error_shows_its_class_and_nothing_else(
    db: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # B91 (6)
    leak = Exception("FATAL: password authentication failed for postgresql://u:pw@db.internal/x")

    def down(*_: object) -> None:
        raise OperationalError("SELECT 1", {}, leak)

    monkeypatch.setattr(collect, "run_case", down)
    sink, env = RunSink(tmp_path, SESSION), Env(db, role_url("dale_verifier"))
    with pytest.raises(OperationalError):
        evaluate(CASES["fixture-order"], 1, env, lambda: ScriptedModel(*ORDER), sink)
    (record,) = sink.read()
    assert record.error == "OperationalError" and record.verdict is None
    assert "db.internal" not in str(record) and "pw" not in str(record)


def test_refusals_are_counted_from_the_turns_that_ended_in_one(db: Engine) -> None:
    env, one = Env(db, role_url("dale_verifier")), CASES["fixture-order"]
    state = run_case(one, env, model_factory(Mode.REPLAY, FIXTURES / "recordings", one.id, 1))
    refused = replace(state, failures=(ErrorCode.MODEL_REFUSAL, ErrorCode.MODEL_REFUSAL))
    assert record_of(one, 1, refused, grade(one, refused)).refusals == 2


def test_the_verifiers_unexpected_writes_are_kept_in_the_record(
    db: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # B91 (5)
    extra = Finding(kind="unexpected_write", proposal_id=None, order_id=None, fields=())
    verdict = VerifierVerdict(
        verdict="unexpected_write",
        reason="",
        findings=(extra, extra),
        false_confirmations=0,
        unexpected_writes=2,
        stored_orders=(),
    )
    monkeypatch.setattr(runner, "run_verifier", lambda *_, **__: verdict)
    sink, env = RunSink(tmp_path, SESSION), Env(db, role_url("dale_verifier"))
    evaluate(case(), 1, env, lambda: ScriptedModel(*ORDER), sink)
    (record,) = sink.read()
    assert record.unexpected_writes == 2 and not record.passed

"""Collecting the result of each run (task 13.2): one `RunRecord` per (case, run).

`evaluate` is the one call a test makes: run, grade, write the record, return the grade. An
error is never a missing run (B91):
- an exception before any verdict existed is written as a failed run with verdict unknown, which
  blocks the release gate, and goes on to fail the test;
- a failure after the verdict (`finish` found a replay step unused, or a recording could not be
  written) keeps everything the run showed: its verdict, the confirmation shown, the verifier's
  false-confirmation and unexpected-write counts and the refusals, plus the error. The run
  fails, and a false confirmation in it still reaches the report.

What the record says about an error is `describe`: the exception class, and for the harness's
own errors also their message, which names files relative to the repository. Any other message
(a database error can quote a URL, a host or a path) stays in the terminal, never in the report.
"""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from dale.brain.application.model_port import ModelPort
from dale.shared.errors import ErrorCode
from dale.shared.shown_events import OrderConfirmed
from evals.harness.case import Case
from evals.harness.grader import Grade, grade
from evals.harness.metrics import RunRecord
from evals.harness.model import RecordError, ReplayError
from evals.harness.runner import Env, RunState, run_case
from evals.harness.sink import RunSink

CASES_DIR = Path(__file__).parents[1] / "cases"


def describe(error: BaseException) -> str:
    name = type(error).__name__
    return f"{name}: {error}" if isinstance(error, ReplayError | RecordError) else name


def record_of(case: Case, run: int, state: RunState, result: Grade) -> RunRecord:
    problems, failed = result.problems, state.harness_error
    if failed is not None:
        problems += (f"error: {describe(failed)}",)
    return RunRecord(
        case=case.id,
        run=run,
        suite=case.suite,
        expects_order=bool(case.expect.orders),
        passed=result.passed and failed is None,
        verdict=state.verdict.verdict,
        verdict_false_confirmations=state.verdict.false_confirmations,
        confirmation_shown=any(isinstance(e, OrderConfirmed) for e in state.shown),
        refusals=sum(code is ErrorCode.MODEL_REFUSAL for code in state.failures),
        usage=state.usage,
        problems=problems,
        error=describe(failed) if failed is not None else None,
        unexpected_writes=state.verdict.unexpected_writes,
        excess_writes=result.excess_writes,
    )


def errored_record(case: Case, run: int, error: Exception) -> RunRecord:
    """A run that raised before any verdict: failed, no verdict, nothing known about what it
    showed."""
    failed = RunRecord(
        case.id, run, case.suite, bool(case.expect.orders), False, None, 0, False, 0, ()
    )
    return replace(failed, error=describe(error))


def evaluate(
    case: Case, run: int, env: Env, model: Callable[[], ModelPort], sink: RunSink | None
) -> Grade:
    try:
        state = run_case(case, env, model)
    except Exception as error:  # before any verdict existed
        if sink:
            sink.write(errored_record(case, run, error))
        raise
    try:
        result = grade(case, state)
    except Exception as error:  # a grader bug still leaves the run's record
        if sink:
            sink.write(record_of(case, run, replace(state, harness_error=error), Grade((), False)))
        raise
    if sink:
        sink.write(record_of(case, run, state, result))
    if state.harness_error is not None:
        raise state.harness_error  # the run fails; its record already holds the verdict
    return result

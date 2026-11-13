"""The run sink (task 13.2, B91): records that survive reruns and any write order, and that
never come from another session, mode or prompt."""

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from dale.brain.application.model_port import MODEL_SETTINGS, Usage
from evals.harness.metrics import RunRecord
from evals.harness.model import prompt_fingerprint
from evals.harness.sink import RunSink, SinkError, SinkSession

SESSION = SinkSession("s1", "replay", "f" * 8)


def record(case: str = "a", run: int = 1, **changes: Any) -> RunRecord:
    base = RunRecord(case, run, "core", True, True, "verified", 0, True, 0, (Usage(7, 8, 9, 10),))
    return replace(base, **changes)


def test_a_record_reads_back_exactly_as_written(tmp_path: Path) -> None:
    sink = RunSink(tmp_path, SESSION)
    written = record(problems=("x",), error="ReplayError: y", unexpected_writes=2)
    sink.write(written)
    assert sink.read() == [written]


def test_the_records_read_back_the_same_whatever_order_they_were_written_in(
    tmp_path: Path,
) -> None:
    one, two = RunSink(tmp_path / "a", SESSION), RunSink(tmp_path / "b", SESSION)
    runs = [record("a", 3), record("b", 1), record("a", 1)]
    for r in runs:
        one.write(r)
    for r in reversed(runs):
        two.write(r)
    assert one.read() == two.read() and len(one.read()) == 3


def test_a_rerun_replaces_its_own_record(tmp_path: Path) -> None:
    sink = RunSink(tmp_path, SESSION)
    sink.write(record(passed=False))
    sink.write(record(passed=True))
    assert [r.passed for r in sink.read()] == [True]
    assert [p.name for p in tmp_path.iterdir()] == ["a.run-1.json"]  # no temporary left


@pytest.mark.parametrize(
    "other",
    [
        replace(SESSION, id="s2"),  # an earlier or concurrent session
        replace(SESSION, mode="live"),  # another mode
        replace(SESSION, fingerprint="0" * 8),  # another prompt
    ],
    ids=["session", "mode", "fingerprint"],
)
def test_a_record_of_another_session_mode_or_fingerprint_is_refused(
    tmp_path: Path, other: SinkSession
) -> None:
    RunSink(tmp_path, other).write(record())
    with pytest.raises(SinkError, match=r"a\.run-1\.json"):
        RunSink(tmp_path, SESSION).read()


def test_two_sessions_with_their_own_directories_never_see_each_other(tmp_path: Path) -> None:
    first, second = SinkSession.new("replay"), SinkSession.new("replay")
    assert first.id != second.id and first.fingerprint == prompt_fingerprint()
    a, b = RunSink(tmp_path / first.id, first), RunSink(tmp_path / second.id, second)
    a.write(record("a"))
    b.write(record("b"))
    assert [r.case for r in a.read()] == ["a"] and [r.case for r in b.read()] == ["b"]


def test_an_empty_or_missing_sink_reads_as_no_records(tmp_path: Path) -> None:
    assert RunSink(tmp_path / "never-written", SESSION).read() == []


def test_the_prompt_fingerprint_changes_with_the_settings() -> None:
    assert prompt_fingerprint(replace(MODEL_SETTINGS, effort="high")) != prompt_fingerprint()

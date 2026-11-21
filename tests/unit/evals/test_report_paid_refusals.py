"""A paid run that asks for a report is refused before it starts when the report could not be
written afterwards (B110): a partial selection, a commit that cannot be read, and `-x`/`--maxfail`.
Real pytest sessions (pytester) in live mode, with the model factory faked: no model is built
and no network can be reached. A counting factory that stays at zero is the proof no run started."""

import subprocess
from pathlib import Path
from typing import Any

import pytest

import evals.conftest as hooks
from evals.harness import model as harness_model
from evals.harness import report_files

pytest_plugins = ["pytester"]
FIXTURE_CASES = Path(__file__).parents[2] / "fixtures" / "evals" / "cases"
INNER = """
import pytest
from pathlib import Path
from evals.harness import model as harness_model
from evals.harness.metrics import RunRecord

pytestmark = pytest.mark.eval

@pytest.mark.parametrize("case", ["fixture-order", "fixture-discount"])
@pytest.mark.parametrize("run", [1, 2, 3])
def test_case(case, run, mode, model_settings, run_sink):
    harness_model.model_factory(mode, Path("unused"), case, run, model_settings)  # faked
    ordered = case == "fixture-order"
    verdict = "verified" if ordered else "nothing_confirmed"
    suite = "core" if ordered else "gauchadas"
    if run_sink:
        run_sink.write(RunRecord(case, run, suite, ordered, True, verdict, 0, ordered, 0, ()))
    assert case != "fixture-order" or run != 2, "a failing run"
"""
LIVE = ["--live", "--report", "v9.9"]


class Calls:
    """The fake model factory: counts the runs that reached for a model, builds none."""

    def __init__(self) -> None:
        self.count = 0

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.count += 1
        return lambda: pytest.fail("the model must never be built")


@pytest.fixture(autouse=True)
def calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Calls:
    monkeypatch.setattr(hooks, "CASES_DIR", FIXTURE_CASES)
    monkeypatch.setattr(report_files, "REPORTS_DIR", tmp_path / "reports")
    fake = Calls()
    monkeypatch.setattr(harness_model, "model_factory", fake)
    return fake


def inner(pytester: pytest.Pytester, git: bool = True) -> pytest.Pytester:
    pytester.makepyfile(test_inner=INNER)
    pytester.makeini("[pytest]\nmarkers =\n    eval: an eval run\n")
    if git:
        env = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
        for args in (["init", "-q"], ["add", "test_inner.py"], ["commit", "-q", "-m", "x"]):
            subprocess.run([*env, *args], cwd=pytester.path, check=True, capture_output=True)
    return pytester


def run(pytester: pytest.Pytester, *args: str) -> pytest.RunResult:
    return pytester.runpytest("-p", "evals.conftest", *args)


def reports(tmp_path: Path) -> list[str]:
    directory = tmp_path / "reports"
    return sorted(p.name for p in directory.iterdir()) if directory.exists() else []


def refused(result: pytest.RunResult, calls: Calls, tmp_path: Path, message: str) -> None:
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert message in result.stderr.str()
    assert calls.count == 0 and reports(tmp_path) == []  # nothing ran, nothing is half written
    assert "report NOT written" not in result.stdout.str()


def test_a_complete_live_selection_runs_and_writes_its_report(
    pytester: pytest.Pytester, tmp_path: Path, calls: Calls
) -> None:
    """The control: the guards let the whole suite through."""
    result = run(inner(pytester), *LIVE)
    assert result.ret == pytest.ExitCode.TESTS_FAILED  # its one failing run, the report is written
    assert calls.count == 6 and len(reports(tmp_path)) == 2
    result.stdout.fnmatch_lines(["report written: *"])


@pytest.mark.parametrize(
    "narrowing",
    [
        ["-k", "fixture-order"],
        ["-k", "not fixture-order"],
        ["--deselect", "test_inner.py::test_case[1-fixture-order]"],
        ["test_inner.py::test_case[1-fixture-order]"],
        ["test_inner.py::test_case[1-fixture-order]", "test_inner.py::test_case[1-fixture-order]"],
        ["-m", "not eval"],
    ],
)
def test_a_live_run_that_is_not_the_whole_suite_is_refused_before_any_run(
    pytester: pytest.Pytester, tmp_path: Path, calls: Calls, narrowing: list[str]
) -> None:
    result = run(inner(pytester), *LIVE, "--record", *narrowing)
    refused(result, calls, tmp_path, "the report needs the whole suite (6)")


def test_a_live_run_of_only_the_last_failures_is_refused_before_any_run(
    pytester: pytest.Pytester, tmp_path: Path, calls: Calls
) -> None:
    """`--lf` keeps only the failures of the last run: a replay that failed one run."""
    inner(pytester)
    assert run(pytester, "--report", "v9.9").ret == pytest.ExitCode.TESTS_FAILED
    calls.count = 0  # the replay above counted its own runs
    result = run(pytester, *LIVE, "--lf")
    assert result.ret == pytest.ExitCode.USAGE_ERROR and calls.count == 0
    assert "the report needs the whole suite (6)" in result.stderr.str()


def test_a_live_run_with_an_unreadable_commit_is_refused_before_any_run(
    pytester: pytest.Pytester, tmp_path: Path, calls: Calls, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unreadable(root: Path) -> str:
        raise subprocess.CalledProcessError(128, "git rev-parse HEAD")

    monkeypatch.setattr(hooks, "commit_label", unreadable)
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "v9.9-claude-haiku-5-5.json").write_text("an older report")
    result = run(inner(pytester), *LIVE)
    assert result.ret == pytest.ExitCode.USAGE_ERROR and calls.count == 0
    assert "the commit cannot be read" in result.stderr.str()
    assert reports(tmp_path) == ["v9.9-claude-haiku-5-5.json"]  # a refused run deletes nothing


def test_a_live_run_outside_a_repository_is_refused_before_any_run(
    pytester: pytest.Pytester, tmp_path: Path, calls: Calls
) -> None:
    result = run(inner(pytester, git=False), *LIVE, "--record")
    refused(result, calls, tmp_path, "the commit cannot be read")


@pytest.mark.parametrize("stop", [["-x"], ["--exitfirst"], ["--maxfail", "2"], ["--maxfail=1"]])
def test_a_live_run_that_stops_after_a_failure_is_refused_before_any_run(
    pytester: pytest.Pytester, tmp_path: Path, calls: Calls, stop: list[str]
) -> None:
    result = run(inner(pytester), *LIVE, *stop)
    refused(result, calls, tmp_path, "-x/--maxfail stops the session after a failure")


def test_replay_keeps_its_behavior_for_all_three(
    pytester: pytest.Pytester, tmp_path: Path, calls: Calls, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replay spends nothing: it runs the selection it was given, with `-x` too, and then
    fails without a report, as before."""
    inner(pytester)
    narrowed = run(pytester, "--report", "v9.9", "-k", "fixture-discount")
    stopped = run(pytester, "--report", "v9.9", "-x")
    assert narrowed.ret == pytest.ExitCode.TESTS_FAILED
    narrowed.assert_outcomes(passed=3, deselected=3)
    narrowed.stdout.fnmatch_lines(["report NOT written: *no record for*"])
    assert stopped.ret == pytest.ExitCode.TESTS_FAILED
    stopped.assert_outcomes(passed=2, failed=1)
    assert calls.count == 3 + 3 and reports(tmp_path) == []

    monkeypatch.setattr(hooks, "commit_label", lambda root: (_ for _ in ()).throw(OSError("git")))
    unreadable = run(pytester, "--report", "v9.9")
    unreadable.assert_outcomes(passed=5, failed=1)
    unreadable.stdout.fnmatch_lines(["report NOT written: *commit could not be read*"])
    assert reports(tmp_path) == []

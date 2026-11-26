"""The `--report` option (task 13.2, B91): through real pytest sessions (pytester) for what a
user sees, and with fakes for the xdist side. The report is written at the end of the session
only when asked for, only by the process that owns the session, and never from partial runs."""

import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import evals.conftest as hooks
from dale.brain.application.model_port import MODEL_SETTINGS
from evals.harness import pricing, report_files
from evals.harness.metrics import RunRecord
from evals.harness.model import prompt_fingerprint
from evals.harness.models import DEFAULT_MODEL, SONNET, settings_for
from evals.harness.pricing import load_pricing
from evals.harness.report import build_report

pytest_plugins = ["pytester"]
STEM = f"v9.9-{MODEL_SETTINGS.model}"  # a report is named for its version and its model (S14.3)
FIXTURE_CASES = Path(__file__).parents[2] / "fixtures" / "evals" / "cases"
INNER = """
import pytest
from evals.harness.metrics import RunRecord

@pytest.mark.parametrize("case", ["fixture-order", "fixture-discount"])
@pytest.mark.parametrize("run", [1, 2, 3])
def test_case(case, run, run_sink, request):
    ordered = case == "fixture-order"
    verdict = "verified" if ordered else "nothing_confirmed"
    suite = "core" if ordered else "gauchadas"
    if run_sink:
        run_sink.write(RunRecord(case, run, suite, ordered, True, verdict, 0, ordered, 0, ()))
    (request.config.rootpath / "written-by-the-run.txt").write_text("like a recording")
"""


@pytest.fixture(autouse=True)
def fixture_cases_and_reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hooks, "CASES_DIR", FIXTURE_CASES)
    monkeypatch.setattr(report_files, "REPORTS_DIR", tmp_path / "reports")


def inner(pytester: pytest.Pytester) -> pytest.Pytester:
    """A git repository holding one test that behaves like the suite: it writes a record per
    run, and a file of its own, as `--record` would."""
    pytester.makepyfile(test_inner=INNER)
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
    for args in (["init", "-q"], ["add", "test_inner.py"], ["commit", "-q", "-m", "x"]):
        subprocess.run([*git, *args], cwd=pytester.path, check=True, capture_output=True)
    return pytester


def run(pytester: pytest.Pytester, *args: str) -> pytest.RunResult:
    return pytester.runpytest("-p", "evals.conftest", *args)


def reports(tmp_path: Path) -> list[str]:
    directory = tmp_path / "reports"
    return sorted(p.name for p in directory.iterdir()) if directory.exists() else []


def test_a_complete_session_writes_the_report_from_every_run(
    pytester: pytest.Pytester, tmp_path: Path
) -> None:
    result = run(inner(pytester), "--report", "v9.9")
    result.assert_outcomes(passed=6)
    result.stdout.fnmatch_lines([f"report written: *{STEM}.json, *{STEM}.md"])
    assert reports(tmp_path) == [f"{STEM}.json", f"{STEM}.md"] and result.ret == pytest.ExitCode.OK
    text = (tmp_path / "reports" / f"{STEM}.json").read_text()
    assert '"mode": "replay"' in text and '"verified": 3' in text


def test_the_commit_is_the_one_at_session_start_not_dirtied_by_what_the_run_writes(
    pytester: pytest.Pytester, tmp_path: Path
) -> None:  # B91 nit
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=inner(pytester).path, capture_output=True, text=True
    ).stdout.strip()
    run(pytester, "--report", "v9.9")
    assert f'"commit": "{sha}"' in (tmp_path / "reports" / f"{STEM}.json").read_text()
    assert (pytester.path / "written-by-the-run.txt").exists()  # written after the label was read


def test_a_session_with_a_deselected_run_writes_no_report_and_fails(
    pytester: pytest.Pytester, tmp_path: Path
) -> None:
    result = run(
        inner(pytester),
        "--report",
        "v9.9",
        "--deselect",
        "test_inner.py::test_case[1-fixture-order]",
    )
    result.assert_outcomes(passed=5, deselected=1)
    result.stdout.fnmatch_lines(["report NOT written: *no record for*fixture-order*"])
    assert reports(tmp_path) == [] and result.ret == pytest.ExitCode.TESTS_FAILED


def test_a_report_that_cannot_be_written_never_leaves_an_older_one_in_place(
    pytester: pytest.Pytester, tmp_path: Path
) -> None:  # B91 (2)
    (tmp_path / "reports").mkdir()
    for name in (f"{STEM}.json", f"{STEM}.md", "v1.0.json", "v9.9-claude-sonnet-5-5.json"):
        (tmp_path / "reports" / name).write_text("Release gate: PASS")
    result = run(inner(pytester), "--report", "v9.9", "-k", "fixture-order")  # runs missing
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    # the stale pair of this version and model is gone, no other (not another model's either)
    assert reports(tmp_path) == ["v1.0.json", "v9.9-claude-sonnet-5-5.json"]


def test_without_the_option_nothing_is_written_nor_deleted(
    pytester: pytest.Pytester, tmp_path: Path
) -> None:
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / f"{STEM}.json").write_text("old")
    result = run(inner(pytester))
    result.assert_outcomes(passed=6)
    assert reports(tmp_path) == [f"{STEM}.json"] and "report" not in result.stdout.str().lower()


def test_the_sink_directory_of_the_session_is_removed_at_its_end(
    pytester: pytest.Pytester,
) -> None:
    run(inner(pytester), "--report", "v9.9")
    assert list((pytester.path / ".pytest_cache" / "d").glob("dale-eval-*")) == []


def test_a_version_that_is_not_a_plain_name_is_a_usage_error(
    pytester: pytest.Pytester, tmp_path: Path
) -> None:
    result = run(inner(pytester), "--report", "../v9.9")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert "not a version name" in result.stderr.str() and reports(tmp_path) == []


def test_the_option_needs_the_cache_provider(pytester: pytest.Pytester) -> None:
    result = run(inner(pytester), "--report", "v9.9", "-p", "no:cacheprovider")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert "cache provider" in result.stderr.str()


def priced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *models: str) -> None:
    """A price file with the shipped Haiku table, copied for each model named: the shipped file
    has no Sonnet table until its prices are read from the live page."""
    table = pricing.PRICING_FILE.read_text(encoding="utf-8")
    text = "".join(table.replace("claude-haiku-5-5", model) for model in models)
    (tmp_path / "pricing.toml").write_text(text, encoding="utf-8")
    monkeypatch.setattr(pricing, "PRICING_FILE", tmp_path / "pricing.toml")


def test_each_model_writes_its_own_report_and_never_the_others(
    pytester: pytest.Pytester, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S14.3: the same version for two compared models gives two named pairs."""
    priced(tmp_path, monkeypatch, "claude-haiku-5-5", "claude-sonnet-5-5")
    inner(pytester)
    for model in ("claude-haiku-5-5", "claude-sonnet-5-5"):
        assert run(pytester, "--report", "v9.9", "--model", model).ret == 0
    assert reports(tmp_path) == [
        "v9.9-claude-haiku-5-5.json",
        "v9.9-claude-haiku-5-5.md",
        "v9.9-claude-sonnet-5-5.json",
        "v9.9-claude-sonnet-5-5.md",
    ]
    for model in ("claude-haiku-5-5", "claude-sonnet-5-5"):
        text = (tmp_path / "reports" / f"v9.9-{model}.json").read_text()
        assert f'"model": "{model}"' in text and f'"effort": "{MODEL_SETTINGS.effort}"' in text


def test_a_model_with_no_prices_is_a_usage_error_before_any_run(
    pytester: pytest.Pytester, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S14.4: nothing runs, so no paid run can end with a report that cannot be written."""
    priced(tmp_path, monkeypatch, "claude-haiku-5-5")
    result = run(inner(pytester), "--report", "v9.9", "--model", "claude-sonnet-5-5")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert "no pricing table for claude-sonnet-5-5" in result.stderr.str()
    assert reports(tmp_path) == [] and not (pytester.path / "written-by-the-run.txt").exists()


class Terminal:
    def write_line(self, line: str) -> None:
        pass


def fake(
    tmp: Path,
    report: str | None,
    worker: dict[str, Any] | None = None,
    model: str = DEFAULT_MODEL,
) -> Any:
    options = {"--report": report, "--live": False, "--record": False, "--model": model}
    config = SimpleNamespace(
        getoption=options.__getitem__,
        cache=SimpleNamespace(mkdir=lambda name: tmp / name),
        rootpath=Path(__file__).parents[3],
        pluginmanager=SimpleNamespace(get_plugin=lambda name: Terminal()),
        stash=pytest.Stash(),
    )
    if worker is not None:
        config.workerinput = worker
    return SimpleNamespace(config=config, exitstatus=pytest.ExitCode.OK)


def test_the_controller_hands_its_session_to_each_worker_and_the_worker_uses_it(
    tmp_path: Path,
) -> None:
    controller = fake(tmp_path, "v9.9")
    node = SimpleNamespace(config=controller.config, workerinput={})
    hooks.pytest_configure_node(node)
    worker = fake(tmp_path, "v9.9", node.workerinput)
    assert hooks._session(worker.config) == hooks._session(controller.config)
    assert hooks._sink(worker.config) is not None
    assert hooks._sink(worker.config)._directory == hooks._sink(controller.config)._directory  # type: ignore[union-attr]


def test_two_sessions_have_their_own_directories_and_never_see_each_other(tmp_path: Path) -> None:
    one, two = fake(tmp_path, "v9.9"), fake(tmp_path, "v9.9")
    a, b = hooks._sink(one.config), hooks._sink(two.config)
    assert a is not None and b is not None and a._directory != b._directory
    record = RunRecord("fixture-order", 1, "core", True, True, "verified", 0, True, 0, ())
    a.write(record)
    b.write(replace(record, case="fixture-discount"))
    assert [r.case for r in a.read()] == ["fixture-order"]
    assert [r.case for r in b.read()] == ["fixture-discount"]


def test_a_worker_neither_deletes_a_report_nor_writes_one(tmp_path: Path) -> None:
    controller = fake(tmp_path, "v9.9")
    sink = hooks._sink(controller.config)
    assert sink is not None
    for case, suite in (("fixture-order", "core"), ("fixture-discount", "gauchadas")):
        for n in (1, 2, 3):
            sink.write(RunRecord(case, n, suite, True, True, "verified", 0, True, 0, ()))
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / f"{STEM}.md").write_text("kept")
    worker = fake(
        tmp_path, "v9.9", {hooks.WORKER_KEY: {"id": "x", "mode": "replay", "fingerprint": "f"}}
    )
    hooks.pytest_sessionstart(worker)
    hooks.pytest_sessionfinish(worker)
    assert reports(tmp_path) == [f"{STEM}.md"]


def test_the_report_is_built_for_the_model_the_session_ran(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B109: a session for another model never writes a report that names the default one. The
    prices are stood in for here, since only the shipped model has a table in this file."""
    written: list[dict[str, Any]] = []

    def build(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return build_report(
            *args, pricing=replace(load_pricing(DEFAULT_MODEL), model=SONNET), **kwargs
        )

    def write(report: dict[str, Any]) -> tuple[Path, Path]:
        written.append(report)
        return tmp_path / "a.json", tmp_path / "a.md"

    monkeypatch.setattr(hooks, "build_report", build)
    monkeypatch.setattr(hooks, "write_report", write)
    session = fake(tmp_path, "v9.9", model=SONNET)
    sink = hooks._sink(session.config)
    assert sink is not None
    for case, suite in (("fixture-order", "core"), ("fixture-discount", "gauchadas")):
        for n in (1, 2, 3):
            sink.write(RunRecord(case, n, suite, True, True, "verified", 0, True, 0, ()))
    monkeypatch.setattr(hooks, "CASES_DIR", FIXTURE_CASES)
    session.config.stash[hooks.COMMIT] = "a" * 40
    hooks.pytest_sessionfinish(session)
    assert session.exitstatus == pytest.ExitCode.OK
    assert [(r["model"], r["prompt"]["fingerprint"]) for r in written] == [
        (SONNET, prompt_fingerprint(settings_for(SONNET)))
    ]

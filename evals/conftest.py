"""Eval options. Default: replay, no network (S13.4). `--live` calls the live model and never
writes; `--live --record` also writes the recordings (14.9). `--record` alone is refused.
`--model` picks the compared model the session replays, records or runs live (default
`MODEL_SETTINGS.model`, D23).

The socket policy follows the mode. pyproject's addopts pass pytest-socket `--disable-socket
--allow-hosts=127.0.0.1,localhost`, which blocks the model API. Replay keeps that restriction.
`--live`, with or without `--record`, lifts it for that session only: before pytest-socket's
own `pytest_configure` stores its settings, this one (tryfirst) sets `--force-enable-socket`,
and pytest-socket checks that first in every test's setup, enabling sockets and returning
before it applies the allowed hosts (pytest_socket 0.8.1, `pytest_runtest_setup`).

`--report <version>` writes `evals/reports/<version>-<model>.json` and `.md` when the session
ends, in any mode, for the model `--model` names (S14.3), from the record of every run
(`evals/harness/report.py`), with the snapshot ids its recordings name (none in `--live`
alone, which writes no recording). Without it nothing is written, so a normal replay run never
rewrites a committed report. A model with no pricing table is a usage error at session start,
before any run (S14.4). Only the process that owns the session (not an xdist worker) touches
the reports:
- at session start it reads the commit and its dirty flag, then deletes the files of that version
  and model (git keeps the old ones), so a report that is not written can never leave a stale
  one in place and a recording the session writes cannot make the commit dirty (B91); a record
  run leaves `evals/recordings` out of that dirty check, so both models record on one commit;
- each session has its own id and its own sink directory under pytest's cache directory; the
  controller hands the id to its workers (`workerinput`), and a record from any other session,
  mode or prompt is refused;
- at session end it builds the report from that sink and removes the directory. If a run has no
  record (a deselected case, an interrupted session) or anything else is wrong, no report is
  written and the session fails.

A paid run (`--live`, with or without `--record`) with `--report` is refused before any run when
its report could not be written afterwards (B110), each as a usage error:
- `-x` or `--maxfail`: a stop after a failure leaves runs without a record (at configure time);
- a commit that cannot be read at session start (the report names the commit it measured);
- a selection that is not the whole suite, every case for every run, whatever narrowed it
  (`-k`, `-m`, `--deselect`, `--lf`, node ids), checked when collection finishes.
Replay spends nothing, so it keeps running and then fails without a report.
"""

import shutil
import subprocess
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from dale.brain.application.model_port import ModelSettings
from evals.harness.case import load_cases
from evals.harness.collect import CASES_DIR
from evals.harness.metrics import RUNS_PER_CASE
from evals.harness.model import Mode, mode_from_flags, recordings_dir, snapshot_ids
from evals.harness.models import COMPARED, DEFAULT_MODEL, settings_for
from evals.harness.pricing import PricingError, load_pricing
from evals.harness.report import VERSION, ReportError, build_report
from evals.harness.report_files import commit_label, report_paths, write_report
from evals.harness.sink import RunSink, SinkSession
from tests.conftest import engines, migrated_db  # noqa: F401  (the session database fixtures)


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("evals")
    group.addoption("--live", action="store_true", help="call the live model (spends money)")
    group.addoption("--record", action="store_true", help="with --live, write the recordings")
    group.addoption("--report", metavar="VERSION", help="write the release report for VERSION")
    group.addoption(
        "--model",
        default=DEFAULT_MODEL,
        choices=sorted(COMPARED),
        help="the model to replay, record or run live (default: the shipped model)",
    )


def _mode(config: pytest.Config) -> Mode:
    try:
        return mode_from_flags(config.getoption("--live"), config.getoption("--record"))
    except ValueError as error:
        raise pytest.UsageError(str(error)) from error


def lifts_host_restriction(mode: Mode) -> bool:
    """The live modes reach the model API; replay reaches nothing but the local database."""
    return mode is not Mode.REPLAY


@pytest.hookimpl(tryfirst=True)  # before pytest-socket reads its options
def pytest_configure(config: pytest.Config) -> None:
    mode = _mode(config)  # a bad flag combination stops the session before any test
    if lifts_host_restriction(mode):
        config.option.force_enable_socket = True
    if (version := config.getoption("--report")) is None:
        return
    if not VERSION.fullmatch(version):
        raise pytest.UsageError(f"--report: {version!r} is not a version name")
    try:  # a model with no prices fails before any run, not after a paid one (S14.4)
        load_pricing(config.getoption("--model"))
    except PricingError as error:
        raise pytest.UsageError(f"--report: {error}") from error
    if lifts_host_restriction(mode) and config.getoption("maxfail"):  # -x is maxfail=1
        raise pytest.UsageError(
            "--report with --live: -x/--maxfail stops the session after a failure, and the "
            "report could not be written after paying for the runs"
        )
    if config.pluginmanager.is_blocked("cacheprovider"):
        raise pytest.UsageError("--report needs pytest's cache provider (not -p no:cacheprovider)")


@pytest.fixture(scope="session")
def mode(request: pytest.FixtureRequest) -> Mode:
    return _mode(request.config)


@pytest.fixture(scope="session")
def model_settings(request: pytest.FixtureRequest) -> ModelSettings:
    """The settings of the model under test: the shipped ones with only the model replaced."""
    return settings_for(request.config.getoption("--model"))


_RUNS = range(1, RUNS_PER_CASE + 1)
SESSION = pytest.StashKey[SinkSession]()
COMMIT = pytest.StashKey[str]()
WORKER_KEY = "dale_eval_session"


def _is_worker(config: pytest.Config) -> bool:
    return getattr(config, "workerinput", None) is not None


def _session(config: pytest.Config) -> SinkSession:
    """The controller makes the session; a worker gets it from the controller."""
    if _is_worker(config):
        return SinkSession(**config.workerinput[WORKER_KEY])  # type: ignore[attr-defined]
    if SESSION not in config.stash:
        config.stash[SESSION] = SinkSession.new(_mode(config).value)
    return config.stash[SESSION]


@pytest.hookimpl(optionalhook=True)  # an xdist hook; without xdist nothing calls it
def pytest_configure_node(node: Any) -> None:
    node.workerinput[WORKER_KEY] = asdict(_session(node.config))


def _sink(config: pytest.Config) -> RunSink | None:
    """Where this session's records go: only with `--report`, in a directory of its own."""
    if not config.getoption("--report") or config.cache is None:
        return None
    session = _session(config)
    return RunSink(Path(config.cache.mkdir(f"dale-eval-{session.id}")), session)


def pytest_sessionstart(session: pytest.Session) -> None:
    config = session.config
    if (version := config.getoption("--report")) and not _is_worker(config):
        try:
            recording = _mode(config) is Mode.RECORD  # its own recordings are not dirt
            config.stash[COMMIT] = commit_label(config.rootpath, recording=recording)
        except (OSError, subprocess.CalledProcessError) as error:
            if lifts_host_restriction(_mode(config)):  # B110: never pay for a report to lose
                raise pytest.UsageError(
                    f"--report with --live: the commit cannot be read, so the report could not "
                    f"be written after paying for the runs ({type(error).__name__})"
                ) from error
            # replay: no commit in the stash, so no report at the end
        for path in report_paths(version, config.getoption("--model")):
            path.unlink(missing_ok=True)


def _run_key(item: pytest.Item) -> tuple[str, int]:
    """Which run an eval item is: its case id and run number, from the parameters of
    `evals/test_cases.py::test_case`. An eval item without them is keyed by its node id, which
    is never a run of the suite."""
    params = getattr(getattr(item, "callspec", None), "params", {})
    if "case" not in params or "run" not in params:
        return item.nodeid, 0
    case = params["case"]
    return getattr(case, "id", case), params["run"]  # a Case, or its id


def pytest_collection_finish(session: pytest.Session) -> None:
    """B110: a paid run with `--report` must select the whole suite, exactly once per run,
    because the report is refused for any other selection (`build_report`)."""
    config = session.config
    if not config.getoption("--report") or not lifts_host_restriction(_mode(config)):
        return
    selected = sorted(_run_key(item) for item in session.items if item.get_closest_marker("eval"))
    whole = sorted((case.id, run) for case in load_cases(CASES_DIR) for run in _RUNS)
    if selected != whole:
        raise pytest.UsageError(
            f"--report with --live: the selection is {len(selected)} eval runs, the report needs "
            f"the whole suite ({len(whole)}), so it could not be written after paying for them; "
            "drop -k, -m, --deselect, --lf and node ids"
        )


@pytest.fixture(scope="session")
def run_sink(request: pytest.FixtureRequest) -> RunSink | None:
    return _sink(request.config)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session: pytest.Session) -> None:
    config = session.config
    if not (version := config.getoption("--report")) or _is_worker(config):
        return  # no report asked for, or an xdist worker: the controller writes it
    if session.exitstatus == pytest.ExitCode.USAGE_ERROR:
        return  # refused before any run: nothing ran, so there is nothing to report or clean up
    sink = _sink(config)
    try:
        assert sink is not None
        if COMMIT not in config.stash:
            raise ReportError("the commit could not be read at the start of the session")
        suite = {case.id: case.suite for case in load_cases(CASES_DIR)}
        model = config.getoption("--model")
        snapshots = (  # B114: a live run writes no recording, so it names no snapshot
            () if _mode(config) is Mode.LIVE else snapshot_ids(recordings_dir(model), suite)
        )
        report = build_report(
            sink.read(),
            suite,
            version=version,
            mode=_session(config).mode,
            commit=config.stash[COMMIT],
            generated=datetime.now(UTC),
            settings=settings_for(model),
            snapshot_ids=snapshots,
        )
        message = "report written: " + ", ".join(str(p) for p in write_report(report))
    except (ValueError, KeyError, TypeError, OSError) as error:
        message = f"report NOT written: {error}"
        if session.exitstatus == pytest.ExitCode.OK:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
    finally:
        if config.cache is not None:
            shutil.rmtree(
                config.cache.mkdir(f"dale-eval-{_session(config).id}"), ignore_errors=True
            )
    if terminal := config.pluginmanager.get_plugin("terminalreporter"):
        terminal.write_line(message)

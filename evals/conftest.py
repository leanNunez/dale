"""Eval options. Default: replay, no network (S13.4). `--live` calls the live model and never
writes; `--live --record` also writes the recordings (14.9). `--record` alone is refused.

The socket policy follows the mode. pyproject's addopts pass pytest-socket `--disable-socket
--allow-hosts=127.0.0.1,localhost`, which blocks the model API. Replay keeps that restriction.
`--live`, with or without `--record`, lifts it for that session only: before pytest-socket's
own `pytest_configure` stores its settings, this one (tryfirst) sets `--force-enable-socket`,
and pytest-socket checks that first in every test's setup, enabling sockets and returning
before it applies the allowed hosts (pytest_socket 0.8.1, `pytest_runtest_setup`).

`--report <version>` writes `evals/reports/<version>.json` and `.md` when the session ends, in
any mode, from the record of every run (`evals/harness/report.py`). Without it nothing is
written, so a normal replay run never rewrites a committed report. Only the process that owns
the session (not an xdist worker) touches the reports:
- at session start it deletes the files of that version (git keeps the old ones), and reads the
  commit and its dirty flag, so a report that is not written can never leave a stale one in place
  and a recording the session writes cannot make the commit dirty (B91);
- each session has its own id and its own sink directory under pytest's cache directory; the
  controller hands the id to its workers (`workerinput`), and a record from any other session,
  mode or prompt is refused;
- at session end it builds the report from that sink and removes the directory. If a run has no
  record (a deselected case, an interrupted session) or anything else is wrong, no report is
  written and the session fails.
"""

import contextlib
import shutil
import subprocess
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from evals.harness.case import load_cases
from evals.harness.collect import CASES_DIR
from evals.harness.model import Mode, mode_from_flags
from evals.harness.report import VERSION, ReportError, build_report
from evals.harness.report_files import commit_label, report_paths, write_report
from evals.harness.sink import RunSink, SinkSession
from tests.conftest import engines, migrated_db  # noqa: F401  (the session database fixtures)


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("evals")
    group.addoption("--live", action="store_true", help="call the live model (spends money)")
    group.addoption("--record", action="store_true", help="with --live, write the recordings")
    group.addoption("--report", metavar="VERSION", help="write the release report for VERSION")


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
    if config.pluginmanager.is_blocked("cacheprovider"):
        raise pytest.UsageError("--report needs pytest's cache provider (not -p no:cacheprovider)")


@pytest.fixture(scope="session")
def mode(request: pytest.FixtureRequest) -> Mode:
    return _mode(request.config)


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
        for path in report_paths(version):
            path.unlink(missing_ok=True)
        with contextlib.suppress(OSError, subprocess.CalledProcessError):
            config.stash[COMMIT] = commit_label(config.rootpath)  # else: no report at the end


@pytest.fixture(scope="session")
def run_sink(request: pytest.FixtureRequest) -> RunSink | None:
    return _sink(request.config)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session: pytest.Session) -> None:
    config = session.config
    if not (version := config.getoption("--report")) or _is_worker(config):
        return  # no report asked for, or an xdist worker: the controller writes it
    sink = _sink(config)
    try:
        assert sink is not None
        if COMMIT not in config.stash:
            raise ReportError("the commit could not be read at the start of the session")
        suite = {case.id: case.suite for case in load_cases(CASES_DIR)}
        report = build_report(
            sink.read(),
            suite,
            version=version,
            mode=_session(config).mode,
            commit=config.stash[COMMIT],
            generated=datetime.now(UTC),
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

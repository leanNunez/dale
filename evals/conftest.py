"""Eval options. Default: replay, no network (S13.4). `--live` calls the live model and never
writes; `--live --record` also writes the recordings (14.9). `--record` alone is refused.

The socket policy follows the mode. pyproject's addopts pass pytest-socket `--disable-socket
--allow-hosts=127.0.0.1,localhost`, which blocks the model API. Replay keeps that restriction.
`--live`, with or without `--record`, lifts it for that session only: before pytest-socket's
own `pytest_configure` stores its settings, this one (tryfirst) sets `--force-enable-socket`,
and pytest-socket checks that first in every test's setup, enabling sockets and returning
before it applies the allowed hosts (pytest_socket 0.8.1, `pytest_runtest_setup`).
"""

import pytest

from evals.harness.model import Mode, mode_from_flags
from tests.conftest import engines, migrated_db  # noqa: F401  (the session database fixtures)


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("evals")
    group.addoption("--live", action="store_true", help="call the live model (spends money)")
    group.addoption("--record", action="store_true", help="with --live, write the recordings")


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


@pytest.fixture(scope="session")
def mode(request: pytest.FixtureRequest) -> Mode:
    return _mode(request.config)

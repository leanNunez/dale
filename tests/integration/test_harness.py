"""The eval harness end to end on two tiny fixture cases with hand-written recordings (task
12.6; R13): three runs each through replay, the real verifier process and the grader. Also
S13.2 with real runs, S13.4 (no model call over the network) and the replay guards: a stale
fingerprint, a changed tool result and a recorded step the run never used."""

import json
import re
import socket
from pathlib import Path
from typing import Any

import pytest
from pytest_socket import SocketConnectBlockedError
from sqlalchemy import Engine

from dale.brain.application.model_port import ModelRequest, ModelResponse
from evals.harness.case import load_cases
from evals.harness.grader import grade
from evals.harness.model import Mode, ReplayError, ReplayModel, model_factory
from evals.harness.runner import Env, RunState, run_case
from tests.conftest import role_url
from tests.fixtures.evals.regenerate import STEPS, write_recordings

pytestmark = pytest.mark.integration
FIXTURES = Path(__file__).parents[1] / "fixtures" / "evals"
RECORDED = FIXTURES / "recordings"
CASES = {case.id: case for case in load_cases(FIXTURES / "cases")}
RUNS = [(case, run) for case in CASES for run in (1, 2, 3)]


def replay(db: Engine, case_id: str, run: int, root: Path = RECORDED, **changes: Any) -> RunState:
    env, case = Env(db, role_url("dale_verifier")), CASES[case_id].model_copy(update=changes)
    return run_case(case, env, model_factory(Mode.REPLAY, root, case_id, run))


def record(db: Engine, root: Path) -> None:
    write_recordings(root, Env(db, role_url("dale_verifier")))


@pytest.mark.parametrize(("case_id", "run"), RUNS)
def test_every_run_of_every_fixture_case_passes(db: Engine, case_id: str, run: int) -> None:
    state = replay(db, case_id, run)
    result = grade(CASES[case_id], state)
    assert result.passed, result.problems
    assert not result.false_confirmation and state.verdict.verdict in (
        "verified",
        "nothing_confirmed",
    )


def test_the_positive_case_ends_in_one_verified_order_each_run(db: Engine) -> None:
    for run in (1, 2, 3):  # each run is reset: never two orders from the runs before it
        state = replay(db, "fixture-order", run)
        assert len(state.orders) == 1 and state.verdict.verified


def test_the_gauchada_ends_in_a_handoff_and_no_order(db: Engine) -> None:
    state = replay(db, "fixture-discount", 1)
    assert state.orders == () and state.handoffs == ("exception_request",)


@pytest.mark.parametrize("case_id", CASES)
def test_different_tool_paths_reach_the_same_state_and_all_pass(db: Engine, case_id: str) -> None:
    """S13.2: run 3 of each case calls other tools than runs 1 and 2, and still passes."""
    states = [replay(db, case_id, run) for run in (1, 2, 3)]
    assert len({len(s.usage) for s in states}) == 2  # the paths differ
    assert len({(s.orders, s.handoffs) for s in states}) == 1  # the final state does not
    assert all(grade(CASES[case_id], s).passed for s in states)


def test_a_stale_recording_fails_the_run_with_re_record_required(
    db: Engine, tmp_path: Path
) -> None:
    """D9: a recording made against another prompt is refused, not replayed."""
    record(db, tmp_path)
    path = tmp_path / "fixture-order" / "run-1.jsonl"
    path.write_text(
        re.sub(r'"fingerprint": "\w{64}"', f'"fingerprint": "{"0" * 64}"', path.read_text())
    )
    with pytest.raises(ReplayError, match="re-record required"):
        replay(db, "fixture-order", 1, tmp_path)


def test_a_changed_tool_result_fails_the_run_with_re_record_required(db: Engine) -> None:
    """The digest: an earlier cutoff moves the delivery date in prepare_order's result, so the
    answer recorded after it no longer fits the conversation."""
    late = {"zones": {"Centro": {"cutoff_time": "08:00"}}}
    with pytest.raises(ReplayError, match="step 2: recording does not match this request"):
        replay(db, "fixture-order", 1, seed_overrides=late)


def test_a_missing_step_fails_the_run(db: Engine, tmp_path: Path) -> None:
    record(db, tmp_path)
    path = tmp_path / "fixture-order" / "run-1.jsonl"
    path.write_text(path.read_text().splitlines(keepends=True)[0])  # the search, nothing after
    with pytest.raises(ReplayError, match="no recorded step 1"):
        replay(db, "fixture-order", 1, tmp_path)


def test_a_recorded_step_the_run_never_used_fails_it(db: Engine, tmp_path: Path) -> None:
    record(db, tmp_path)
    path = tmp_path / "fixture-order" / "run-1.jsonl"
    last = json.loads(path.read_text().splitlines()[-1])
    path.write_text(path.read_text() + json.dumps(last | {"step": 3}) + "\n")
    with pytest.raises(ReplayError, match=r"steps \[3\] were never asked for"):
        replay(db, "fixture-order", 1, tmp_path)


def test_the_committed_recordings_are_current(db: Engine, tmp_path: Path) -> None:
    """The committed files carry today's fingerprint and digests, or this says how to
    refresh them."""
    record(db, tmp_path)
    fresh = {p.relative_to(tmp_path): p.read_text() for p in tmp_path.rglob("*.jsonl")}
    committed = {p.relative_to(RECORDED): p.read_text() for p in RECORDED.rglob("*.jsonl")}
    assert fresh == committed, "run: uv run python -m tests.fixtures.evals.regenerate"
    assert {case: len(runs) for case, runs in STEPS.items()} == {c: 3 for c in CASES}


LOCAL = {"127.0.0.1", "::1", "localhost"}


def test_a_replay_run_makes_no_network_call_except_to_the_database(
    db: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S13.4: every Python socket connect a run attempts is to this machine. (libpq opens its
    own sockets, which pytest-socket cannot see; the test database host is refused unless it
    is local, in tests/conftest.py.)"""
    attempts: list[object] = []
    connect = socket.socket.connect

    def spy(self: socket.socket, address: object) -> None:
        attempts.append(address)
        connect(self, address)  # type: ignore[arg-type]  # pytest-socket's guard

    monkeypatch.setattr(socket.socket, "connect", spy)
    assert grade(CASES["fixture-order"], replay(db, "fixture-order", 1)).passed
    assert {a[0] for a in attempts if isinstance(a, tuple)} <= LOCAL


class DialsTheModelApi:
    """A replay that reaches for the network, like the live adapter would."""

    def complete(self, request: ModelRequest) -> ModelResponse:
        socket.create_connection(("192.0.2.1", 443), timeout=1)  # an address of no model API
        raise AssertionError("unreachable under the socket policy")


@pytest.mark.filterwarnings("ignore:A test tried to use socket")
def test_a_run_that_tries_a_model_api_socket_fails(db: Engine) -> None:
    env = Env(db, role_url("dale_verifier"))
    with pytest.raises(SocketConnectBlockedError):
        run_case(CASES["fixture-order"], env, DialsTheModelApi)


def test_replay_is_the_model_the_default_mode_builds(tmp_path: Path) -> None:
    assert isinstance(model_factory(Mode.REPLAY, tmp_path, "x", 1)(), ReplayModel)

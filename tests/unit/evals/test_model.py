"""The eval model (tasks 12.1, 12.3; D9, R13): replay answers from (case, run, step) and the
fingerprint and from nothing else; record writes what replay reads; live never writes."""

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, ClassVar

import pytest

from dale.brain.application.model_port import (
    MODEL_SETTINGS,
    Json,
    ModelRequest,
    ModelResponse,
    ModelSettings,
    ModelUnavailableError,
    parse_response,
)
from dale.brain.application.prompt import fingerprint, system_blocks
from dale.brain.application.tools import TOOL_SCHEMAS
from evals.conftest import lifts_host_restriction
from evals.harness.model import (
    REPO_ROOT,
    Mode,
    RecordError,
    RecordingModel,
    ReplayError,
    ReplayModel,
    messages_digest,
    mode_from_flags,
    model_factory,
    prompt_fingerprint,
    recording_path,
    request_fingerprint,
    shown_path,
    snapshot_ids,
)
from tests.unit.brain.test_model_port import SEARCH, message

REQUEST = ModelRequest(system_blocks("Distribuidora El Hornero"), TOOL_SCHEMAS, ({"role": "user"},))
FIRST, SECOND = message(SEARCH), message({"type": "text", "text": "Listo."}, stop="end_turn")
# S11.5, design §5 check 1: the prompt the v0.1 recordings were made against, pinned from slice 2
# until the comparison slice. The tool trace and the verdict evidence must not move it.
V01_FINGERPRINT = "d7db359bbb5c67a09edcef0a370c75531554e5e500de0124b2d3e36db3dce4c9"


def write(root: Path, steps: list[Any], case: str = "a", run: int = 1, **changes: Any) -> Path:
    """One line per message, with the current fingerprint unless `changes` says otherwise."""
    path = recording_path(root, case, run)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        {"case": case, "run": run, "step": i, "fingerprint": request_fingerprint(REQUEST)}
        | {"messages": messages_digest(REQUEST), "message": m}
        | changes
        for i, m in enumerate(steps)
    ]
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    return path


def test_the_fingerprint_changes_with_the_prompt_the_tools_or_a_setting() -> None:
    """D9: model, effort, system and tools; any edit means re-record."""
    base = request_fingerprint(REQUEST)
    edited = ({"type": "text", "text": "reglas distintas"}, *REQUEST.system[1:])
    assert request_fingerprint(replace(REQUEST, system=edited)) != base
    assert request_fingerprint(replace(REQUEST, tools=TOOL_SCHEMAS[:-1])) != base
    assert request_fingerprint(REQUEST, replace(MODEL_SETTINGS, effort="high")) != base
    assert request_fingerprint(REQUEST, replace(MODEL_SETTINGS, model="claude-other")) != base
    assert request_fingerprint(REQUEST) == fingerprint(MODEL_SETTINGS, REQUEST.system, TOOL_SCHEMAS)


def test_the_prompt_fingerprint_is_still_the_one_the_v01_recordings_hold() -> None:
    assert prompt_fingerprint() == V01_FINGERPRINT


def test_replay_answers_each_call_from_its_step_in_order(tmp_path: Path) -> None:
    write(tmp_path, [FIRST, SECOND])
    replay = ReplayModel(tmp_path, "a", 1)
    assert [replay.complete(REQUEST), replay.complete(REQUEST)] == [
        parse_response(FIRST),
        parse_response(SECOND),
    ]


def test_a_stale_fingerprint_fails_with_re_record_required(tmp_path: Path) -> None:
    """D9: the prompt moved on since the recording."""
    write(tmp_path, [FIRST], fingerprint="0" * 64)
    with pytest.raises(ReplayError, match="re-record required"):
        ReplayModel(tmp_path, "a", 1).complete(REQUEST)
    write(tmp_path, [FIRST], case="b")
    edited = replace(REQUEST, system=({"type": "text", "text": "otro"},))
    with pytest.raises(ReplayError, match="re-record required"):
        ReplayModel(tmp_path, "b", 1).complete(edited)


def test_a_missing_step_fails_the_run_and_nothing_answers_instead(tmp_path: Path) -> None:
    write(tmp_path, [FIRST])
    replay = ReplayModel(tmp_path, "a", 1)
    replay.complete(REQUEST)
    with pytest.raises(ReplayError, match="no recorded step"):  # not the last step again
        replay.complete(REQUEST)


def test_a_request_whose_messages_changed_fails_with_re_record_required(tmp_path: Path) -> None:
    """Another tool result or customer text since the recording: its answer no longer fits."""
    write(tmp_path, [FIRST])
    changed = replace(REQUEST, messages=({"role": "user", "content": "otro resultado"},))
    with pytest.raises(ReplayError, match="does not match this request; re-record required"):
        ReplayModel(tmp_path, "a", 1).complete(changed)


def test_a_recorded_step_never_asked_for_fails_the_run_at_finish(tmp_path: Path) -> None:
    write(tmp_path, [FIRST, SECOND])
    replay = ReplayModel(tmp_path, "a", 1)
    replay.complete(REQUEST)
    with pytest.raises(ReplayError, match=r"steps \[1\] were never asked for"):
        replay.finish()
    replay.complete(REQUEST)
    replay.finish()  # every step used


def test_a_malformed_recorded_message_is_a_replay_error_not_a_failed_turn(tmp_path: Path) -> None:
    """A ModelUnavailableError would become a notice and a failed turn; a broken file fails."""
    write(tmp_path, [{"content": "not a list of blocks"}])
    with pytest.raises(ReplayError, match="malformed message"):
        ReplayModel(tmp_path, "a", 1).complete(REQUEST)


def test_a_missing_file_fails_the_run(tmp_path: Path) -> None:
    with pytest.raises(ReplayError, match="no recording"):
        ReplayModel(tmp_path, "a", 1).complete(REQUEST)


LINE = {"case": "a", "run": 1, "step": 0, "fingerprint": "f", "messages": "d", "message": {}}
ONE = json.dumps(LINE)


@pytest.mark.parametrize(
    "line",
    [
        ONE + "\n" + ONE,  # a step twice
        "not json",
        "[]",
        json.dumps({"case": "a", "run": 1, "step": 0}),
        json.dumps(LINE | {"case": "b"}),
        json.dumps(LINE | {"run": 2}),
        json.dumps(LINE | {"step": "0"}),
        json.dumps(LINE | {"fingerprint": 1}),
        json.dumps(LINE | {"messages": 1}),
    ],
)
def test_a_malformed_or_foreign_line_fails_the_run(tmp_path: Path, line: str) -> None:
    path = write(tmp_path, [])
    path.write_text(line + "\n", encoding="utf-8")
    with pytest.raises(ReplayError):
        ReplayModel(tmp_path, "a", 1).complete(REQUEST)


class FakeLive:
    """Stands for AnthropicModel: answers from a list and keeps the raw message."""

    def __init__(self, *raw: Json) -> None:
        self.settings, self.raw = MODEL_SETTINGS, list(raw)
        self.last_raw: Json | None = None

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.last_raw = self.raw.pop(0)
        return parse_response(self.last_raw)


def test_what_record_writes_replay_reads_back_the_same(tmp_path: Path) -> None:
    recorder = RecordingModel(FakeLive(FIRST, SECOND), tmp_path, "a", 1)
    live = [recorder.complete(REQUEST), recorder.complete(REQUEST)]
    recorder.finish()
    path = recording_path(tmp_path, "a", 1)
    assert [json.loads(line)["step"] for line in path.read_text().splitlines()] == [0, 1]
    replay = ReplayModel(tmp_path, "a", 1)
    assert [replay.complete(REQUEST), replay.complete(REQUEST)] == live


def record(tmp_path: Path, *raw: Json) -> RecordingModel:
    recorder = RecordingModel(FakeLive(*raw), tmp_path, "a", 1)
    for _ in raw:
        recorder.complete(REQUEST)
    return recorder


def test_a_new_record_run_replaces_the_old_file(tmp_path: Path) -> None:
    record(tmp_path, FIRST, SECOND).finish()
    record(tmp_path, SECOND).finish()
    assert len(recording_path(tmp_path, "a", 1).read_text().splitlines()) == 1


def test_a_run_that_fails_keeps_the_previous_recording_byte_for_byte(tmp_path: Path) -> None:
    record(tmp_path, FIRST, SECOND).finish()
    path = recording_path(tmp_path, "a", 1)
    before = path.read_bytes()
    record(tmp_path, SECOND)  # a run that raised before its end: never finished
    broken = RecordingModel(FakeLive(SECOND, {"content": "bad"}), tmp_path, "a", 1)
    broken.complete(REQUEST)
    with pytest.raises(ModelUnavailableError):  # the turn fails, the run goes on
        broken.complete(REQUEST)
    with pytest.raises(RecordError, match="a live call failed"):
        broken.finish()
    assert path.read_bytes() == before
    assert [p.name for p in path.parent.iterdir()] == ["run-1.jsonl"]  # no temporary left


class Built:
    """Stands for the AnthropicModel class: remembers how it was built."""

    calls: ClassVar[list[tuple[Any, ...]]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        Built.calls.append((args, kwargs))
        self.settings: ModelSettings = MODEL_SETTINGS
        self.last_raw: Json | None = SECOND

    def complete(self, request: ModelRequest) -> ModelResponse:
        return parse_response(SECOND)


@pytest.fixture
def built(monkeypatch: pytest.MonkeyPatch) -> type[Built]:
    Built.calls = []
    monkeypatch.setattr("dale.brain.infrastructure.anthropic_model.AnthropicModel", Built)
    return Built


def test_replay_never_builds_the_live_model(tmp_path: Path, built: type[Built]) -> None:
    write(tmp_path, [FIRST])
    model_factory(Mode.REPLAY, tmp_path, "a", 1)().complete(REQUEST)
    assert built.calls == []


def test_live_builds_the_adapter_with_the_settings_only_and_writes_nothing(
    tmp_path: Path, built: type[Built]
) -> None:
    model_factory(Mode.LIVE, tmp_path, "a", 1)().complete(REQUEST)
    assert built.calls == [((), {"settings": MODEL_SETTINGS})] and list(tmp_path.iterdir()) == []


def test_record_builds_the_adapter_with_the_settings_only_and_writes_the_file(
    tmp_path: Path, built: type[Built]
) -> None:
    other = replace(MODEL_SETTINGS, model="claude-sonnet-5-5")
    model = model_factory(Mode.RECORD, tmp_path, "a", 1, other)()
    model.complete(REQUEST)
    assert built.calls == [((), {"settings": other})] and isinstance(model, RecordingModel)
    model.finish()
    assert json.loads(recording_path(tmp_path, "a", 1).read_text())["message"] == SECOND


def test_the_flags_pick_the_mode_and_record_alone_is_refused() -> None:
    assert mode_from_flags(False, False) is Mode.REPLAY
    assert mode_from_flags(True, False) is Mode.LIVE
    assert mode_from_flags(True, True) is Mode.RECORD
    with pytest.raises(ValueError, match="--record needs --live"):
        mode_from_flags(False, True)


def test_record_without_live_stops_the_session_before_any_test() -> None:
    """A fresh pytest: no database, no model; the usage error comes first."""
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "evals", "--record"],
        capture_output=True,
        check=False,
        cwd=Path(__file__).parents[3],
    )
    assert done.returncode == 4 and b"--record needs --live" in done.stderr


def test_only_the_live_modes_lift_the_socket_host_restriction() -> None:
    assert [lifts_host_restriction(mode) for mode in Mode] == [False, True, True]


PROBE = """
import pytest, pytest_socket

def pytest_sessionstart(session):
    print("force_enabled", session.config.stash[pytest_socket._STASH_KEY].socket_force_enabled)
    pytest.exit("probe", returncode=0)
"""


@pytest.mark.parametrize(
    ("flags", "lifted"),
    [([], False), (["--model", "claude-sonnet-5-5"], False), (["--live"], True)],
)
def test_pytest_socket_reads_the_lifted_option_and_replay_keeps_it_off(
    tmp_path: Path, flags: list[str], lifted: bool
) -> None:
    """A fresh pytest that stops at session start, before any collection: no model call."""
    (tmp_path / "socket_probe.py").write_text(PROBE, encoding="utf-8")
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "evals",
            *flags,
            "-p",
            "socket_probe",
            "-p",
            "no:cacheprovider",
        ],
        capture_output=True,
        check=False,
        cwd=Path(__file__).parents[3],
        env=os.environ | {"PYTHONPATH": str(tmp_path)},
    )
    assert f"force_enabled {lifted}".encode() in done.stdout, done.stdout


def test_a_path_is_shown_relative_to_the_repository_and_never_absolute(tmp_path: Path) -> None:
    inside = REPO_ROOT / "evals" / "recordings" / "a" / "run-1.jsonl"
    assert shown_path(inside) == "evals/recordings/a/run-1.jsonl"
    assert shown_path(tmp_path / "a" / "run-1.jsonl") == f"{tmp_path.name}/a/run-1.jsonl"
    assert shown_path(Path("/run-1.jsonl")) == "run-1.jsonl"


def test_a_record_error_and_a_replay_error_name_their_file_without_an_absolute_path(
    tmp_path: Path,
) -> None:
    broken = RecordingModel(FakeLive({"content": "bad"}), tmp_path, "a", 1)
    with pytest.raises(ModelUnavailableError):
        broken.complete(REQUEST)
    with pytest.raises(RecordError) as record_error:
        broken.finish()
    with pytest.raises(ReplayError) as replay_error:
        ReplayModel(tmp_path, "a", 1).complete(REQUEST)
    for error in (record_error.value, replay_error.value):
        assert str(tmp_path) not in str(error) and f"{tmp_path.name}/a/run-1.jsonl" in str(error)


def test_snapshot_ids_are_the_distinct_message_models_of_the_suite_s_recordings(
    tmp_path: Path,
) -> None:
    """S16.7: the model ids the API answered with, read from the runs of the given cases."""
    for case, run, model in (("a", 1, "m-2"), ("a", 2, "m-1"), ("b", 3, "m-2"), ("c", 1, "m-9")):
        path = recording_path(tmp_path, case, run)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"message": {"model": model}}) + "\n" + "not json\n")
    (tmp_path / "a" / "run-4.jsonl").write_text(json.dumps({"message": {"model": "m-4"}}))
    assert snapshot_ids(tmp_path, ["a", "b", "missing"]) == ["m-1", "m-2"]


def test_the_haiku_recordings_name_one_snapshot() -> None:
    root = REPO_ROOT / "evals" / "recordings" / MODEL_SETTINGS.model
    cases = [path.name for path in root.iterdir() if path.is_dir()]
    assert snapshot_ids(root, cases) == [MODEL_SETTINGS.model]

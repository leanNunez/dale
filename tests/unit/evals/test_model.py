"""The replayed eval model (tasks 12.1, 12.3; D9, R13): replay answers from (case, run, step)
and the fingerprint and from nothing else."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from dale.brain.application.model_port import MODEL_SETTINGS, ModelRequest, parse_response
from dale.brain.application.prompt import fingerprint, system_blocks
from dale.brain.application.tools import TOOL_SCHEMAS
from evals.harness.model import (
    ReplayError,
    ReplayModel,
    messages_digest,
    recording_path,
    request_fingerprint,
)
from tests.unit.brain.test_model_port import SEARCH, message

REQUEST = ModelRequest(system_blocks("Distribuidora El Hornero"), TOOL_SCHEMAS, ({"role": "user"},))
FIRST, SECOND = message(SEARCH), message({"type": "text", "text": "Listo."}, stop="end_turn")


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

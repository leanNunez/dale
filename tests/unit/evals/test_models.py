"""The model dimension of the evals (task 8a.1; D23, S13.8): the compared models, the option
that picks one, where its recordings live and that a recording never replays under another."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from dale.brain.application.model_port import MODEL_SETTINGS, ModelRequest, ModelSettings
from dale.brain.application.prompt import system_blocks
from dale.brain.application.tools import TOOL_SCHEMAS
from evals.harness.model import (
    RECORDINGS,
    Mode,
    ReplayError,
    ReplayModel,
    messages_digest,
    model_factory,
    recording_path,
    recordings_dir,
    request_fingerprint,
)
from evals.harness.models import (
    COMPARED,
    DEFAULT_MODEL,
    HAIKU,
    SONNET,
    UnknownModelError,
    settings_for,
)
from tests.unit.brain.test_model_port import SEARCH, message

pytest_plugins = ["pytester"]
REQUEST = ModelRequest(system_blocks("Distribuidora El Hornero"), TOOL_SCHEMAS, ({"role": "user"},))
ANSWER = message(SEARCH)


def test_the_compared_models_differ_from_the_shipped_settings_only_in_the_model() -> None:
    assert set(COMPARED) == {HAIKU, SONNET} == {"claude-haiku-5-5", "claude-sonnet-5-5"}
    for model, settings in COMPARED.items():
        assert settings == replace(MODEL_SETTINGS, model=model)
        assert settings.effort == "medium"  # the same for both: only the model is compared
    assert COMPARED[HAIKU] == MODEL_SETTINGS  # the v0.1 settings, so its recordings still hold


def test_the_default_model_is_the_shipped_one_and_is_compared() -> None:
    assert MODEL_SETTINGS.model == DEFAULT_MODEL
    assert settings_for(DEFAULT_MODEL) == MODEL_SETTINGS


def test_a_model_that_is_not_compared_has_no_settings() -> None:
    with pytest.raises(UnknownModelError, match="not a compared model"):
        settings_for("claude-other")


def test_the_recordings_of_a_model_live_under_its_own_directory() -> None:
    assert recordings_dir(HAIKU) == RECORDINGS / "claude-haiku-5-5"
    assert recordings_dir(SONNET, Path("r")) == Path("r/claude-sonnet-5-5")
    assert recording_path(recordings_dir(HAIKU), "min-by-count", 2) == (
        RECORDINGS / "claude-haiku-5-5" / "min-by-count" / "run-2.jsonl"
    )
    with pytest.raises(UnknownModelError):
        recordings_dir("../claude-haiku-5-5")  # a name that is not compared is never a path


def test_the_fingerprint_names_the_model() -> None:
    fingerprints = {request_fingerprint(REQUEST, settings) for settings in COMPARED.values()}
    assert len(fingerprints) == len(COMPARED)


def record(root: Path, settings: ModelSettings) -> None:
    """One step recorded against `settings`, as the record mode writes it."""
    path = recording_path(root, "a", 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = {"case": "a", "run": 1, "step": 0, "message": ANSWER}
    line |= {"fingerprint": request_fingerprint(REQUEST, settings)}
    line |= {"messages": messages_digest(REQUEST)}
    path.write_text(json.dumps(line) + "\n", encoding="utf-8")


def test_a_recording_replays_under_its_own_model(tmp_path: Path) -> None:
    record(tmp_path, COMPARED[SONNET])
    assert ReplayModel(tmp_path, "a", 1, COMPARED[SONNET]).complete(REQUEST).stop_reason


def test_a_recording_replayed_under_another_model_fails_its_fingerprint(tmp_path: Path) -> None:
    """S13.8, both directions: the settings the replay is built with are what is checked."""
    record(tmp_path, COMPARED[HAIKU])
    with pytest.raises(ReplayError, match="re-record required"):
        ReplayModel(tmp_path, "a", 1, COMPARED[SONNET]).complete(REQUEST)
    record(tmp_path, COMPARED[SONNET])
    with pytest.raises(ReplayError, match="re-record required"):
        ReplayModel(tmp_path, "a", 1, COMPARED[HAIKU]).complete(REQUEST)


def test_the_factory_hands_its_settings_to_the_replay(tmp_path: Path) -> None:
    record(tmp_path, COMPARED[HAIKU])
    assert model_factory(Mode.REPLAY, tmp_path, "a", 1, COMPARED[HAIKU])().complete(REQUEST)
    with pytest.raises(ReplayError, match="re-record required"):
        model_factory(Mode.REPLAY, tmp_path, "a", 1, COMPARED[SONNET])().complete(REQUEST)


PROBE = """
def test_probe(model_settings):
    print("PROBE", model_settings.model, model_settings.effort)
"""


def probe(pytester: pytest.Pytester, *args: str) -> pytest.RunResult:
    pytester.makepyfile(test_probe=PROBE)
    return pytester.runpytest("-p", "evals.conftest", "-s", *args)


def test_the_option_defaults_to_the_shipped_model(pytester: pytest.Pytester) -> None:
    result = probe(pytester)
    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines([f"*PROBE {MODEL_SETTINGS.model} {MODEL_SETTINGS.effort}*"])


def test_the_option_picks_a_compared_model_with_the_same_effort(pytester: pytest.Pytester) -> None:
    result = probe(pytester, "--model", SONNET)
    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines([f"*PROBE {SONNET} medium*"])


def test_the_option_refuses_a_model_that_is_not_compared(pytester: pytest.Pytester) -> None:
    result = probe(pytester, "--model", "claude-other")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert "invalid choice" in result.stderr.str()

"""Every case in `evals/cases`, three runs each, in the mode the options pick: replay by default
(R13, S13.4). A run passes when its final state grades clean (the grader never reads the tool
path). With `--report <version>` each run's record is also collected for the report (task 13).
In replay, a run listed in the model's own `evals/recordings/<model>/known_misses.toml` must fail
exactly as recorded and never be a false confirmation; every other run must pass."""

import pytest
from sqlalchemy import Engine

from dale.brain.application.model_port import ModelSettings
from evals.harness.case import Case, load_cases
from evals.harness.collect import CASES_DIR, evaluate
from evals.harness.known_misses import KnownMiss, load_known_misses
from evals.harness.model import Mode, model_factory, recordings_dir
from evals.harness.runner import Env
from evals.harness.sink import RunSink
from tests.conftest import role_url

pytestmark = [pytest.mark.eval, pytest.mark.integration]
CASES = load_cases(CASES_DIR)  # raises when there is no case: an empty suite never passes


@pytest.fixture(scope="module")
def known_misses(model_settings: ModelSettings) -> dict[tuple[str, int], KnownMiss]:
    """Only the list of the model under test: a miss of one model never excuses the other."""
    return load_known_misses(recordings_dir(model_settings.model) / "known_misses.toml", CASES)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
@pytest.mark.parametrize("run", [1, 2, 3])
def test_case(
    case: Case,
    run: int,
    engines: dict[str, Engine],
    mode: Mode,
    run_sink: RunSink | None,
    model_settings: ModelSettings,
    known_misses: dict[tuple[str, int], KnownMiss],
) -> None:
    env = Env(engines["dale_app"], role_url("dale_verifier"))
    factory = model_factory(
        mode, recordings_dir(model_settings.model), case.id, run, model_settings
    )
    result = evaluate(case, run, env, factory, run_sink)
    miss = known_misses.get((case.id, run)) if mode is Mode.REPLAY else None
    if miss is None:
        assert result.passed, "; ".join(result.problems)
        return
    assert not result.false_confirmation, f"a known miss became a false confirmation: {miss}"
    assert result.problems == miss.problems, "; ".join(result.problems)

"""Every case in `evals/cases`, three runs each, in the mode the options pick: replay by default
(R13, S13.4). A run passes when its final state grades clean (the grader never reads the tool
path). With `--report <version>` each run's record is also collected for the report (task 13)."""

import pytest
from sqlalchemy import Engine

from evals.harness.case import Case, load_cases
from evals.harness.collect import CASES_DIR, evaluate
from evals.harness.model import RECORDINGS, Mode, model_factory
from evals.harness.runner import Env
from evals.harness.sink import RunSink
from tests.conftest import role_url

pytestmark = [pytest.mark.eval, pytest.mark.integration]
CASES = load_cases(CASES_DIR)  # raises when there is no case: an empty suite never passes


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
@pytest.mark.parametrize("run", [1, 2, 3])
def test_case(
    case: Case, run: int, engines: dict[str, Engine], mode: Mode, run_sink: RunSink | None
) -> None:
    env = Env(engines["dale_app"], role_url("dale_verifier"))
    result = evaluate(case, run, env, model_factory(mode, RECORDINGS, case.id, run), run_sink)
    assert result.passed, "; ".join(result.problems)

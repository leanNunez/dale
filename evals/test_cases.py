"""Every case in `evals/cases`, three runs each, in the mode the options pick: replay by default
(R13, S13.4). A run passes when its final state grades clean (the grader never reads the tool
path). Metrics over the runs come in task 13."""

from pathlib import Path

import pytest
from sqlalchemy import Engine

from evals.harness.case import Case, load_cases
from evals.harness.grader import grade
from evals.harness.model import RECORDINGS, Mode, model_factory
from evals.harness.runner import Env, run_case
from tests.conftest import role_url

pytestmark = [pytest.mark.eval, pytest.mark.integration]
CASES = load_cases(Path(__file__).parent / "cases")  # no case yet: the test is skipped


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
@pytest.mark.parametrize("run", [1, 2, 3])
def test_case(case: Case, run: int, engines: dict[str, Engine], mode: Mode) -> None:
    env = Env(engines["dale_app"], role_url("dale_verifier"))
    state = run_case(case, env, model_factory(mode, RECORDINGS, case.id, run))
    result = grade(case, state)
    assert result.passed, "; ".join(result.problems)

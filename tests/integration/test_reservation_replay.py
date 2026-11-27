"""The reservation bound against every committed recording (DD38, design §10 and §13): each
recorded call of each compared model is replayed through the eval runner, and the reservation
of the request the brain really built is at least the cost of the usage the API reported, and
the byte bound is at least its prompt tokens. Every recorded step must be asked for, so no call
goes unchecked. The verifier is not what this checks and calls no model, so a fixed verdict
stands in for its process."""

from dataclasses import dataclass, field

import pytest
from sqlalchemy import Engine

from dale.apps.demo.ledger import cost_micros, prompt_bound, reserve_micros
from dale.apps.demo.prices import PRICES
from dale.apps.verifier_runner import VerifierVerdict
from dale.brain.application.model_port import ModelRequest, ModelResponse, ModelSettings
from evals.harness import runner
from evals.harness.case import load_cases
from evals.harness.collect import CASES_DIR
from evals.harness.model import Mode, ReplayModel, recording_path, recordings_dir, unrecorded
from evals.harness.models import COMPARED
from evals.harness.runner import Env, run_case
from tests.conftest import role_url

pytestmark = pytest.mark.integration
CASES = load_cases(CASES_DIR)
NO_VERDICT = VerifierVerdict(
    verdict="unverifiable",
    reason="not run",
    findings=(),
    false_confirmations=0,
    unexpected_writes=0,
    stored_orders=(),
)


@dataclass
class Checked:
    calls: int = 0
    worst_cost_ratio: float = 0.0
    worst_token_ratio: float = 0.0
    over: list[str] = field(default_factory=list)


class Probe:
    """The replay, plus the bound checked on each request it answers."""

    def __init__(self, inner: ReplayModel, settings: ModelSettings, where: str, seen: Checked):
        self._inner, self._settings, self._where, self._seen = inner, settings, where, seen
        self._step = 0

    def complete(self, request: ModelRequest) -> ModelResponse:
        response = self._inner.complete(request)
        prices, used, seen = PRICES[self._settings.model], response.usage, self._seen
        reserved = reserve_micros(request, self._settings.max_tokens, prices)
        cost, bound = cost_micros(used, prices), prompt_bound(request)
        prompt = used.input_tokens + used.cache_creation_input_tokens + used.cache_read_input_tokens
        seen.calls, self._step = seen.calls + 1, self._step + 1
        seen.worst_cost_ratio = max(seen.worst_cost_ratio, cost / reserved)
        seen.worst_token_ratio = max(seen.worst_token_ratio, prompt / bound)
        if cost > reserved or prompt > bound or used.output_tokens > self._settings.max_tokens:
            seen.over.append(
                f"{self._where} call {self._step}: {cost}/{reserved}, {prompt}/{bound}"
            )
        return response

    def finish(self) -> None:
        self._inner.finish()


def recorded_calls(model: str) -> int:
    root = recordings_dir(model)
    paths = (recording_path(root, case.id, run) for case in CASES for run in (1, 2, 3))
    return sum(len(p.read_text(encoding="utf-8").splitlines()) for p in paths if p.is_file())


@pytest.mark.parametrize("model", sorted(COMPARED))
def test_every_recorded_call_costs_at_most_its_reservation(
    db: Engine, model: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "run_verifier", lambda request, url: NO_VERDICT)
    settings, root, seen = COMPARED[model], recordings_dir(model), Checked()
    env = Env(db, role_url("dale_verifier"))
    for case in CASES:
        if unrecorded(Mode.REPLAY, root, case.id):
            continue
        for run in (1, 2, 3):
            where = f"{model}/{case.id}/run-{run}"

            def build(case_id: str = case.id, run: int = run, where: str = where) -> Probe:
                return Probe(ReplayModel(root, case_id, run, settings), settings, where, seen)

            state = run_case(case, env, build)
            assert state.harness_error is None, f"{where}: {state.harness_error}"
    assert seen.calls == recorded_calls(model) > 0
    assert not seen.over, seen.over
    assert seen.worst_cost_ratio <= 1.0
    print(f"{model}: {seen.calls} calls, cost/reservation at most {seen.worst_cost_ratio:.3f},")
    print(f"prompt tokens/bound at most {seen.worst_token_ratio:.3f}")

"""Writes the hand-written recordings of the harness fixtures (task 12.6, D9) through the real
recorder: each run goes through `run_case` on the test database, with these messages standing
in for the live model, so every line carries the CURRENT fingerprint and the digest of the
messages the run really sent, tool results included. Run it after any change to the prompt,
the tools, the model settings, the seed or the fixture cases, with the DALE_TEST_ADMIN_URL the
tests use and no test session running (it rebuilds their database):

    uv run python -m tests.fixtures.evals.regenerate

`fixture-order` takes a different tool path in run 3 (it also asks for prices) and
`fixture-discount` in run 3 (it searches first): same final state, so all three runs pass."""

from functools import partial
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine

from dale.brain.application.model_port import (
    MODEL_SETTINGS,
    Json,
    ModelRequest,
    ModelResponse,
    parse_response,
)
from dale.erp_sim.infrastructure.seed import el_hornero
from evals.harness.case import load_cases
from evals.harness.model import RecordingModel
from evals.harness.runner import Env, run_case
from tests.conftest import fresh_database, role_url

FIXTURES = Path(__file__).parent
RECORDINGS = FIXTURES / "recordings"
COLA = str(el_hornero.row_id("product", "COLA-225"))


def message(stop: str, *blocks: Json) -> Json:
    usage = {"input_tokens": 1_200, "output_tokens": 40, "cache_read_input_tokens": 900}
    return {"content": list(blocks), "stop_reason": stop, "usage": usage}


def call(name: str, **tool_input: Any) -> Json:
    return message(
        "tool_use",
        {"type": "tool_use", "id": f"toolu_{name}", "name": name} | {"input": tool_input},
    )


def says(text: str) -> Json:
    return message("end_turn", {"type": "text", "text": text})


SEARCH = call("search_products", query="cola dos y cuarto")
PREPARE = call("prepare_order", lines=[{"product_id": COLA, "quantity": 20}])
PRICES = call("get_prices", product_ids=[COLA])
HANDOFF = call("request_human_handoff", reason="exception_request", note="pide 30% de descuento")
STEPS: dict[str, list[list[Json]]] = {
    "fixture-order": [
        [SEARCH, PREPARE, says("Te armé la propuesta: confirmala con la tecla Dale.")],
        [SEARCH, PREPARE, says("Listo, armé la propuesta. Apretá la tecla Dale.")],
        [SEARCH, PRICES, PREPARE, says("Dejé la propuesta lista, confirmala con Dale.")],
    ],
    "fixture-discount": [
        [HANDOFF, says("Lo dejé registrado.")],
        [HANDOFF, says("Pasé tu pedido a una persona.")],
        [SEARCH, HANDOFF, says("Lo dejé registrado.")],
    ],
}


class Scripted:
    """Stands for the live adapter: answers with the hand-written messages, in order."""

    def __init__(self, steps: list[Json]) -> None:
        self.settings, self.steps = MODEL_SETTINGS, list(steps)
        self.last_raw: Json | None = None

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.last_raw = self.steps.pop(0)  # an IndexError: the run asked for more than written
        return parse_response(self.last_raw)


def write_recordings(root: Path, env: Env) -> None:
    for case in load_cases(FIXTURES / "cases"):
        for run, steps in enumerate(STEPS[case.id], 1):
            scripted = Scripted(steps)
            run_case(case, env, partial(RecordingModel, scripted, root, case.id, run))
            if scripted.steps:
                raise ValueError(f"{case.id} run {run}: {len(scripted.steps)} steps never asked")


if __name__ == "__main__":
    with fresh_database():
        engine = create_engine(role_url("dale_app"))
        try:
            write_recordings(RECORDINGS, Env(engine, role_url("dale_verifier")))
        finally:
            engine.dispose()

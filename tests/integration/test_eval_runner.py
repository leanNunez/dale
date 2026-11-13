"""The eval runner on the seeded DB with a scripted model (task 12.2, B21, B24): every run
starts from a reseeded erp and an empty brain, then converses, presses, verifies and reads
the final state back."""

from datetime import date
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine

from dale.brain.infrastructure import tables as brain
from dale.brain.infrastructure.reset import reset_brain
from dale.erp_sim.infrastructure.seed import el_hornero
from dale.shared.shown_events import AssistantText
from evals.harness.case import Case
from evals.harness.runner import Env, RunState, run_case
from tests.conftest import role_url
from tests.integration.test_proposals import COLA, NOW
from tests.unit.brain.test_loop import ScriptedModel, calls, says

pytestmark = pytest.mark.integration
ORDER = (
    calls("search_products", query="cola dos y cuarto"),
    calls("prepare_order", lines=[{"product_id": str(COLA), "quantity": 20}]),
    says("Te armé la propuesta: confirmala con la tecla Dale."),
)
HANDOFF = (
    calls("request_human_handoff", reason="exception_request", note="pide descuento"),
    says("Lo dejé registrado."),
)
EXPECT: dict[str, Any] = {"orders": [], "handoff": None, "pending_proposal": False}


def case(**changes: Any) -> Case:
    base = {"id": "a", "suite": "core", "now": NOW, "customer": "C-001", "press_dale": False}
    return Case.model_validate({"message": "quiero 20 colas", "expect": EXPECT} | base | changes)


def run(db: Engine, one: Case, *script: Any) -> RunState:
    return run_case(one, Env(db, role_url("dale_verifier")), lambda: ScriptedModel(*script))


def brain_rows(db: Engine) -> dict[str, int]:
    with db.connect() as conn:
        counts = (
            (t.name, sa.select(sa.func.count()).select_from(t))
            for t in brain.METADATA.tables.values()
        )
        return {name: conn.execute(query).scalar_one() for name, query in counts}


def test_a_run_presses_the_key_and_reads_back_a_verified_order(db: Engine) -> None:
    state = run(db, case(press_dale=True), *ORDER)
    [order] = state.orders
    assert order.lines == (("COLA-225", 20, 245_000),)
    assert (order.total_cents, order.delivery_date) == (4_900_000, date(2026, 11, 19))
    assert state.verdict.verified and state.failures == ()
    assert state.list_prices["COLA-225"] == 245_000 and state.minimum_cents == 3_000_000
    assert state.list_prices_by_id[COLA] == 245_000
    assert [type(e).__name__ for e in state.shown] == [
        "ProposalSummary",
        "AssistantText",
        "OrderConfirmed",
    ]
    assert len(state.usage) == 3
    [stored] = state.proposals  # read back from the brain's rows, in the summary's shape
    assert (stored.status, stored.summary) == ("confirmed", state.shown[0])
    assert state.delivery_date == date(2026, 11, 19)  # management's rule at the case's `now`


def test_the_key_is_not_pressed_unless_the_case_says_so(db: Engine) -> None:
    state = run(db, case(press_dale=False), *ORDER)
    assert state.orders == () and state.verdict.verdict == "nothing_confirmed"
    assert [p.status for p in state.proposals] == ["prepared"]  # left pending


def test_a_press_without_a_proposal_to_press_on_does_nothing(db: Engine) -> None:
    state = run(db, case(press_dale=True), says("¿Qué cola querés?"))
    assert state.orders == () and [type(e).__name__ for e in state.shown] == ["AssistantText"]


def test_a_handoff_is_read_back_by_its_reason(db: Engine) -> None:
    state = run(db, case(message="dame descuento"), *HANDOFF)
    assert state.handoffs == ("exception_request",) and state.orders == ()


def test_history_turns_go_through_the_same_model_before_the_message(db: Engine) -> None:
    model = ScriptedModel(says("uno"), says("dos"))
    one = case(history=("hola",))
    state = run_case(one, Env(db, role_url("dale_verifier")), lambda: model)
    assert len(model.requests) == 2 and len(state.usage) == 2
    assert state.shown == (AssistantText("uno"), AssistantText("dos"))


def test_seed_overrides_are_applied_before_the_run(db: Engine) -> None:
    centro = {
        "zones": {"Centro": {"min_order_amount_cents": 1_000_000_000, "cutoff_time": "10:00"}}
    }
    state = run(db, case(seed_overrides=centro), says("hola"))
    assert state.minimum_cents == 1_000_000_000


def test_the_next_case_starts_with_no_brain_rows_and_no_orphaned_order(db: Engine) -> None:
    """B24: case A leaves a proposal, an order and a handoff; case B finds none of them."""
    run(db, case(id="a", press_dale=True), *ORDER)
    assert brain_rows(db)["order_proposal"] == 1
    run(db, case(id="a2", message="dame descuento"), *HANDOFF)  # leaves its own handoff
    state = run(db, case(id="b", message="hola"), says("¿Qué necesitás?"))
    rows = brain_rows(db)
    assert (rows["order_proposal"], rows["order_proposal_line"], rows["handoff_request"]) == (
        0,
        0,
        0,
    )
    assert rows["conversation"] == 1  # only case B's own
    assert state.orders == () and state.handoffs == ()
    with db.connect() as conn:
        orphans = sa.select(brain.order_proposal.c.order_id).where(
            brain.order_proposal.c.order_id.is_not(None)
        )
        assert conn.execute(orphans).all() == []


def test_the_brain_reset_clears_one_company_only(db: Engine) -> None:
    other = UUID(int=99)
    row = {"company_id": other, "id": UUID(int=1), "customer_id": UUID(int=2), "channel": "x"}
    with db.begin() as conn:
        conn.execute(sa.insert(brain.conversation), row | {"started_at": NOW})
    reset_brain(db, el_hornero.COMPANY_ID)
    assert brain_rows(db)["conversation"] == 1
    reset_brain(db, other)
    assert brain_rows(db)["conversation"] == 0


def test_an_unknown_customer_fails_the_run(db: Engine) -> None:
    with pytest.raises(ValueError, match="not an active customer"):
        run(db, case(customer="C-999"), says("x"))


class Finishing(ScriptedModel):
    finished = 0

    def finish(self) -> None:
        self.finished += 1


def test_a_model_with_finish_is_told_once_the_whole_run_is_over(db: Engine) -> None:
    """Replay fails the run there on an unused step; record writes its file only then."""
    model = Finishing(says("hola"))
    state = run_case(case(), Env(db, role_url("dale_verifier")), lambda: model)
    assert model.finished == 1 and state.harness_error is None

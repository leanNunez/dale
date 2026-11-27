"""A turn cut by its deadline after it showed a proposal (R9 S9.7, S9.8; v0.1 B75; ADR 0011),
through the composed terminal on the seeded DB: the cut turn confirms nothing, a typed "dale"
confirms nothing, and only the Dale key confirms, after management revalidates."""

import pytest
import sqlalchemy as sa
from prompt_toolkit.input import PipeInput, create_pipe_input
from prompt_toolkit.output import DummyOutput
from sqlalchemy import Engine

from dale.apps import terminal
from dale.apps.verifier_runner import run_verifier
from dale.brain.application.model_port import DeadlineExceededError
from dale.channels.common.pending import Pending
from dale.channels.terminal.keys import TerminalInput
from dale.channels.terminal.session import TerminalSession
from dale.erp_sim.infrastructure import tables as erp
from dale.shared.clock import FrozenClock
from dale.shared.customer_input import CustomerInput
from dale.shared.errors import ErrorCode, Ok, message_for
from tests.conftest import role_url
from tests.integration.test_proposals import C001, COLA, NOW
from tests.integration.test_terminal_app import CONFIRMED, F2
from tests.unit.brain.test_loop import ScriptedModel, calls, customer_texts, says

pytestmark = pytest.mark.integration
CUT = message_for(ErrorCode.TURN_DEADLINE_EXCEEDED)


def orders(db: Engine) -> list[object]:
    with db.connect() as conn:
        return list(conn.execute(sa.select(erp.sales_order.c.customer_id)).scalars())


def test_a_summary_shown_before_the_deadline_is_confirmed_only_by_the_dale_key(db: Engine) -> None:
    model = ScriptedModel(
        calls("search_products", query="cola dos y cuarto"),
        calls("prepare_order", lines=[{"product_id": str(COLA), "quantity": 20}]),
        DeadlineExceededError("attempt cut at the deadline"),  # the third call of the turn
        says("Para confirmarlo usá la tecla Dale."),
    )
    composed = terminal.compose(
        db,
        "el-hornero",
        "C-001",
        lambda: model,
        FrozenClock(NOW),
        verifier=lambda r: run_verifier(r, role_url("dale_verifier")),
        turn_seconds=90,
    )
    assert isinstance(composed, Ok)
    chunks = ["quiero 20 colas de dos y cuarto\r", "dale\r", F2]
    printed, before_f2, pending = list[str](), list[list[object]](), Pending()
    with create_pipe_input() as pipe:
        typed = TerminalInput(pending, pipe, DummyOutput())

        def read(pipe: PipeInput = pipe) -> CustomerInput:
            if not chunks:
                raise EOFError
            if chunks[0] == F2:
                before_f2.append(orders(db))
            pipe.send_text(chunks.pop(0))
            return typed.read()

        TerminalSession(composed.value, read, printed.append, pending).run()

    cut = printed.index(CUT)  # S9.7: the cut turn shows the catalog message
    assert any(p.startswith("Propuesta de pedido") for p in printed[:cut])  # shown before it
    assert before_f2 == [[]]  # neither the cut turn nor the typed "dale" made an order
    assert customer_texts(model.requests[-1])[-1] == "dale"  # typed text reached only the model
    assert printed[-2:] == [
        CONFIRMED,
        "Verificación: VERIFICADO. El pedido está en la base de gestión tal como se mostró.",
    ]
    assert orders(db) == [C001]
    assert all(r.deadline is not None for r in model.requests)  # every request carries it
    assert [t.failure for t in composed.value.turns] == [ErrorCode.TURN_DEADLINE_EXCEEDED, None]

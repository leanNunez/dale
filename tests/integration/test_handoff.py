"""Handoffs on a real database (R7, R15, D1): one row with a reason for the session's own
conversation, no order or proposal, and no promise of a person when the write fails."""

from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine

from dale.brain.application.tools import HANDOFF_NOTICE, Tools
from dale.brain.domain.handoff import HandoffReason
from dale.brain.domain.session import SessionContext
from dale.brain.infrastructure import tables as t
from dale.brain.infrastructure.handoff_repository import SqlHandoffRepository
from dale.brain.infrastructure.proposal_repository import SqlProposalRepository
from dale.erp_sim.infrastructure import tables as erp
from dale.erp_sim.infrastructure.facade import SqlErpFacade
from dale.shared.clock import FrozenClock
from dale.shared.ids import ConversationId, CustomerId, SequentialIdGenerator
from dale.shared.shown_events import HandoffNotice
from tests.integration.test_proposals import C001, HORNERO, NOW, TWIN, rows, session

pytestmark = pytest.mark.integration
GAUCHADA = {"reason": "exception_request", "note": "dale, haceme la gauchada con el mínimo"}
WRITTEN = ("company_id", "conversation_id", "customer_id", "reason", "note")


def handoff(db: Engine, at: SessionContext, tool_input: Any, writes: Engine | None = None) -> Any:
    tools = Tools(
        at,
        SqlErpFacade(db, FrozenClock(NOW)),
        SqlProposalRepository(db),
        SequentialIdGenerator(),
        SqlHandoffRepository(writes or db),
    )
    return tools.run("request_human_handoff", tool_input)


def test_a_gauchada_writes_one_handoff_with_its_reason_and_no_order(db: Engine) -> None:
    at = session(db)
    outcome = handoff(db, at, GAUCHADA)  # S7.1 mechanics
    assert not outcome.is_error and outcome.shown == (HandoffNotice(HANDOFF_NOTICE),)
    row = (HORNERO, at.conversation_id, C001, "exception_request", GAUCHADA["note"])
    assert rows(db, t.handoff_request, *WRITTEN) == [row]
    assert rows(db, t.order_proposal, "id") == rows(db, erp.sales_order, "id") == []


@pytest.mark.parametrize("note", ["x" * 501, "dale\x00con el mínimo"])
def test_a_note_over_500_characters_or_with_a_nul_writes_nothing(db: Engine, note: str) -> None:
    """B68: a NUL would make Postgres raise a DataError out of the tool; it never gets there."""
    outcome = handoff(db, session(db), GAUCHADA | {"note": note})
    assert outcome.is_error and '"invalid_tool_input"' in outcome.content and outcome.shown == ()
    assert rows(db, t.handoff_request, "id") == []


def test_a_failed_write_is_an_error_for_the_model_and_shows_no_notice(db: Engine) -> None:
    """S7.4: the database is unreachable, so nobody can promise that a person will call."""
    down = sa.create_engine(db.url.set(port=1))  # nothing listens there
    try:
        outcome = handoff(db, session(db), GAUCHADA, writes=down)
    finally:
        down.dispose()
    assert outcome.is_error and '"rules_unavailable"' in outcome.content and outcome.shown == ()
    assert rows(db, t.handoff_request, "id") == []


def test_a_twin_company_with_the_same_ids_gets_no_handoff_row(db: Engine) -> None:
    conversation = uuid4()
    session(db, TWIN, conversation)
    ours = session(db, HORNERO, conversation)  # same conversation and customer ids
    SqlHandoffRepository(db).request_handoff(ours, HandoffReason.COMPLAINT, None)
    assert rows(db, t.handoff_request, "company_id", "note") == [(HORNERO, None)]
    only_twin = SessionContext(HORNERO, C001, ConversationId(session(db, TWIN).conversation_id))
    other_customer = SessionContext(HORNERO, CustomerId(uuid4()), ours.conversation_id)
    for wrong in (only_twin, other_customer):
        with pytest.raises(RuntimeError, match="conversation row"):  # a wiring bug
            SqlHandoffRepository(db).request_handoff(wrong, HandoffReason.OTHER, "x")
    assert len(rows(db, t.handoff_request, "id")) == 1

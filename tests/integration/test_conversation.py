"""The session's conversation row on a real database (B61, R15): opened once, keyed by company,
never taken over by another customer, and opened by the loop before any tool runs, so one full
refused turn ends with its agent_refusal handoff written (D10)."""

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine

from dale.brain.application.prompt import system_blocks
from dale.brain.application.take_turn import TakeTurn
from dale.brain.application.tools import HANDOFF_NOTICE, Tools
from dale.brain.domain.session import SessionContext
from dale.brain.infrastructure import tables as t
from dale.brain.infrastructure.conversation_repository import SqlConversationRepository
from dale.brain.infrastructure.handoff_repository import SqlHandoffRepository
from dale.brain.infrastructure.proposal_repository import SqlProposalRepository
from dale.erp_sim.infrastructure.facade import SqlErpFacade
from dale.shared.clock import FrozenClock
from dale.shared.customer_input import CustomerText
from dale.shared.ids import ConversationId, CustomerId, SequentialIdGenerator
from dale.shared.shown_events import HandoffNotice, ProposalSummary
from tests.integration.test_proposals import C001, COLA, HORNERO, NOW, TWIN, rows
from tests.unit.brain.test_loop import ScriptedModel, calls, says

pytestmark = pytest.mark.integration
COLUMNS = ("company_id", "id", "customer_id", "channel", "started_at")


def conversations(db: Engine) -> SqlConversationRepository:
    return SqlConversationRepository(db, FrozenClock(NOW), "terminal")


def test_opening_twice_writes_one_row_per_company_key(db: Engine) -> None:
    at = SessionContext(HORNERO, C001, ConversationId(uuid4()))
    twin = SessionContext(TWIN, C001, at.conversation_id)  # same id, another company's key
    for session in (at, at, twin):
        conversations(db).open(session)
    expected = {(s.company_id, s.conversation_id, C001, "terminal", NOW) for s in (at, twin)}
    assert set(rows(db, t.conversation, *COLUMNS)) == expected


def test_a_conversation_of_another_customer_is_never_taken_over(db: Engine) -> None:
    at = SessionContext(HORNERO, C001, ConversationId(uuid4()))
    conversations(db).open(at)
    with pytest.raises(RuntimeError, match="another customer"):
        conversations(db).open(SessionContext(HORNERO, CustomerId(uuid4()), at.conversation_id))
    assert rows(db, t.conversation, "customer_id") == [(C001,)]


def loop(db: Engine, *replies: Any) -> tuple[SessionContext, TakeTurn]:
    """A full turn on the real repositories; the loop opens the conversation row itself."""
    at, handoffs = SessionContext(HORNERO, C001, ConversationId(uuid4())), SqlHandoffRepository(db)
    erp, proposals = SqlErpFacade(db, FrozenClock(NOW)), SqlProposalRepository(db)
    tools = Tools(at, erp, proposals, SequentialIdGenerator(), handoffs)
    stores = (conversations(db), handoffs, proposals)
    return at, TakeTurn(at, ScriptedModel(*replies), tools, *stores, system_blocks("El Hornero"))


def test_a_refused_first_turn_opens_the_conversation_and_writes_the_handoff(db: Engine) -> None:
    at, take = loop(db, says("", "refusal"))
    assert take(CustomerText("che")).shown[-1] == HandoffNotice(HANDOFF_NOTICE)
    assert rows(db, t.handoff_request, "conversation_id", "reason") == [
        (at.conversation_id, "agent_refusal")
    ]
    assert rows(db, t.order_proposal, "id") == []


SEARCH = calls("search_products", query="cola dos y cuarto")
PREPARE = calls("prepare_order", lines=[{"product_id": str(COLA), "quantity": 20}])


def test_a_refusal_after_a_prepare_leaves_no_proposal_prepared(db: Engine) -> None:
    """B75: turn 1 shows P1; turn 2 prepares P2, which supersedes P1, and is refused. P2 was
    never shown, so it is withdrawn: nothing is left to confirm, and one handoff is written."""
    _, take = loop(db, SEARCH, PREPARE, says("Te armé la propuesta."), PREPARE, says("", "refusal"))
    [p1] = [e for e in take(CustomerText("20 colas")).shown if isinstance(e, ProposalSummary)]
    refused = take(CustomerText("haceme precio"))
    assert not any(isinstance(e, ProposalSummary) for e in refused.shown)
    statuses = dict(rows(db, t.order_proposal, "id", "status"))
    assert (
        len(statuses) == 2
        and set(statuses.values()) == {"superseded"}
        and p1.proposal_id in statuses
    )
    assert rows(db, t.handoff_request, "reason") == [("agent_refusal",)]
    assert refused.shown[-1] == HandoffNotice(HANDOFF_NOTICE)

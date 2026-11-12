"""Proposals on a real database (R3, R15, D6): server prices, never an order, one prepared
proposal per conversation, and no read or write across companies."""

import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import date, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine

from dale.brain.application.tools import Tools
from dale.brain.domain.proposal import OrderProposal, ProposalLine, ProposalStatus
from dale.brain.domain.session import SessionContext
from dale.brain.infrastructure import tables as t
from dale.brain.infrastructure.proposal_repository import SqlProposalRepository
from dale.erp_sim.infrastructure import tables as erp
from dale.erp_sim.infrastructure.facade import SqlErpFacade
from dale.erp_sim.infrastructure.seed import el_hornero
from dale.shared.clock import FrozenClock
from dale.shared.ids import (
    CompanyId,
    ConversationId,
    CustomerId,
    ProductId,
    SequentialIdGenerator,
    new_proposal_id,
)
from dale.shared.money import Money
from dale.shared.shown_events import ProposalSummary, ShownLine

pytestmark = pytest.mark.integration
HORNERO, TWIN = CompanyId(el_hornero.COMPANY_ID), CompanyId(uuid5(NAMESPACE_URL, "dale:twin"))
NOW = datetime(2026, 11, 18, 9, tzinfo=ZoneInfo(el_hornero.TIMEZONE))  # delivery Thursday 19
C001 = CustomerId(el_hornero.row_id("customer", "C-001"))
COLA = ProductId(el_hornero.row_id("product", "COLA-225"))
DAY = date(2026, 11, 19)


@pytest.fixture
def db(app: Engine) -> Iterator[Engine]:
    yield app
    with app.begin() as conn:  # the brain owns its reset (B24)
        for table in reversed(t.METADATA.sorted_tables):
            conn.execute(sa.delete(table))


def session(db: Engine, company: CompanyId = HORNERO, id: Any = None) -> SessionContext:
    started = SessionContext(company, C001, ConversationId(id or uuid4()))
    row = {"company_id": company, "id": started.conversation_id, "customer_id": C001}
    with db.begin() as conn:
        conn.execute(sa.insert(t.conversation), row | {"channel": "terminal", "started_at": NOW})
    return started


def grounded(db: Engine, at: SessionContext) -> Tools:
    """Tools whose search returned COLA. Ids are sequential, so two Tools reuse the first id."""
    erp_facade, store = SqlErpFacade(db, FrozenClock(NOW)), SqlProposalRepository(db)
    tools = Tools(at, erp_facade, store, SequentialIdGenerator())
    assert not tools.run("search_products", {"query": "cola dos y cuarto"}).is_error
    return tools


def order(tools: Tools, quantity: int, **extra: object) -> Any:
    line = {"product_id": str(COLA), "quantity": quantity} | extra
    outcome = tools.run("prepare_order", {"lines": [line]})
    return outcome.shown[0] if outcome.shown else json.loads(outcome.content)["code"]


def rows(db: Engine, table: sa.Table, *cols: str) -> list[tuple[Any, ...]]:
    with db.connect() as conn:
        return [tuple(r) for r in conn.execute(sa.select(*(table.c[c] for c in cols)))]


def test_a_valid_proposal_is_stored_at_server_prices_and_is_not_an_order(db: Engine) -> None:
    tools = grounded(db, session(db))
    assert order(tools, 20, unit_price=50_000) == "invalid_tool_input"  # S1.2: never stored
    assert rows(db, t.order_proposal, "id") == []
    summary = order(tools, 20)  # S1.1, S3.1
    line = ShownLine(COLA, 20, Money(245_000), Money(4_900_000))
    assert summary == ProposalSummary(summary.proposal_id, (line,), Money(4_900_000), DAY)
    head = rows(db, t.order_proposal, "id", "status", "total_cents", "delivery_date")
    assert head == [(summary.proposal_id, "prepared", 4_900_000, DAY)]  # S3.3
    assert rows(db, t.order_proposal_line, "product_id", "qty", "unit_price_cents") == [
        (COLA, 20, 245_000)
    ]
    assert rows(db, erp.sales_order, "id") == []


def test_a_rule_failure_stores_no_proposal(db: Engine) -> None:
    assert order(grounded(db, session(db)), 1) == "below_minimum_amount"  # S3.2
    assert rows(db, t.order_proposal, "id") == rows(db, t.order_proposal_line, "id") == []


def test_a_new_proposal_supersedes_the_last_one_in_the_same_transaction(db: Engine) -> None:
    at = session(db)
    tools = grounded(db, at)
    first, second = order(tools, 20), order(tools, 30)
    statuses = dict(rows(db, t.order_proposal, "id", "status"))
    assert statuses == {first.proposal_id: "superseded", second.proposal_id: "prepared"}
    with pytest.raises(sa.exc.IntegrityError):  # a key clash is a bug, not an outage
        order(grounded(db, at), 40)  # a second Tools reuses the first id
    assert dict(rows(db, t.order_proposal, "id", "status")) == statuses  # supersede rolled back


def test_a_twin_company_with_the_same_ids_reads_and_supersedes_only_its_own(db: Engine) -> None:
    store, conversation, proposal_id = SqlProposalRepository(db), uuid4(), new_proposal_id()
    for company, qty in ((TWIN, 1), (HORNERO, 20)):
        at = session(db, company, conversation)
        line = ProposalLine(COLA, qty, Money(111_100), Money(111_100 * qty))
        mine = OrderProposal.prepared(proposal_id, at, (line,), line.line_total, DAY, NOW)
        assert store.save_prepared(company, mine) == mine
    ours, twins = store.get(HORNERO, proposal_id), store.get(TWIN, proposal_id)
    assert ours and twins and (ours.lines[0].quantity, twins.lines[0].quantity) == (20, 1)
    newer = OrderProposal.prepared(new_proposal_id(), at, ours.lines, ours.total, DAY, NOW)
    store.save_prepared(HORNERO, newer)
    assert store.get(TWIN, proposal_id) == twins and twins.status is ProposalStatus.PREPARED
    assert store.get(HORNERO, proposal_id) == replace(ours, status=ProposalStatus.SUPERSEDED)

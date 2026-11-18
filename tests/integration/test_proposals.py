"""Proposals on a real database (R3, R15, D6): server prices, never an order, one prepared
proposal per conversation, and no read or write across companies."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine

from dale.brain.application.shown import order_confirmed
from dale.brain.application.tools import Tools
from dale.brain.domain.proposal import OrderProposal, ProposalLine, ProposalStatus
from dale.brain.domain.session import SessionContext
from dale.brain.infrastructure import tables as t
from dale.brain.infrastructure.handoff_repository import SqlHandoffRepository
from dale.brain.infrastructure.proposal_repository import SqlProposalRepository
from dale.erp_sim.infrastructure import tables as erp
from dale.erp_sim.infrastructure.facade import SqlErpFacade
from dale.erp_sim.infrastructure.seed import el_hornero
from dale.erp_sim.public import ConfirmLine, ConfirmRequest, OrderConfirmation
from dale.shared.clock import FrozenClock
from dale.shared.errors import Ok
from dale.shared.ids import (
    CompanyId,
    ConversationId,
    CustomerId,
    IdGenerator,
    OrderId,
    ProductId,
    SequentialIdGenerator,
    Uuid4Generator,
    new_proposal_id,
)
from dale.shared.money import Money
from dale.shared.shown_events import ProposalSummary, SummaryLine

pytestmark = pytest.mark.integration
HORNERO, TWIN = CompanyId(el_hornero.COMPANY_ID), CompanyId(uuid5(NAMESPACE_URL, "dale:twin"))
NOW = datetime(2026, 11, 18, 9, tzinfo=ZoneInfo(el_hornero.TIMEZONE))  # delivery Thursday 19
C001 = CustomerId(el_hornero.row_id("customer", "C-001"))
COLA = ProductId(el_hornero.row_id("product", "COLA-225"))
COLA_NAME = "Gaseosa cola Burbuja 2,25 L"  # management's name, brand and size
DAY = date(2026, 11, 19)


def session(db: Engine, company: CompanyId = HORNERO, id: Any = None) -> SessionContext:
    started = SessionContext(company, C001, ConversationId(id or uuid4()))
    row = {"company_id": company, "id": started.conversation_id, "customer_id": C001}
    with db.begin() as conn:
        conn.execute(sa.insert(t.conversation), row | {"channel": "terminal", "started_at": NOW})
    return started


def grounded(
    db: Engine, at: SessionContext, ids: IdGenerator | None = None, writes: Engine | None = None
) -> Tools:
    """Tools whose search returned COLA. Ids are sequential by default, so two Tools reuse the
    first id; `writes` is the engine of the proposal store."""
    erp_facade, store = SqlErpFacade(db, FrozenClock(NOW)), SqlProposalRepository(writes or db)
    tools = Tools(at, erp_facade, store, ids or SequentialIdGenerator(), SqlHandoffRepository(db))
    assert not tools.run("search_products", {"query": "cola dos y cuarto"}).is_error
    return tools


def order(tools: Tools, quantity: int, **extra: object) -> Any:
    line = {"product_id": str(COLA), "quantity": quantity} | extra
    outcome = tools.run("prepare_order", {"lines": [line]})
    return outcome.shown[0] if outcome.shown else json.loads(outcome.content)["code"]


def save(store: SqlProposalRepository, company: CompanyId, proposal: OrderProposal) -> Any:
    with store.locked(company, proposal.conversation_id) as locked:
        return locked.save_prepared(proposal)


def rows(db: Engine, table: sa.Table, *cols: str) -> list[tuple[Any, ...]]:
    with db.connect() as conn:
        return [tuple(r) for r in conn.execute(sa.select(*(table.c[c] for c in cols)))]


def test_a_valid_proposal_is_stored_at_server_prices_and_is_not_an_order(db: Engine) -> None:
    tools = grounded(db, session(db))
    assert order(tools, 20, unit_price=50_000) == "invalid_tool_input"  # S1.2: never stored
    assert rows(db, t.order_proposal, "id") == []
    summary = order(tools, 20)  # S1.1, S3.1
    line = SummaryLine(COLA, COLA_NAME, 20, Money(245_000), Money(4_900_000))
    assert summary == ProposalSummary(summary.proposal_id, (line,), Money(4_900_000), DAY)
    head = rows(db, t.order_proposal, "id", "status", "total_cents", "delivery_date")
    assert head == [(summary.proposal_id, "prepared", 4_900_000, DAY)]  # S3.3
    assert rows(db, t.order_proposal_line, "product_id", "qty", "product_name") == [
        (COLA, 20, COLA_NAME)  # B61: stored from the quote, so the summary names the product
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
        line = ProposalLine(COLA, COLA_NAME, qty, Money(111_100), Money(111_100 * qty))
        mine = OrderProposal.prepared(proposal_id, at, (line,), line.line_total, DAY, NOW)
        assert save(store, company, mine) == mine
    ours, twins = store.get(HORNERO, proposal_id), store.get(TWIN, proposal_id)
    assert ours and twins and (ours.lines[0].quantity, twins.lines[0].quantity) == (20, 1)
    newer = OrderProposal.prepared(new_proposal_id(), at, ours.lines, ours.total, DAY, NOW)
    save(store, HORNERO, newer)
    assert store.get(TWIN, proposal_id) == twins and twins.status is ProposalStatus.PREPARED
    assert store.get(HORNERO, proposal_id) == replace(ours, status=ProposalStatus.SUPERSEDED)


def test_a_new_proposal_supersedes_only_its_own_conversations(db: Engine) -> None:
    a, b = session(db), session(db)  # one customer, two conversations
    first, second = order(grounded(db, a), 20), order(grounded(db, b, Uuid4Generator()), 30)
    statuses = dict(rows(db, t.order_proposal, "id", "status"))
    assert statuses == {first.proposal_id: "prepared", second.proposal_id: "prepared"}


def test_a_proposal_without_its_conversation_row_raises(db: Engine) -> None:
    """A wiring bug, not an outage. A twin company's conversation with that id does not count."""
    line = ProposalLine(COLA, COLA_NAME, 20, Money(245_000), Money(4_900_000))
    for at in (SessionContext(HORNERO, C001, ConversationId(uuid4())), session(db, TWIN)):
        mine = replace(at, company_id=HORNERO)
        proposal = OrderProposal.prepared(
            new_proposal_id(), mine, (line,), line.line_total, DAY, NOW
        )
        with pytest.raises(RuntimeError, match="conversation row"):
            save(SqlProposalRepository(db), HORNERO, proposal)
    assert rows(db, t.order_proposal, "id") == []


def test_concurrent_prepares_of_one_conversation_leave_one_prepared(db: Engine) -> None:
    """Both writes begin together. The conversation row lock makes the second wait and then
    supersede the first. Without the lock the loser's insert breaks the partial unique index
    (an IntegrityError, raised here); without both, two proposals stay prepared."""
    at = session(db)
    earlier = order(grounded(db, at), 20)
    writes, both = sa.create_engine(db.url), threading.Barrier(2, timeout=10)
    racers = [grounded(db, at, Uuid4Generator(), writes) for _ in range(2)]
    sa.event.listen(writes, "begin", lambda conn: both.wait())  # only save_prepared begins here
    try:
        with ThreadPoolExecutor(2) as pool:
            shown = list(pool.map(order, racers, (30, 40)))
    finally:
        writes.dispose()
    assert all(isinstance(s, ProposalSummary) for s in shown)  # neither call failed
    statuses = dict(rows(db, t.order_proposal, "id", "status"))
    assert sorted(statuses.values()) == ["prepared", "superseded", "superseded"]
    assert statuses[earlier.proposal_id] == "superseded"


def ordered(db: Engine, summary: ProposalSummary) -> OrderConfirmation:
    """Management stores the shown proposal's order: a Dale press whose answer the brain lost."""
    lines = tuple(ConfirmLine(x.product_id, x.quantity, x.unit_price) for x in summary.lines)
    request = ConfirmRequest(summary.proposal_id, C001, lines, summary.delivery_date, summary.total)
    done = SqlErpFacade(db, FrozenClock(NOW)).confirm(HORNERO, request)
    assert isinstance(done, Ok)
    return done.value


def test_an_ordered_earlier_proposal_is_confirmed_not_superseded(db: Engine) -> None:
    """B67: one order per intent. The new prepare shows the stored order and prepares nothing."""
    tools = grounded(db, session(db), Uuid4Generator())
    first = order(tools, 20)
    done = ordered(db, first)
    assert order(tools, 30) == order_confirmed(done)
    marked = [(first.proposal_id, "confirmed", done.order_id)]
    assert rows(db, t.order_proposal, "id", "status", "order_id") == marked
    assert rows(db, erp.sales_order, "id") == [(done.order_id,)]


def test_a_mark_moves_exactly_one_proposal_in_the_status_it_expects(db: Engine) -> None:
    """B68: a mark on a proposal that is no longer prepared raises and changes nothing; with no
    status guard the second mark would overwrite the first order id."""
    at = session(db)
    tools = grounded(db, at)
    first, second = order(tools, 20), order(tools, 30)  # the first is now superseded
    store, one, other = SqlProposalRepository(db), OrderId(uuid4()), OrderId(uuid4())
    with store.locked(HORNERO, at.conversation_id) as locked:
        locked.mark_confirmed(second.proposal_id, one)
    for proposal_id in (second.proposal_id, first.proposal_id):
        conversation = store.locked(HORNERO, at.conversation_id)
        with pytest.raises(RuntimeError, match="exactly one"), conversation as locked:
            locked.mark_confirmed(proposal_id, other)
    statuses = rows(db, t.order_proposal, "id", "status", "order_id")
    expected = [(first.proposal_id, "superseded", None), (second.proposal_id, "confirmed", one)]
    assert sorted(statuses) == sorted(expected)

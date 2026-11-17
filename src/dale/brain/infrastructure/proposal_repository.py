"""Proposals in `brain.order_proposal(+_line)`, SQLAlchemy Core. Every statement filters by
`company_id` through `of_company` (R15)."""

from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa

from dale.brain.domain.proposal import OrderProposal, ProposalLine, ProposalStatus
from dale.brain.infrastructure import tables as t
from dale.shared.ids import CompanyId, ConversationId, CustomerId, ProductId, ProposalId
from dale.shared.money import Money


def of_company(table: sa.Table, company_id: CompanyId) -> sa.ColumnElement[bool]:
    """The tenant filter. No company, no query: a missing id fails before any SQL is built."""
    if not isinstance(company_id, UUID):
        raise TypeError("every brain query needs a company_id")
    return table.c.company_id == company_id


class SqlProposalRepository:
    def __init__(self, engine: sa.Engine) -> None:
        self._engine = engine

    def save_prepared(self, company_id: CompanyId, proposal: OrderProposal) -> OrderProposal:
        if proposal.status is not ProposalStatus.PREPARED:
            raise ValueError("only a prepared proposal is saved here")
        p, own, prepared = t.order_proposal, {"company_id": company_id}, proposal.status.value
        head: dict[str, object] = own | {"id": proposal.id, "status": prepared}
        head |= {"conversation_id": proposal.conversation_id, "customer_id": proposal.customer_id}
        head |= {"delivery_date": proposal.delivery_date, "total_cents": proposal.total.cents}
        earlier = (p.c.conversation_id == proposal.conversation_id) & (p.c.status == prepared)
        lines = [
            own
            | {"id": uuid4(), "proposal_id": proposal.id, "product_id": x.product_id}
            | {"qty": x.quantity, "unit_price_cents": x.unit_price.cents}
            | {"line_total_cents": x.line_total.cents}
            for x in proposal.lines
        ]
        with self._engine.begin() as conn:  # the supersede and the insert commit together
            c = t.conversation  # its row lock serializes the prepares of one conversation
            mine = (of_company(c, company_id), c.c.id == proposal.conversation_id)
            if conn.execute(sa.select(c.c.id).where(*mine).with_for_update()).first() is None:
                raise RuntimeError("a proposal needs its conversation row")  # a wiring bug
            superseded = {"status": ProposalStatus.SUPERSEDED.value}
            conn.execute(sa.update(p).where(of_company(p, company_id), earlier).values(superseded))
            conn.execute(sa.insert(p), head | {"created_at": proposal.created_at})
            conn.execute(sa.insert(t.order_proposal_line), lines)
            stored = _read(conn, company_id, proposal.id)
        if stored is None:
            raise RuntimeError("a stored proposal must read back")
        return stored

    def get(self, company_id: CompanyId, proposal_id: ProposalId) -> OrderProposal | None:
        with self._engine.connect() as conn:
            return _read(conn, company_id, proposal_id)


def _read(
    conn: sa.Connection, company_id: CompanyId, proposal_id: ProposalId
) -> OrderProposal | None:
    p, li = t.order_proposal, t.order_proposal_line
    cols = (p.c.conversation_id, p.c.customer_id, p.c.status, p.c.total_cents, p.c.delivery_date)
    stmt = sa.select(*cols, p.c.created_at).where(of_company(p, company_id), p.c.id == proposal_id)
    head = conn.execute(stmt).one_or_none()  # the key is (company_id, id)
    if head is None:
        return None
    parts = (li.c.product_id, li.c.qty, li.c.unit_price_cents, li.c.line_total_cents)
    where = (of_company(li, company_id), li.c.proposal_id == proposal_id)
    rows: list[Any] = list(conn.execute(sa.select(*parts).where(*where).order_by(*parts[:2])))
    lines = tuple(ProposalLine(ProductId(i), q, Money(u), Money(x)) for i, q, u, x in rows)
    conversation, customer, status, total, day, created_at = head
    who = (ConversationId(conversation), CustomerId(customer), ProposalStatus(status))
    return OrderProposal(proposal_id, *who, lines, Money(total), day, created_at)

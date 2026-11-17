"""Proposals in `brain.order_proposal(+_line)`, SQLAlchemy Core. Every statement filters by
`company_id` through `of_company` (R15)."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa

from dale.brain.domain.proposal import OrderProposal, ProposalLine, ProposalStatus
from dale.brain.infrastructure import tables as t
from dale.shared.errors import ErrorCode
from dale.shared.ids import CompanyId, ConversationId, CustomerId, OrderId, ProductId, ProposalId
from dale.shared.money import Money

PREPARED, READ_COMMITTED = ProposalStatus.PREPARED, {"isolation_level": "READ COMMITTED"}


def of_company(table: sa.Table, company_id: CompanyId) -> sa.ColumnElement[bool]:
    """The tenant filter. No company, no query: a missing id fails before any SQL is built."""
    if not isinstance(company_id, UUID):
        raise TypeError("every brain query needs a company_id")
    return table.c.company_id == company_id


class SqlLockedProposals:
    """Statements in `SqlProposalRepository.locked`'s transaction, filtered by its company and
    conversation."""

    def __init__(self, conn: sa.Connection, company_id: CompanyId, chat: ConversationId) -> None:
        p, self._conn, self._company_id, self._chat = t.order_proposal, conn, company_id, chat
        self._mine = (of_company(p, company_id), p.c.conversation_id == chat)
        self._prepared = (*self._mine, p.c.status == PREPARED.value)  # one at most (0004)

    def get(self, proposal_id: ProposalId) -> OrderProposal | None:
        return _read(self._conn, self._company_id, proposal_id)

    def prepared(self) -> OrderProposal | None:
        pid = self._conn.execute(sa.select(t.order_proposal.c.id).where(*self._prepared)).scalar()
        return None if pid is None else _read(self._conn, self._company_id, ProposalId(pid))

    def save_prepared(self, proposal: OrderProposal) -> OrderProposal:
        if (proposal.status, proposal.conversation_id) != (PREPARED, self._chat):
            raise ValueError("only a prepared proposal of the locked conversation is saved")
        p, own, prepared = t.order_proposal, {"company_id": self._company_id}, PREPARED.value
        head: dict[str, object] = own | {"id": proposal.id, "status": prepared}
        head |= {"conversation_id": proposal.conversation_id, "customer_id": proposal.customer_id}
        head |= {"delivery_date": proposal.delivery_date, "total_cents": proposal.total.cents}
        lines = [
            own
            | {"id": uuid4(), "proposal_id": proposal.id, "product_id": x.product_id}
            | {"qty": x.quantity, "unit_price_cents": x.unit_price.cents}
            | {"line_total_cents": x.line_total.cents}
            for x in proposal.lines
        ]
        conn, superseded = self._conn, {"status": ProposalStatus.SUPERSEDED.value}
        conn.execute(sa.update(p).where(*self._prepared).values(superseded))
        conn.execute(sa.insert(p), head | {"created_at": proposal.created_at})
        conn.execute(sa.insert(t.order_proposal_line), lines)
        stored = _read(conn, self._company_id, proposal.id)
        if stored is None:
            raise RuntimeError("a stored proposal must read back")
        return stored

    def mark_confirmed(
        self, proposal_id: ProposalId, order_id: OrderId, was: ProposalStatus = PREPARED
    ) -> None:
        confirmed = ProposalStatus.CONFIRMED.value
        self._mark(proposal_id, was, status=confirmed, order_id=order_id, rejection_code=None)

    def withdraw(self, proposal_id: ProposalId) -> None:
        self._mark(proposal_id, PREPARED, status=ProposalStatus.SUPERSEDED.value)

    def mark_rejected(self, proposal_id: ProposalId, code: ErrorCode) -> None:
        rejected = ProposalStatus.REJECTED.value
        self._mark(proposal_id, PREPARED, status=rejected, rejection_code=code.value)

    def _mark(self, proposal_id: ProposalId, was: ProposalStatus, **values: object) -> None:
        """Exactly one proposal in status `was` moves, or the brain lost an outcome (B68)."""
        p = t.order_proposal
        stmt = sa.update(p).where(*self._mine, p.c.id == proposal_id, p.c.status == was.value)
        if len(self._conn.execute(stmt.values(**values).returning(p.c.id)).all()) != 1:
            raise RuntimeError("a mark must move exactly one proposal")  # rolls it all back


class SqlProposalRepository:
    def __init__(self, engine: sa.Engine) -> None:
        self._engine = engine

    @contextmanager
    def locked(
        self, company_id: CompanyId, conversation_id: ConversationId
    ) -> Iterator[SqlLockedProposals]:
        # READ COMMITTED, pinned: once the lock is granted, each statement sees what it waited for
        with self._engine.connect().execution_options(**READ_COMMITTED) as conn, conn.begin():
            c = t.conversation  # its row lock serializes the prepares and presses of one chat
            mine = (of_company(c, company_id), c.c.id == conversation_id)
            if conn.execute(sa.select(c.c.id).where(*mine).with_for_update()).first() is None:
                raise RuntimeError("a proposal needs its conversation row")  # a wiring bug
            yield SqlLockedProposals(conn, company_id, conversation_id)

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

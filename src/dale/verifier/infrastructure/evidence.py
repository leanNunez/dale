"""The verifier's own SQL (design §9, contract 4). It reads `erp` and `brain` as the read-only
`dale_verifier` role, in one read-only snapshot, and never through the writers' table mappings.
Every statement filters by company_id (R15).

The run is the session's conversation: its orders are the session customer's received since the
conversation started, those for its proposals, and those for the proposals shown confirmed.
"""

from collections import defaultdict
from collections.abc import Collection, Iterable, Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import sqlalchemy as sa

from dale.verifier.domain.rules import ZoneRule
from dale.verifier.domain.verdict import Evidence, Line, Session, StoredOrder, StoredProposal

ROLE = "dale_verifier"
SHOWN = "ANY(CAST(:shown AS uuid[]))"
CONVERSATION = sa.text(
    "SELECT customer_id, started_at FROM brain.conversation"
    " WHERE company_id = :company AND id = :conversation"
)
ORDERS = sa.text(
    "SELECT o.company_id, o.id, o.proposal_id, o.customer_id, o.total_cents, o.delivery_date,"
    " o.received_at FROM erp.sales_order o WHERE o.company_id = :company"
    " AND ((o.received_at >= :started AND o.customer_id = :customer)"
    f" OR o.proposal_id = {SHOWN} OR o.proposal_id IN ("
    "  SELECT p.id FROM brain.order_proposal p"
    "  WHERE p.company_id = :company AND p.conversation_id = :conversation))"
)
ORDER_LINES = sa.text(
    "SELECT order_id, product_id, qty, unit_price_cents, line_total_cents"
    " FROM erp.sales_order_line"
    " WHERE company_id = :company AND order_id = ANY(CAST(:ids AS uuid[]))"
)
PROPOSALS = sa.text(
    "SELECT id, customer_id, total_cents, delivery_date FROM brain.order_proposal"
    f" WHERE company_id = :company AND conversation_id = :conversation AND id = {SHOWN}"
)
PROPOSAL_LINES = sa.text(
    "SELECT proposal_id, product_id, qty, unit_price_cents, line_total_cents"
    f" FROM brain.order_proposal_line WHERE company_id = :company AND proposal_id = {SHOWN}"
)
ZONE = sa.text(
    "SELECT z.delivery_weekdays, z.cutoff_time, z.min_order_amount_cents, c.timezone"
    " FROM erp.customer u JOIN erp.zone z ON z.company_id = u.company_id AND z.id = u.zone_id"
    " JOIN erp.company c ON c.id = u.company_id WHERE u.company_id = :company AND u.id = :customer"
)


class SqlEvidence:
    def __init__(self, engine: sa.Engine) -> None:
        self._engine = engine

    @contextmanager
    def snapshot(self) -> Iterator[sa.Connection]:
        """A read-only REPEATABLE READ transaction, refused unless it runs as dale_verifier."""
        options: dict[str, Any] = {"isolation_level": "REPEATABLE READ"}
        options["postgresql_readonly"] = True
        with self._engine.connect().execution_options(**options) as conn, conn.begin():
            if conn.scalar(sa.text("SELECT current_user")) != ROLE:
                raise PermissionError(f"the verifier reads only as {ROLE}")
            yield conn

    def read(self, session: Session, shown: Collection[UUID]) -> Evidence:
        keys = {"company": session.company_id, "conversation": session.conversation_id}
        company, wanted = {"company": session.company_id}, list(shown)
        with self.snapshot() as conn:
            head = conn.execute(CONVERSATION, keys).one_or_none()
            if head is None or head.customer_id != session.customer_id:
                raise LookupError("the session has no conversation row")
            params = keys | {"started": head.started_at, "customer": session.customer_id}
            params["shown"] = wanted
            orders = conn.execute(ORDERS, params).all()
            ids = [o.id for o in orders]
            order_lines = _lines(conn.execute(ORDER_LINES, company | {"ids": ids}))
            proposals = conn.execute(PROPOSALS, keys | {"shown": wanted}).all()
            proposal_lines = _lines(conn.execute(PROPOSAL_LINES, company | {"shown": wanted}))
            zone = conn.execute(ZONE, company | {"customer": session.customer_id}).one_or_none()
        return Evidence(
            tuple(_order(o, order_lines.get(o.id, ())) for o in orders),
            {
                p.id: StoredProposal(
                    p.customer_id, proposal_lines.get(p.id, ()), p.total_cents, p.delivery_date
                )
                for p in proposals
            },
            None if zone is None else _zone(zone),
        )


def _order(o: Any, lines: tuple[Line, ...]) -> StoredOrder:
    head = (o.company_id, o.id, o.proposal_id, o.customer_id)
    return StoredOrder(*head, lines, o.total_cents, o.delivery_date, o.received_at)


def _zone(z: Any) -> ZoneRule:
    weekdays, cutoff, minimum, timezone = z
    return ZoneRule(frozenset(weekdays), cutoff, minimum, ZoneInfo(timezone))


def _lines(rows: Iterable[Any]) -> dict[UUID, tuple[Line, ...]]:
    grouped: defaultdict[UUID, list[Line]] = defaultdict(list)
    for owner, *line in rows:
        grouped[owner].append(Line(*line))
    return {owner: tuple(lines) for owner, lines in grouped.items()}

"""Rule reads and the order write, SQLAlchemy Core. Every predicate uses `of_company` (R15)."""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import sqlalchemy as sa

from dale.erp_sim.application.confirm import Order
from dale.erp_sim.domain.catalog import CatalogProduct
from dale.erp_sim.domain.rules import Customer, Zone
from dale.erp_sim.infrastructure import tables as t
from dale.shared.ids import CompanyId, CustomerId, ProductId
from dale.shared.money import Money


def of_company(table: sa.Table, company_id: CompanyId) -> sa.ColumnElement[bool]:
    """The tenant filter. No company, no query: a missing id fails before any SQL is built."""
    if not isinstance(company_id, UUID):
        raise TypeError("every erp query needs a company_id")
    return table.c.company_id == company_id


class SqlRuleData:
    """On an engine each read opens its own connection; on a connection, reads join its
    transaction (confirm's second check, B40)."""

    def __init__(self, source: sa.Engine | sa.Connection) -> None:
        self._source = source

    def _rows(self, stmt: sa.Executable) -> list[Any]:
        if isinstance(self._source, sa.Connection):
            return list(self._source.execute(stmt))
        with self._source.connect() as conn:
            return list(conn.execute(stmt))

    def customer(
        self, company_id: CompanyId, customer_id: CustomerId
    ) -> tuple[Customer, Zone] | None:
        c, z = t.customer, t.zone
        stmt = (
            sa.select(c.c.active, z.c.delivery_weekdays, z.c.cutoff_time)
            .add_columns(z.c.min_order_amount_cents, t.company.c.timezone)
            .join_from(c, z, (z.c.company_id == c.c.company_id) & (z.c.id == c.c.zone_id))
            .join(t.company, t.company.c.id == z.c.company_id)
            .where(of_company(c, company_id), of_company(z, company_id), c.c.id == customer_id)
        )
        rows = self._rows(stmt)  # the primary key gives at most one
        if not rows:
            return None
        active, weekdays, cutoff, minimum, timezone = rows[0]
        zone = Zone(frozenset(weekdays), cutoff, Money(minimum), ZoneInfo(timezone))
        return Customer(customer_id, active), zone

    def current_prices(
        self, company_id: CompanyId, product_ids: Sequence[ProductId], at: datetime
    ) -> dict[ProductId, Money | None]:
        p, pp = t.product, t.product_price
        latest = (  # current price: the latest row already valid at `at`
            sa.select(pp.c.unit_price_cents)
            .where(of_company(pp, company_id), pp.c.product_id == p.c.id, pp.c.valid_from <= at)
            .order_by(pp.c.valid_from.desc())
            .limit(1)
            .scalar_subquery()
        )
        stmt = sa.select(p.c.id, latest).where(
            of_company(p, company_id), p.c.active, p.c.id.in_(product_ids)
        )
        rows = self._rows(stmt)
        return {ProductId(i): None if cents is None else Money(cents) for i, cents in rows}

    def active_products(self, company_id: CompanyId) -> list[CatalogProduct]:
        p = t.product
        cols = (p.c.id, p.c.sku, p.c.name, p.c.brand, p.c.presentation, p.c.search_terms)
        stmt = sa.select(*cols).where(of_company(p, company_id), p.c.active).order_by(p.c.sku)
        return [CatalogProduct(ProductId(r[0]), *r[1:]) for r in self._rows(stmt)]


class SqlOrderData(SqlRuleData):
    """Rule reads and the order write on one connection, inside its transaction."""

    def __init__(self, conn: sa.Connection) -> None:
        super().__init__(conn)
        self._conn = conn

    def insert_order(self, company_id: CompanyId, order: Order) -> None:
        o, own = t.sales_order, {"company_id": company_id}
        head: dict[str, object] = own | {"id": order.id, "proposal_id": order.proposal_id}
        head |= {"customer_id": order.customer_id, "delivery_date": order.delivery_date}
        head |= {"total_cents": order.total.cents, "received_at": order.received_at}
        self._conn.execute(sa.insert(o).values(head))
        lines = [
            own
            | {"id": uuid4(), "order_id": order.id, "product_id": x.product_id, "qty": x.quantity}
            | {"unit_price_cents": x.unit_price.cents, "line_total_cents": x.line_total.cents}
            for x in order.lines
        ]
        self._conn.execute(sa.insert(t.sales_order_line), lines)


class SqlOrderStore:
    def __init__(self, engine: sa.Engine) -> None:
        self._engine = engine

    @contextmanager
    def transaction(self) -> Iterator[SqlOrderData]:
        with self._engine.begin() as conn:
            yield SqlOrderData(conn)

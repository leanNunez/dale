"""Rule-data reads with SQLAlchemy Core. Every predicate starts from `of_company` (R15)."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

import sqlalchemy as sa

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
    def __init__(self, engine: sa.Engine) -> None:
        self._engine = engine

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
        with self._engine.connect() as conn:
            row = conn.execute(stmt).one_or_none()
        if row is None:
            return None
        active, weekdays, cutoff, minimum, timezone = row
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
        with self._engine.connect() as conn:
            rows = conn.execute(stmt).all()
        return {ProductId(i): None if cents is None else Money(cents) for i, cents in rows}

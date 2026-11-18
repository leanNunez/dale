"""Seed of the ERP simulator. `reseed` empties the `erp` schema and inserts El Hornero again.

It deletes rows in foreign-key order instead of TRUNCATE: `dale_app` has no TRUNCATE (B13).
"""

from datetime import datetime
from typing import Any

import sqlalchemy as sa

from dale.erp_sim.infrastructure import tables as t
from dale.erp_sim.infrastructure.seed import el_hornero


def reseed(
    engine: sa.Engine, overrides: dict[str, dict[str, dict[str, Any]]] | None = None
) -> None:
    """Idempotent, one transaction, scoped to El Hornero (other companies survive). `overrides`:
    {"zones" | "customers" | "products": {natural key: {column: value}}}, e.g. a zone minimum."""
    data = el_hornero.build(overrides or {})
    with engine.begin() as conn:
        for table in reversed(t.METADATA.sorted_tables):  # children first (foreign-key order)
            own = table.c.id if table is t.company else table.c.company_id
            conn.execute(sa.delete(table).where(own == el_hornero.COMPANY_ID))
        conn.execute(sa.insert(t.company), data["company"])
        for table, name in ((t.zone, "zones"), (t.customer, "customers"), (t.product, "products")):
            conn.execute(sa.insert(table), data[name])
        conn.execute(sa.insert(t.product_price), data["prices"])


def change_price(engine: sa.Engine, sku: str, pesos: int, valid_from: datetime) -> None:
    """A new list price for `sku` that takes effect at `valid_from` (D4's price change). A row is
    added, never rewritten, so the price history stays; an unknown sku fails on the foreign key."""
    row = {"company_id": el_hornero.COMPANY_ID, "product_id": el_hornero.row_id("product", sku)}
    with engine.begin() as conn:
        conn.execute(
            sa.insert(t.product_price),
            [row | {"valid_from": valid_from, "unit_price_cents": pesos * 100}],
        )

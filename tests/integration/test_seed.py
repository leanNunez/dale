"""The El Hornero seed: complete, tenant-scoped, deterministic and idempotent (R2, R15)."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine

from dale.erp_sim.infrastructure import tables as t
from dale.erp_sim.infrastructure.seed import el_hornero, reseed

pytestmark = pytest.mark.integration
CASE_NOW = datetime(2026, 6, 1, tzinfo=UTC)  # fixed: after the base prices, before the future one
D = UUID("00000000-0000-0000-0000-00000000000d")


def snapshot(engine: Engine) -> dict[str, list[tuple[Any, ...]]]:
    """Every row of every erp table, ids included."""
    with engine.connect() as conn:
        return {
            tb.name: sorted((tuple(r) for r in conn.execute(sa.select(tb))), key=repr)
            for tb in t.METADATA.sorted_tables
        }


def order_sql(company: UUID, customer: UUID, product: UUID) -> str:
    """An order and its line (SQL), as the app role writes them."""
    o = uuid5(company, "order")
    return (
        f"INSERT INTO erp.sales_order VALUES ('{company}', '{o}', '{o}', '{customer}',"
        f" '2026-11-17', 245000, now()); INSERT INTO erp.sales_order_line"
        f" VALUES ('{company}', '{o}', '{o}', '{product}', 1, 245000, 245000)"
    )


@pytest.fixture
def other_company(engines: dict[str, Engine]) -> Iterator[None]:
    """A second company with one row per table; removed afterwards, children first."""
    with engines["dale_app"].begin() as conn:
        conn.exec_driver_sql(
            f"INSERT INTO erp.company VALUES ('{D}', 'otra', 'Otra distribuidora', 'UTC');"
            f"INSERT INTO erp.zone VALUES ('{D}', '{D}', 'Centro', '{{2}}', '18:00', 0);"
            f"INSERT INTO erp.customer VALUES ('{D}', '{D}', 'C-001', 'x', '{D}', true);"
            f"INSERT INTO erp.product VALUES ('{D}', '{D}', 'COLA-225', 'x', 'x', 'x', '', true);"
            f"INSERT INTO erp.product_price VALUES ('{D}', '{D}', now(), 100);" + order_sql(D, D, D)
        )
    yield
    with engines["dale_app"].begin() as conn:
        for table in reversed(t.METADATA.sorted_tables):
            own = table.c.id if table is t.company else table.c.company_id
            conn.execute(sa.delete(table).where(own == D))


def test_seed_prices_every_active_product_now_and_one_later(engines: dict[str, Engine]) -> None:
    reseed(engines["dale_app"])
    price = t.product_price
    assert el_hornero.PRICES_FROM <= CASE_NOW < el_hornero.FUTURE_PRICE[1]
    with engines["dale_app"].connect() as conn:
        unpriced = sa.select(t.product.c.sku).where(
            t.product.c.active,
            ~sa.exists().where(
                price.c.product_id == t.product.c.id, price.c.valid_from <= CASE_NOW
            ),
        )
        assert conn.execute(unpriced).first() is None
        future = sa.select(price.c.valid_from).where(price.c.valid_from > CASE_NOW)
        assert conn.execute(future).scalar_one() == datetime(2026, 12, 1, 3, tzinfo=UTC)  # BA time
        active = sa.select(t.customer.c.active, t.product.c.active).join_from(
            t.customer, t.product, sa.true()
        )
        assert {False, True} <= {c for c, _ in conn.execute(active)}


def test_reseed_restores_the_seed_after_foreign_writes(engines: dict[str, Engine]) -> None:
    app = engines["dale_app"]
    reseed(app)
    seeded = snapshot(app)
    assert [len(seeded[k]) for k in ("product", "product_price")] == [36, 37]
    ids = (el_hornero.row_id("customer", "C-001"), el_hornero.row_id("product", "COLA-225"))
    with app.begin() as conn:
        conn.exec_driver_sql(order_sql(el_hornero.COMPANY_ID, *ids))
    assert len(snapshot(app)["sales_order_line"]) == 1
    reseed(app)  # (a) orders written by the app role are cleared with the rest
    assert snapshot(app) == seeded
    reseed(app, {"zones": {"Centro": {"min_order_amount_cents": 123}}})
    assert snapshot(app)["zone"] != seeded["zone"]  # the override took effect
    reseed(app)  # (b) and an override left by a previous reseed is gone
    assert snapshot(app) == seeded


def test_ids_are_stable_across_reseeds_and_follow_uuid5(engines: dict[str, Engine]) -> None:
    app = engines["dale_app"]
    reseed(app)
    first = snapshot(app)
    reseed(app)
    assert snapshot(app) == first  # a random id per reseed would differ here
    company = uuid5(NAMESPACE_URL, "dale:el-hornero")  # documented: uuid5 of the natural key
    assert first["company"][0][0] == company
    assert any(r[:2] == (company, uuid5(company, "product:COLA-225")) for r in first["product"])


def test_reseed_keeps_other_companies(engines: dict[str, Engine], other_company: None) -> None:
    app = engines["dale_app"]
    before = snapshot(app)
    reseed(app)
    after = snapshot(app)
    for name, rows in before.items():
        mine = [r for r in rows if D in r]
        assert mine, f"fixture wrote nothing to {name}"
        assert [r for r in after[name] if D in r] == mine

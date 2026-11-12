"""CHECK, unique and company-scoped foreign keys reject bad rows (R15, design §5)."""

import psycopg
import pytest
from sqlalchemy import Engine
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.integration

C, D = "00000000-0000-0000-0000-00000000000c", "00000000-0000-0000-0000-00000000000d"
# One valid row per table, keyed (C, C), plus a second company D with no rows of its own.
BASELINE = f"""
INSERT INTO erp.company VALUES ('{C}', 'el-hornero', 'Distribuidora El Hornero', 'UTC');
INSERT INTO erp.company VALUES ('{D}', 'otra', 'Otra distribuidora', 'UTC');
INSERT INTO erp.zone VALUES ('{C}', '{C}', 'Centro', '{{2,5}}', '18:00', 5000000);
INSERT INTO erp.customer VALUES ('{C}', '{C}', 'C-001', 'Almacen Don Tito', '{C}', true);
INSERT INTO erp.product VALUES ('{C}', '{C}', 'COLA-225', 'Cola', 'Burbuja', '2,25 L', '', true);
INSERT INTO erp.sales_order VALUES ('{C}', '{C}', '{C}', '{C}', '2026-11-17', 300000, now());
INSERT INTO erp.sales_order_line VALUES ('{C}', '{C}', '{C}', '{C}', 2, 150000, 300000);
"""
# (constraint that must reject it, statement run after BASELINE)
BAD_ROWS = [
    ("ck_zone_delivery_weekdays", "UPDATE erp.zone SET delivery_weekdays = '{}'"),
    ("ck_zone_delivery_weekdays", "UPDATE erp.zone SET delivery_weekdays = '{1,8}'"),
    ("ck_zone_delivery_weekdays", "UPDATE erp.zone SET delivery_weekdays = '{NULL}'"),
    ("ck_zone_delivery_weekdays", "UPDATE erp.zone SET delivery_weekdays = '{2,5,2}'"),
    ("ck_zone_delivery_weekdays", "UPDATE erp.zone SET delivery_weekdays = '{{2,5},{3,4}}'"),
    ("ck_zone_min_order_amount_cents", "UPDATE erp.zone SET min_order_amount_cents = -1"),
    (
        "ck_product_price_unit_price_cents",
        f"INSERT INTO erp.product_price VALUES ('{C}', '{C}', now(), 0)",
    ),
    ("ck_sales_order_total_cents", "UPDATE erp.sales_order SET total_cents = 0"),
    ("ck_sales_order_line_qty", "UPDATE erp.sales_order_line SET qty = 0, line_total_cents = 0"),
    (
        "ck_sales_order_line_qty",
        "UPDATE erp.sales_order_line SET qty = 1000, line_total_cents = 150000000",
    ),
    (
        "ck_sales_order_line_line_total_cents",
        "UPDATE erp.sales_order_line SET line_total_cents = 1",
    ),
    (
        "ck_sales_order_line_unit_price_cents",
        "UPDATE erp.sales_order_line SET unit_price_cents = 0, line_total_cents = 0",
    ),
    (  # the idempotency key: one order per proposal and company
        "uq_sales_order_company_id_proposal_id",
        f"INSERT INTO erp.sales_order VALUES ('{C}', '{D}', '{C}', '{C}', '2026-11-17', 1, now())",
    ),
    (  # company D cannot point at company C's zone
        "fk_customer_company_id_zone_id",
        f"INSERT INTO erp.customer VALUES ('{D}', '{C}', 'C-001', 'X', '{C}', true)",
    ),
]


@pytest.mark.parametrize(("constraint", "sql"), BAD_ROWS)
def test_constraint_rejects_bad_row(engines: dict[str, Engine], constraint: str, sql: str) -> None:
    with engines["dale_app"].connect() as conn:  # rolled back on exit
        conn.exec_driver_sql(BASELINE)
        with pytest.raises(DBAPIError) as err:
            conn.exec_driver_sql(sql)
    assert isinstance(err.value.orig, psycopg.Error)
    assert err.value.orig.diag.constraint_name == constraint

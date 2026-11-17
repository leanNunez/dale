"""Tables of the `erp` schema (design §5). The migrations create them; this is the query model.

Keys below the tenant root `company` start with `company_id`: `(company_id, id)`, or a natural
key (`product_price`). Foreign keys and unique constraints include it (R15). Money: bigint cents.
"""

import sqlalchemy as sa

from dale.shared.db_naming import NAMING_CONVENTION

METADATA = sa.MetaData(schema="erp", naming_convention=NAMING_CONVENTION)
_TO_COMPANY = (["company_id"], ["erp.company.id"])


def _tenant_table(name: str, *items: sa.schema.SchemaItem) -> sa.Table:
    key = [sa.Column(c, sa.Uuid, primary_key=True) for c in ("company_id", "id")]
    return sa.Table(name, METADATA, *key, *items)


def _ref(table: str, column: str) -> sa.ForeignKeyConstraint:
    """Composite foreign key `(company_id, column)` to `erp.table`."""
    return sa.ForeignKeyConstraint(
        ["company_id", column], [f"erp.{table}.company_id", f"erp.{table}.id"]
    )


company = sa.Table(
    "company",
    METADATA,
    sa.Column("id", sa.Uuid, primary_key=True),
    sa.Column("slug", sa.Text, nullable=False, unique=True),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("timezone", sa.Text, nullable=False),
)

zone = _tenant_table(
    "zone",
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("delivery_weekdays", sa.ARRAY(sa.SmallInteger), nullable=False),
    sa.Column("cutoff_time", sa.Time, nullable=False),
    sa.Column("min_order_amount_cents", sa.BigInteger, nullable=False),
    sa.ForeignKeyConstraint(*_TO_COMPANY),
    sa.CheckConstraint(  # non-empty, one dimension, days 1-7, no day twice (one digit each)
        "cardinality(delivery_weekdays) > 0 AND array_ndims(delivery_weekdays) = 1"
        " AND delivery_weekdays <@ '{1,2,3,4,5,6,7}'"
        r" AND array_to_string(delivery_weekdays, '') !~ '(.).*\1'",
        name="delivery_weekdays",
    ),
    sa.CheckConstraint("min_order_amount_cents >= 0", name="min_order_amount_cents"),
)

customer = _tenant_table(
    "customer",
    sa.Column("code", sa.Text, nullable=False),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("zone_id", sa.Uuid, nullable=False),
    sa.Column("active", sa.Boolean, nullable=False),
    _ref("zone", "zone_id"),
    sa.UniqueConstraint("company_id", "code"),
)

product = _tenant_table(
    "product",
    sa.Column("sku", sa.Text, nullable=False),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("brand", sa.Text, nullable=False),
    sa.Column("presentation", sa.Text, nullable=False),
    sa.Column("search_terms", sa.Text, nullable=False),
    sa.Column("active", sa.Boolean, nullable=False),
    sa.ForeignKeyConstraint(*_TO_COMPANY),
    sa.UniqueConstraint("company_id", "sku"),
)

product_price = sa.Table(
    "product_price",
    METADATA,
    sa.Column("company_id", sa.Uuid, primary_key=True),
    sa.Column("product_id", sa.Uuid, primary_key=True),
    sa.Column("valid_from", sa.DateTime(timezone=True), primary_key=True),
    sa.Column("unit_price_cents", sa.BigInteger, nullable=False),
    _ref("product", "product_id"),
    sa.CheckConstraint("unit_price_cents > 0", name="unit_price_cents"),
)

sales_order = _tenant_table(
    "sales_order",
    sa.Column("proposal_id", sa.Uuid, nullable=False),
    sa.Column("customer_id", sa.Uuid, nullable=False),
    sa.Column("delivery_date", sa.Date, nullable=False),
    sa.Column("total_cents", sa.BigInteger, nullable=False),
    sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    _ref("customer", "customer_id"),
    sa.UniqueConstraint("company_id", "proposal_id"),
    sa.CheckConstraint("total_cents > 0", name="total_cents"),
)

sales_order_line = _tenant_table(
    "sales_order_line",
    sa.Column("order_id", sa.Uuid, nullable=False),
    sa.Column("product_id", sa.Uuid, nullable=False),
    sa.Column("qty", sa.Integer, nullable=False),
    sa.Column("unit_price_cents", sa.BigInteger, nullable=False),
    sa.Column("line_total_cents", sa.BigInteger, nullable=False),
    _ref("sales_order", "order_id"),
    _ref("product", "product_id"),
    sa.CheckConstraint("qty BETWEEN 1 AND 999", name="qty"),
    sa.CheckConstraint("unit_price_cents > 0", name="unit_price_cents"),
    sa.CheckConstraint("line_total_cents = qty * unit_price_cents", name="line_total_cents"),
)

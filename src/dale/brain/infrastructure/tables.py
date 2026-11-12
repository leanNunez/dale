"""Tables of the `brain` schema (design §5, D1, D6). The migrations create them.

Keys are `(company_id, id)` and foreign keys include `company_id` (R15). Nothing references
the `erp` schema: customer, product and order IDs cross by value. Money is bigint cents.
"""

import sqlalchemy as sa

from dale.shared.db_naming import NAMING_CONVENTION

METADATA = sa.MetaData(schema="brain", naming_convention=NAMING_CONVENTION)


def _tenant_table(name: str, *items: sa.schema.SchemaItem) -> sa.Table:
    key = [sa.Column(c, sa.Uuid, primary_key=True) for c in ("company_id", "id")]
    return sa.Table(name, METADATA, *key, *items)


def _ref(table: str, column: str) -> sa.ForeignKeyConstraint:
    """Composite foreign key `(company_id, column)` to `brain.table`."""
    return sa.ForeignKeyConstraint(
        ["company_id", column], [f"brain.{table}.company_id", f"brain.{table}.id"]
    )


conversation = _tenant_table(
    "conversation",
    sa.Column("customer_id", sa.Uuid, nullable=False),
    sa.Column("channel", sa.Text, nullable=False),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
)

order_proposal = _tenant_table(
    "order_proposal",
    sa.Column("conversation_id", sa.Uuid, nullable=False),
    sa.Column("customer_id", sa.Uuid, nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("rejection_code", sa.Text),
    sa.Column("order_id", sa.Uuid),
    sa.Column("delivery_date", sa.Date, nullable=False),
    sa.Column("total_cents", sa.BigInteger, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    _ref("conversation", "conversation_id"),
    sa.CheckConstraint(
        "status IN ('prepared', 'superseded', 'confirmed', 'rejected')", name="status"
    ),
    sa.CheckConstraint("(status = 'confirmed') = (order_id IS NOT NULL)", name="order_id"),
    sa.CheckConstraint(
        "(status = 'rejected') = (rejection_code IS NOT NULL)", name="rejection_code"
    ),
    sa.CheckConstraint("total_cents > 0", name="total_cents"),
    # One prepared proposal per conversation (migration 0004); the others are history.
    sa.Index(
        None,
        "company_id",
        "conversation_id",
        unique=True,
        postgresql_where=sa.text("status = 'prepared'"),
    ),
)

order_proposal_line = _tenant_table(
    "order_proposal_line",
    sa.Column("proposal_id", sa.Uuid, nullable=False),
    sa.Column("product_id", sa.Uuid, nullable=False),
    sa.Column("qty", sa.Integer, nullable=False),
    sa.Column("unit_price_cents", sa.BigInteger, nullable=False),
    sa.Column("line_total_cents", sa.BigInteger, nullable=False),
    _ref("order_proposal", "proposal_id"),
    sa.CheckConstraint("qty BETWEEN 1 AND 999", name="qty"),
    sa.CheckConstraint("unit_price_cents > 0", name="unit_price_cents"),
    sa.CheckConstraint("line_total_cents = qty * unit_price_cents", name="line_total_cents"),
)

handoff_request = _tenant_table(
    "handoff_request",
    sa.Column("conversation_id", sa.Uuid, nullable=False),
    sa.Column("customer_id", sa.Uuid, nullable=False),
    sa.Column("reason", sa.Text, nullable=False),
    sa.Column("note", sa.Text),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    _ref("conversation", "conversation_id"),
    sa.CheckConstraint(
        "reason IN ('exception_request', 'complaint', 'out_of_scope', 'agent_refusal', 'other')",
        name="reason",
    ),
    sa.CheckConstraint("char_length(note) <= 500", name="note"),
)

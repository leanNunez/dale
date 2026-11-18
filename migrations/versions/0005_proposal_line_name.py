"""Product names on proposal lines (B61), so the summary the customer sees names each product.

The name comes from management's quote, never from the model. A database that already holds
proposal lines cannot take the NOT NULL column: forward-only, it is rebuilt and reseeded.

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"

DDL = """
ALTER TABLE brain.order_proposal_line
  ADD COLUMN product_name text NOT NULL,
  ADD CONSTRAINT ck_order_proposal_line_product_name CHECK (btrim(product_name) <> '');
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    raise NotImplementedError("forward-only migration: rebuild the database instead")

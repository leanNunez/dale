"""At most one prepared proposal per conversation (design §5, B62).

`save_prepared` already locks the conversation row; this index makes the database refuse a
second prepared proposal even if a caller skips that lock.

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"

DDL = """
CREATE UNIQUE INDEX ix_order_proposal_company_id_conversation_id
  ON brain.order_proposal (company_id, conversation_id) WHERE status = 'prepared';
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    raise NotImplementedError("forward-only migration: rebuild the database instead")

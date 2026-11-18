"""Conversation, proposal and handoff tables of the brain schema (design §5, D1, D6).

No foreign key leaves the schema: customer, product and order IDs cross by value.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"

DDL = """
CREATE TABLE brain.conversation (
  company_id uuid NOT NULL, id uuid NOT NULL, customer_id uuid NOT NULL,
  channel text NOT NULL, started_at timestamptz NOT NULL,
  CONSTRAINT pk_conversation PRIMARY KEY (company_id, id));

CREATE TABLE brain.order_proposal (
  company_id uuid NOT NULL, id uuid NOT NULL, conversation_id uuid NOT NULL,
  customer_id uuid NOT NULL, status text NOT NULL, rejection_code text, order_id uuid,
  delivery_date date NOT NULL, total_cents bigint NOT NULL, created_at timestamptz NOT NULL,
  CONSTRAINT pk_order_proposal PRIMARY KEY (company_id, id),
  CONSTRAINT fk_order_proposal_company_id_conversation_id
    FOREIGN KEY (company_id, conversation_id) REFERENCES brain.conversation (company_id, id),
  CONSTRAINT ck_order_proposal_status
    CHECK (status IN ('prepared', 'superseded', 'confirmed', 'rejected')),
  CONSTRAINT ck_order_proposal_order_id CHECK ((status = 'confirmed') = (order_id IS NOT NULL)),
  CONSTRAINT ck_order_proposal_rejection_code
    CHECK ((status = 'rejected') = (rejection_code IS NOT NULL)),
  CONSTRAINT ck_order_proposal_total_cents CHECK (total_cents > 0));

CREATE TABLE brain.order_proposal_line (
  company_id uuid NOT NULL, id uuid NOT NULL, proposal_id uuid NOT NULL,
  product_id uuid NOT NULL, qty integer NOT NULL, unit_price_cents bigint NOT NULL,
  line_total_cents bigint NOT NULL,
  CONSTRAINT pk_order_proposal_line PRIMARY KEY (company_id, id),
  CONSTRAINT fk_order_proposal_line_company_id_proposal_id
    FOREIGN KEY (company_id, proposal_id) REFERENCES brain.order_proposal (company_id, id),
  CONSTRAINT ck_order_proposal_line_qty CHECK (qty BETWEEN 1 AND 999),
  CONSTRAINT ck_order_proposal_line_unit_price_cents CHECK (unit_price_cents > 0),
  CONSTRAINT ck_order_proposal_line_line_total_cents
    CHECK (line_total_cents = qty * unit_price_cents));

CREATE TABLE brain.handoff_request (
  company_id uuid NOT NULL, id uuid NOT NULL, conversation_id uuid NOT NULL,
  customer_id uuid NOT NULL, reason text NOT NULL, note text, created_at timestamptz NOT NULL,
  CONSTRAINT pk_handoff_request PRIMARY KEY (company_id, id),
  CONSTRAINT fk_handoff_request_company_id_conversation_id
    FOREIGN KEY (company_id, conversation_id) REFERENCES brain.conversation (company_id, id),
  CONSTRAINT ck_handoff_request_reason CHECK (reason IN
    ('exception_request', 'complaint', 'out_of_scope', 'agent_refusal', 'other')),
  CONSTRAINT ck_handoff_request_note CHECK (char_length(note) <= 500));
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    raise NotImplementedError("forward-only migration: rebuild the database instead")

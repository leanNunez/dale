"""Management tables of the erp schema (design §5, D3).

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"

DDL = """
CREATE TABLE erp.company (
  id uuid NOT NULL, slug text NOT NULL, name text NOT NULL, timezone text NOT NULL,
  CONSTRAINT pk_company PRIMARY KEY (id),
  CONSTRAINT uq_company_slug UNIQUE (slug));

CREATE TABLE erp.zone (
  company_id uuid NOT NULL, id uuid NOT NULL, name text NOT NULL,
  delivery_weekdays smallint[] NOT NULL, cutoff_time time NOT NULL,
  min_order_amount_cents bigint NOT NULL,
  CONSTRAINT pk_zone PRIMARY KEY (company_id, id),
  CONSTRAINT fk_zone_company_id FOREIGN KEY (company_id) REFERENCES erp.company (id),
  CONSTRAINT ck_zone_delivery_weekdays CHECK (cardinality(delivery_weekdays) > 0
    AND array_ndims(delivery_weekdays) = 1 AND delivery_weekdays <@ '{1,2,3,4,5,6,7}'
    AND array_to_string(delivery_weekdays, '') !~ '(.).*\\1'),
  CONSTRAINT ck_zone_min_order_amount_cents CHECK (min_order_amount_cents >= 0));

CREATE TABLE erp.customer (
  company_id uuid NOT NULL, id uuid NOT NULL, code text NOT NULL, name text NOT NULL,
  zone_id uuid NOT NULL, active boolean NOT NULL,
  CONSTRAINT pk_customer PRIMARY KEY (company_id, id),
  CONSTRAINT fk_customer_company_id_zone_id FOREIGN KEY (company_id, zone_id)
    REFERENCES erp.zone (company_id, id),
  CONSTRAINT uq_customer_company_id_code UNIQUE (company_id, code));

CREATE TABLE erp.product (
  company_id uuid NOT NULL, id uuid NOT NULL, sku text NOT NULL, name text NOT NULL,
  brand text NOT NULL, presentation text NOT NULL, search_terms text NOT NULL,
  active boolean NOT NULL,
  CONSTRAINT pk_product PRIMARY KEY (company_id, id),
  CONSTRAINT fk_product_company_id FOREIGN KEY (company_id) REFERENCES erp.company (id),
  CONSTRAINT uq_product_company_id_sku UNIQUE (company_id, sku));

CREATE TABLE erp.product_price (
  company_id uuid NOT NULL, product_id uuid NOT NULL, valid_from timestamptz NOT NULL,
  unit_price_cents bigint NOT NULL,
  CONSTRAINT pk_product_price PRIMARY KEY (company_id, product_id, valid_from),
  CONSTRAINT fk_product_price_company_id_product_id FOREIGN KEY (company_id, product_id)
    REFERENCES erp.product (company_id, id),
  CONSTRAINT ck_product_price_unit_price_cents CHECK (unit_price_cents > 0));

CREATE TABLE erp.sales_order (
  company_id uuid NOT NULL, id uuid NOT NULL, proposal_id uuid NOT NULL,
  customer_id uuid NOT NULL, delivery_date date NOT NULL, total_cents bigint NOT NULL,
  received_at timestamptz NOT NULL,
  CONSTRAINT pk_sales_order PRIMARY KEY (company_id, id),
  CONSTRAINT fk_sales_order_company_id_customer_id FOREIGN KEY (company_id, customer_id)
    REFERENCES erp.customer (company_id, id),
  CONSTRAINT uq_sales_order_company_id_proposal_id UNIQUE (company_id, proposal_id),
  CONSTRAINT ck_sales_order_total_cents CHECK (total_cents > 0));

CREATE TABLE erp.sales_order_line (
  company_id uuid NOT NULL, id uuid NOT NULL, order_id uuid NOT NULL,
  product_id uuid NOT NULL, qty integer NOT NULL, unit_price_cents bigint NOT NULL,
  line_total_cents bigint NOT NULL,
  CONSTRAINT pk_sales_order_line PRIMARY KEY (company_id, id),
  CONSTRAINT fk_sales_order_line_company_id_order_id FOREIGN KEY (company_id, order_id)
    REFERENCES erp.sales_order (company_id, id),
  CONSTRAINT fk_sales_order_line_company_id_product_id FOREIGN KEY (company_id, product_id)
    REFERENCES erp.product (company_id, id),
  CONSTRAINT ck_sales_order_line_qty CHECK (qty BETWEEN 1 AND 999),
  CONSTRAINT ck_sales_order_line_unit_price_cents CHECK (unit_price_cents > 0),
  CONSTRAINT ck_sales_order_line_line_total_cents
    CHECK (line_total_cents = qty * unit_price_cents));
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    raise NotImplementedError("forward-only migration: rebuild the database instead")

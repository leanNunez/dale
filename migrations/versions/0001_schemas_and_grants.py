"""The erp and brain schemas and their grants (design §2, §5). No cross-schema foreign keys.

Default privileges are set before any table exists, so every table dale_owner creates in
these schemas gets the same grants: dale_app reads and writes rows, dale_verifier only reads
(R11). Neither may run DDL: they get USAGE on the schemas, never CREATE, and own nothing.
PUBLIC loses TEMPORARY on the database, so neither can create temporary tables either. The
owner of the database runs this, so the revoke works wherever the database was created.

Revision ID: 0001
Revises: none
"""

from alembic import op

revision = "0001"
down_revision = None

DDL = """
CREATE SCHEMA erp;
CREATE SCHEMA brain;
GRANT USAGE ON SCHEMA erp, brain TO dale_app, dale_verifier;
ALTER DEFAULT PRIVILEGES IN SCHEMA erp, brain
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO dale_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA erp, brain GRANT SELECT ON TABLES TO dale_verifier;
DO $$ BEGIN
  EXECUTE 'REVOKE TEMPORARY ON DATABASE ' || quote_ident(current_database()) || ' FROM PUBLIC';
END $$;
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    raise NotImplementedError("forward-only migration: rebuild the database instead")

-- Dale database roles. Run as a superuser, then create the database owned by dale_owner and
-- migrate as dale_owner:
--   psql -v ON_ERROR_STOP=1 -f db/roles.sql && createdb --owner=dale_owner dale
--   DALE_OWNER_DATABASE_URL=postgresql+psycopg://dale_owner@127.0.0.1/dale alembic upgrade head
-- No passwords live in this file. Dev and CI servers trust local connections. Production will
-- run this same file through deploy/db/init.sh (planned, slice 14), which then sets each
-- role's password from root-only files on the server (design DD30, §9; release-gate G9).
-- Grants on every schema (erp, brain, demo) are in migrations/; dale_verifier gets none on demo.
DO $$
DECLARE
  r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['dale_owner', 'dale_app', 'dale_verifier'] LOOP
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('CREATE ROLE %I', r);
    END IF;
    EXECUTE format('ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION'
                   ' NOBYPASSRLS', r);
  END LOOP;
END
$$;

-- The verifier only reads (R11). The real guarantee is its SELECT-only grant; this setting
-- makes an accidental write fail even before the privilege check.
ALTER ROLE dale_verifier SET default_transaction_read_only = on;

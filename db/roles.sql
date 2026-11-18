-- Dale database roles, for dev and CI only. Run as a superuser, then create the database
-- owned by dale_owner and migrate as dale_owner:
--   psql -v ON_ERROR_STOP=1 -f db/roles.sql && createdb --owner=dale_owner dale
--   DALE_OWNER_DATABASE_URL=postgresql+psycopg://dale_owner@127.0.0.1/dale alembic upgrade head
-- No passwords live here: dev and CI servers trust local connections. Anywhere else, set
-- them interactively with \password. Grants on the erp and brain schemas are in migrations/.
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

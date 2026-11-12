"""DB role privileges on a freshly migrated database (R11 S11.3, design §5)."""

import psycopg
import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.integration

DENIED = [
    ("dale_verifier", "INSERT INTO erp.company VALUES (gen_random_uuid(), 'x', 'x', 'UTC')"),
    ("dale_verifier", "UPDATE erp.sales_order SET total_cents = total_cents"),
    ("dale_verifier", "DELETE FROM erp.sales_order_line"),
    ("dale_verifier", "TRUNCATE erp.product"),
    ("dale_verifier", "CREATE TABLE erp.x (id int)"),
    ("dale_app", "CREATE TABLE erp.x (id int)"),
    ("dale_app", "CREATE TABLE brain.x (id int)"),
    ("dale_app", "CREATE TABLE public.x (id int)"),
    ("dale_app", "CREATE SCHEMA x"),
    ("dale_app", "ALTER TABLE erp.zone ADD COLUMN x int"),
    ("dale_app", "TRUNCATE erp.product"),
]


def _sqlstate(err: pytest.ExceptionInfo[DBAPIError]) -> str | None:
    assert isinstance(err.value.orig, psycopg.Error)
    return err.value.orig.sqlstate


@pytest.mark.parametrize(("role", "sql"), DENIED)
def test_privilege_denied(engines: dict[str, Engine], role: str, sql: str) -> None:
    """Even in a read-write transaction: the grant, not the session setting, is the guarantee."""
    with engines[role].connect() as conn:
        conn.exec_driver_sql("SET TRANSACTION READ WRITE")
        with pytest.raises(DBAPIError) as err:
            conn.exec_driver_sql(sql)
    assert _sqlstate(err) == "42501"  # insufficient_privilege


def test_verifier_sessions_are_read_only_by_default(engines: dict[str, Engine]) -> None:
    with engines["dale_verifier"].connect() as conn:
        assert conn.exec_driver_sql("SHOW default_transaction_read_only").scalar_one() == "on"
        with pytest.raises(DBAPIError) as err:
            conn.exec_driver_sql("CREATE TABLE erp.x (id int)")
    assert _sqlstate(err) == "25006"  # read_only_sql_transaction


def test_grants_cover_every_table_including_future_ones(engines: dict[str, Engine]) -> None:
    with engines["dale_owner"].connect() as conn:  # rolled back on exit
        conn.exec_driver_sql("CREATE TABLE erp.later (id int); CREATE TABLE brain.later (id int)")
        grants = conn.execute(
            text("""
            SELECT r.role, array_to_string(ARRAY(
              SELECT p FROM unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE',
                                         'REFERENCES', 'TRIGGER']) p
              WHERE has_table_privilege(r.role, c.oid, p)), ',')
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            CROSS JOIN unnest(ARRAY['dale_app', 'dale_verifier', 'public']) r(role)
            WHERE n.nspname IN ('erp', 'brain') AND c.relkind = 'r'""")
        ).all()
    assert {tuple(row) for row in grants} == {
        ("dale_app", "SELECT,INSERT,UPDATE,DELETE"),
        ("dale_verifier", "SELECT"),
        ("public", ""),
    }


def test_no_write_or_public_grant_hides_at_column_level(engines: dict[str, Engine]) -> None:
    """A per-column grant is invisible to has_table_privilege; has_any_column_privilege sees it."""
    with engines["dale_owner"].connect() as conn:
        leaks = conn.execute(
            text("""
            SELECT c.oid::regclass::text, g.role, g.priv
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            CROSS JOIN (VALUES ('dale_verifier', 'INSERT'), ('dale_verifier', 'UPDATE'),
              ('dale_verifier', 'REFERENCES'), ('public', 'SELECT'), ('public', 'INSERT'),
              ('public', 'UPDATE'), ('public', 'REFERENCES')) g(role, priv)
            WHERE n.nspname IN ('erp', 'brain') AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
              AND has_any_column_privilege(g.role, c.oid, g.priv)""")
        ).all()
    assert leaks == []


def test_public_gets_nothing_in_the_dale_schemas_or_the_database(
    engines: dict[str, Engine],
) -> None:
    with engines["dale_owner"].connect() as conn:
        schemas = conn.execute(
            text("""
            SELECT s, p FROM unnest(ARRAY['erp', 'brain']) s, unnest(ARRAY['USAGE', 'CREATE']) p
            WHERE has_schema_privilege('public', s, p)""")
        ).all()
        default_acls = conn.execute(
            text(
                "SELECT d.defaclobjtype FROM pg_default_acl d, aclexplode(d.defaclacl) a"
                " WHERE a.grantee = 0"
            )  # 0 is PUBLIC
        ).all()
        temp = conn.execute(
            text("""
            SELECT r FROM unnest(ARRAY['dale_app', 'dale_verifier', 'public']) r
            WHERE has_database_privilege(r, current_database(), 'TEMPORARY')""")
        ).all()
    assert (schemas, default_acls, temp) == ([], [], [])

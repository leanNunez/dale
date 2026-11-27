"""Grants on the demo schema (design §5, R11 unchanged): dale_app gets exactly its per-table
privileges, and neither dale_verifier nor PUBLIC can even see the schema."""

import psycopg
import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError

from dale.apps.demo import tables as demo

pytestmark = pytest.mark.integration

PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
APP = {
    "control": {"SELECT", "UPDATE"},
    "host_status": {"SELECT", "INSERT", "UPDATE"},
    "spend_day": {"SELECT", "INSERT", "UPDATE"},
    "spend_request": {"SELECT", "INSERT", "UPDATE"},
    "counter": {"SELECT", "INSERT", "UPDATE", "DELETE"},
    "transcript": {"SELECT", "INSERT", "DELETE"},
    "transcript_event": {"SELECT", "INSERT", "DELETE"},
}
OUTSIDERS = ("dale_verifier", "public")
DENIED = [
    ("dale_verifier", "SELECT * FROM demo.control"),
    ("dale_verifier", "SELECT * FROM demo.spend_day"),
    ("dale_app", "INSERT INTO demo.control (id, paused, reason, changed_at)"
     " VALUES (2, false, 'operator', now())"),
    ("dale_app", "DELETE FROM demo.control"),
    ("dale_app", "UPDATE demo.transcript SET notice_version = notice_version"),
    ("dale_app", "DELETE FROM demo.spend_request"),
    ("dale_app", "TRUNCATE demo.counter"),
    ("dale_app", "CREATE TABLE demo.x (id int)"),
    ("dale_app", "ALTER TABLE demo.control ADD COLUMN x int"),
]  # fmt: skip


def _table_privileges(conn: Connection, role: str) -> dict[str, set[str]]:
    rows = conn.execute(
        text("""
        SELECT c.relname, p FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        CROSS JOIN unnest(CAST(:privileges AS text[])) p
        WHERE n.nspname = 'demo' AND c.relkind = 'r' AND has_table_privilege(:role, c.oid, p)"""),
        {"privileges": list(PRIVILEGES), "role": role},
    ).all()
    found: dict[str, set[str]] = {t.name: set() for t in demo.METADATA.sorted_tables}
    for table, privilege in rows:
        found[table].add(privilege)
    return found


def test_dale_app_gets_exactly_the_design_grants_table_by_table(
    engines: dict[str, Engine],
) -> None:
    with engines["dale_owner"].connect() as conn:
        assert _table_privileges(conn, "dale_app") == APP


@pytest.mark.parametrize("role", OUTSIDERS)
def test_the_verifier_and_public_get_nothing_on_demo(engines: dict[str, Engine], role: str) -> None:
    """Not USAGE, not CREATE, no table and no column privilege (R11: the verifier is unchanged)."""
    with engines["dale_owner"].connect() as conn:
        schema = [p for p in ("USAGE", "CREATE") if conn.execute(
            text("SELECT has_schema_privilege(:role, 'demo', :p)"), {"role": role, "p": p}
        ).scalar_one()]  # fmt: skip
        columns = conn.execute(
            text("""
            SELECT c.relname, p FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            CROSS JOIN unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'REFERENCES']) p
            WHERE n.nspname = 'demo' AND has_any_column_privilege(:role, c.oid, p)"""),
            {"role": role},
        ).all()
        tables = _table_privileges(conn, role)
    assert (schema, columns) == ([], [])
    assert tables == {name: set() for name in APP}


def test_dale_app_may_use_the_schema_but_not_create_in_it(engines: dict[str, Engine]) -> None:
    with engines["dale_owner"].connect() as conn:
        usage, create = conn.execute(
            text("SELECT has_schema_privilege('dale_app', 'demo', p) FROM unnest("
                 "ARRAY['USAGE', 'CREATE']) WITH ORDINALITY u(p, o) ORDER BY o")
        ).scalars()  # fmt: skip
    assert (usage, create) == (True, False)


def test_no_column_grant_widens_a_table_grant(engines: dict[str, Engine]) -> None:
    """has_table_privilege misses a per-column grant; has_any_column_privilege sees it."""
    with engines["dale_owner"].connect() as conn:
        widened = [
            (table, p)
            for table, granted in APP.items()
            for p in ("INSERT", "UPDATE", "REFERENCES")
            if p not in granted
            and conn.execute(
                text("SELECT has_any_column_privilege('dale_app', :t, :p)"),
                {"t": f"demo.{table}", "p": p},
            ).scalar_one()
        ]
    assert widened == []


def test_no_default_privileges_and_a_later_table_gets_nothing(
    engines: dict[str, Engine],
) -> None:
    """0001's default privileges name erp and brain only; nothing widens a future demo table."""
    with engines["dale_owner"].connect() as conn:  # rolled back on exit
        defaults = conn.execute(
            text("""
            SELECT d.defaclrole::regrole::text FROM pg_default_acl d
            WHERE d.defaclnamespace IN (0, 'demo'::regnamespace)""")
        ).all()
        conn.exec_driver_sql("CREATE TABLE demo.later (id int)")
        later = conn.execute(
            text("""
            SELECT r, p FROM unnest(ARRAY['dale_app', 'dale_verifier', 'public']) r,
              unnest(CAST(:privileges AS text[])) p
            WHERE has_table_privilege(r, 'demo.later', p)"""),
            {"privileges": list(PRIVILEGES)},
        ).all()
    assert (defaults, later) == ([], [])


def test_dale_owner_owns_the_schema_and_every_table(engines: dict[str, Engine]) -> None:
    with engines["dale_owner"].connect() as conn:
        owners = conn.execute(
            text("""
            SELECT nspowner::regrole::text FROM pg_namespace WHERE nspname = 'demo'
            UNION SELECT tableowner FROM pg_tables WHERE schemaname = 'demo'""")
        ).scalars()
        assert list(owners) == ["dale_owner"]


@pytest.mark.parametrize(("role", "sql"), DENIED)
def test_privilege_denied(engines: dict[str, Engine], role: str, sql: str) -> None:
    """Even in a read-write transaction: the grant, not the session setting, is the guarantee."""
    with engines[role].connect() as conn:
        conn.exec_driver_sql("SET TRANSACTION READ WRITE")
        with pytest.raises(DBAPIError) as err:
            conn.exec_driver_sql(sql)
    assert isinstance(err.value.orig, psycopg.Error)
    assert err.value.orig.sqlstate == "42501"  # insufficient_privilege

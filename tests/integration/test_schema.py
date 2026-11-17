"""Schema invariants of a freshly migrated database (R15 S15.1, design §5 and §11)."""

from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, Row, text

from dale.erp_sim.infrastructure.tables import METADATA as ERP
from tests.conftest import alembic_config

pytestmark = pytest.mark.integration

METADATAS = (ERP,)
TENANT_ROOT = ("erp", "company")  # its own id is the company_id of every other row

CONSTRAINTS = """
SELECT n.nspname AS schema, t.relname AS tbl, c.conname AS name, c.contype AS type,
       c.confrelid::regclass::text AS ref, array_agg(a.attname::text ORDER BY k.ord) AS cols,
       array_agg(f.attname::text ORDER BY k.ord) AS refcols  -- paired with cols by position
FROM pg_constraint c
JOIN pg_class t ON t.oid = c.conrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
CROSS JOIN unnest(c.conkey, c.confkey) WITH ORDINALITY AS k(attnum, refnum, ord)
JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
LEFT JOIN pg_attribute f ON f.attrelid = c.confrelid AND f.attnum = k.refnum
WHERE n.nspname IN ('erp', 'brain')
GROUP BY 1, 2, 3, 4, 5
"""

# Every constraint and index with its definition as the catalog prints it.
DEFINITIONS = """
SELECT n.nspname, t.relname, c.conname, pg_get_constraintdef(c.oid)
FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
UNION ALL
SELECT n.nspname, t.relname, i.relname, pg_get_indexdef(i.oid)
FROM pg_index x JOIN pg_class i ON i.oid = x.indexrelid JOIN pg_class t ON t.oid = x.indrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
"""


@pytest.fixture(scope="module")
def constraints(engines: dict[str, Engine]) -> list[Row[Any]]:
    with engines["dale_owner"].connect() as conn:
        return list(conn.execute(text(CONSTRAINTS)))


def test_every_table_has_a_non_null_company_id(engines: dict[str, Engine]) -> None:
    with engines["dale_owner"].connect() as conn:
        rows = conn.execute(
            text("""
            SELECT t.table_schema, t.table_name, c.is_nullable
            FROM information_schema.tables t
            LEFT JOIN information_schema.columns c ON c.table_schema = t.table_schema
              AND c.table_name = t.table_name AND c.column_name = 'company_id'
            WHERE t.table_schema IN ('erp', 'brain')""")
        ).all()
    assert len(rows) == sum(len(m.tables) for m in METADATAS)
    assert [r for r in rows if r[2] != "NO" and (r[0], r[1]) != TENANT_ROOT] == []


def test_keys_and_unique_constraints_include_company_id(constraints: list[Row[Any]]) -> None:
    keys = [r for r in constraints if r.type in ("p", "u", "f")]
    root = [r for r in keys if (r.schema, r.tbl) == TENANT_ROOT]
    assert sorted(r.name for r in root) == ["pk_company", "uq_company_slug"]
    assert [r.name for r in keys if r not in root and "company_id" not in r.cols] == []


def test_primary_keys_start_with_company_id(constraints: list[Row[Any]]) -> None:
    """(company_id, id), or a natural composite key led by company_id (product_price)."""
    pks = [r for r in constraints if r.type == "p" and (r.schema, r.tbl) != TENANT_ROOT]
    assert pks
    assert [r.name for r in pks if r.cols[0] != "company_id" or len(r.cols) < 2] == []


def test_foreign_keys_stay_in_their_schema_and_company(constraints: list[Row[Any]]) -> None:
    """company_id must reference company_id (the tenant root's id), not merely be listed."""
    fks = [r for r in constraints if r.type == "f"]
    assert fks
    assert [r.name for r in fks if r.ref.split(".")[0] != r.schema] == []
    target = {r.name: "id" if r.ref == ".".join(TENANT_ROOT) else "company_id" for r in fks}
    mapped = {r.name: dict(zip(r.cols, r.refcols, strict=True)).get("company_id") for r in fks}
    assert mapped == target


def test_money_columns_are_bigint_not_null(engines: dict[str, Engine]) -> None:
    with engines["dale_owner"].connect() as conn:
        cents = conn.execute(
            text(
                "SELECT table_name, column_name, data_type, is_nullable FROM information_schema"
                ".columns WHERE table_schema IN ('erp', 'brain') AND column_name ~ '_cents$'"
            )
        ).all()
    assert cents and [c for c in cents if c[2:] != ("bigint", "NO")] == []


def test_every_constraint_name_follows_the_convention(constraints: list[Row[Any]]) -> None:
    def ok(r: Row[Any]) -> bool:
        cols = "_".join(r.cols)
        exact = {"p": f"pk_{r.tbl}", "u": f"uq_{r.tbl}_{cols}", "f": f"fk_{r.tbl}_{cols}"}
        if r.type == "c":
            return bool(r.name.startswith(f"ck_{r.tbl}_"))
        return bool(r.name == exact.get(r.type))

    assert [r.name for r in constraints if not ok(r)] == []


def test_database_and_metadata_define_the_same_constraints(engines: dict[str, Engine]) -> None:
    """Names and bodies: the metadata is built in scratch schemas (rolled back) and the
    catalog's own text of every constraint and index is compared, CHECK bodies included."""
    scratch = {m.schema: f"expected_{m.schema}" for m in METADATAS if m.schema}
    with engines["dale_owner"].connect() as conn:
        conn.exec_driver_sql("; ".join(f"CREATE SCHEMA {s}" for s in scratch.values()))
        for m in METADATAS:
            m.create_all(conn.execution_options(schema_translate_map=scratch), checkfirst=False)
        rows = conn.execute(text(DEFINITIONS)).all()
    defs = {(s, t, n): d for s, t, n, d in rows}
    assert {k: d for k, d in defs.items() if k[0] in scratch} == {
        (s.removeprefix("expected_"), t, n): d.replace("expected_", "")
        for (s, t, n), d in defs.items()
        if s in scratch.values()
    }


def test_alembic_check_is_clean(migrated_db: None) -> None:
    command.check(alembic_config())


def test_migrations_refuse_to_run_as_another_role(migrated_db: None) -> None:
    with pytest.raises(RuntimeError, match="must run as dale_owner"):
        command.upgrade(alembic_config("dale_app"), "head")


def test_no_table_outside_the_dale_schemas(engines: dict[str, Engine]) -> None:
    """Every schema and grant check looks only at erp and brain; nothing else may hold data."""
    with engines["dale_owner"].connect() as conn:
        tables = conn.execute(
            text("""
            SELECT n.nspname || '.' || c.relname
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f')
              AND n.nspname NOT IN ('erp', 'brain', 'information_schema')
              AND n.nspname !~ '^pg_'""")
        ).scalars()
        assert list(tables) == ["public.alembic_version"]

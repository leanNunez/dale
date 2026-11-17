"""Schema invariants of a freshly migrated database (design §5 and §11)."""

import pytest
from alembic import command
from sqlalchemy import Engine, text

from tests.conftest import alembic_config

pytestmark = pytest.mark.integration


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

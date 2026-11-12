"""Migrations are forward-only and online-only: every downgrade() raises, --sql is refused
(design §11)."""

import importlib.util
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = sorted((ROOT / "migrations" / "versions").glob("*.py"))


def test_migrations_exist() -> None:
    assert VERSIONS


@pytest.mark.parametrize("path", VERSIONS, ids=lambda p: p.stem)
def test_downgrade_raises(path: Path) -> None:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(NotImplementedError, match="forward-only"):
        module.downgrade()


def test_offline_sql_mode_is_refused() -> None:
    """--sql would print DDL that skips the owner check, so env.py refuses it outright."""
    with pytest.raises(RuntimeError, match="offline"):
        command.upgrade(Config(toml_file=ROOT / "pyproject.toml"), "head", sql=True)

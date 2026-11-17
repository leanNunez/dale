"""Database fixtures: one fresh, migrated database per session, one engine per Dale role.

The server comes from DALE_TEST_ADMIN_URL (a superuser on a local, trust-auth Postgres 17;
the default matches the CI service). pytest-socket blocks only Python sockets: libpq opens
its own, so admin_url() itself refuses any server that is not on this machine.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import URL, Engine, create_engine, make_url

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ADMIN_URL = "postgresql+psycopg://postgres@127.0.0.1:5432/postgres"
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")
TEST_DB = "dale_test"
ROLES = ("dale_owner", "dale_app", "dale_verifier")


def admin_url() -> URL:
    """DALE_TEST_ADMIN_URL, refused before any SQL unless its server is on this machine."""
    url = make_url(os.environ.get("DALE_TEST_ADMIN_URL", DEFAULT_ADMIN_URL))
    # libpq lets these win over the URL host, so any of them could reach another machine.
    redirects = [key for key in ("host", "hostaddr", "service") if key in url.query]
    redirects += [var for var in ("PGHOSTADDR", "PGSERVICE") if os.environ.get(var)]
    if url.host not in LOCAL_HOSTS or redirects:
        raise RuntimeError(
            f"tests run only against a local server: DALE_TEST_ADMIN_URL host is {url.host!r}"
            f" (allowed: {', '.join(LOCAL_HOSTS)}), libpq redirects: {redirects or 'none'}"
        )
    return url


def role_url(role: str) -> str:
    url = admin_url().set(username=role, password=None, database=TEST_DB)
    return url.render_as_string(hide_password=False)


def alembic_config(role: str = "dale_owner") -> Config:
    return Config(toml_file=ROOT / "pyproject.toml", attributes={"url": role_url(role)})


@pytest.fixture(scope="session")
def migrated_db() -> Iterator[None]:
    admin = admin_url().set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute((ROOT / "db" / "roles.sql").read_text())  # no params: sent as-is
        conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {TEST_DB} OWNER dale_owner")
    command.upgrade(alembic_config(), "head")
    yield
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE {TEST_DB} WITH (FORCE)")


@pytest.fixture(scope="session")
def engines(migrated_db: None) -> Iterator[dict[str, Engine]]:
    engines = {role: create_engine(role_url(role)) for role in ROLES}
    yield engines
    for engine in engines.values():
        engine.dispose()

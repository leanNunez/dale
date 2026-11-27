"""Alembic environment: online only, run as dale_owner (design §5), forward-only."""

import os

from alembic import context
from sqlalchemy import create_engine, pool, text

from dale.apps.demo.tables import METADATA as DEMO
from dale.brain.infrastructure.tables import METADATA as BRAIN
from dale.erp_sim.infrastructure.tables import METADATA as ERP

OWNER = "dale_owner"
SCHEMAS = {"erp", "brain", "demo"}


def include_name(name: str | None, type_: str, parent_names: object) -> bool:
    """Compare only the Dale schemas; the default schema holds just alembic_version."""
    return type_ != "schema" or name in SCHEMAS


if context.is_offline_mode():
    raise RuntimeError("offline (--sql) mode is not supported")
url = context.config.attributes.get("url") or os.environ["DALE_OWNER_DATABASE_URL"]
with create_engine(url, poolclass=pool.NullPool).begin() as connection:
    # Tables must belong to dale_owner, or the default privileges in 0001 never apply (demo
    # has none: 0006 grants its tables one by one).
    user = connection.execute(text("SELECT current_user")).scalar_one()
    if user != OWNER:
        raise RuntimeError(f"migrations must run as {OWNER}, not {user}")
    context.configure(
        connection=connection,
        target_metadata=[ERP, BRAIN, DEMO],
        include_schemas=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()

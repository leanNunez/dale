"""Empties one company's `brain` rows (B21, B24). `erp_sim` reseed owns only `erp` and may not
reach these tables, so whoever resets a run (the eval harness) resets the brain through this."""

from uuid import UUID

import sqlalchemy as sa

from dale.brain.infrastructure import tables as t


def reset_brain(engine: sa.Engine, company_id: UUID) -> None:
    """Deletes conversations, proposals, proposal lines and handoffs of `company_id`, children
    first, in one transaction. Other companies keep their rows."""
    with engine.begin() as conn:
        for table in reversed(t.METADATA.sorted_tables):
            conn.execute(sa.delete(table).where(table.c.company_id == company_id))

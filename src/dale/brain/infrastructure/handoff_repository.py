"""Handoff requests in `brain.handoff_request` (D1, R7), SQLAlchemy Core. The row is copied
from the session's own conversation row, found by company_id (R15), conversation and customer."""

from uuid import uuid4

import sqlalchemy as sa

from dale.brain.domain.handoff import HandoffReason
from dale.brain.domain.session import SessionContext
from dale.brain.infrastructure import tables as t
from dale.brain.infrastructure.proposal_repository import of_company

COLUMNS = ("company_id", "id", "conversation_id", "customer_id", "reason", "note", "created_at")


class SqlHandoffRepository:
    def __init__(self, engine: sa.Engine) -> None:
        self._engine = engine

    def request_handoff(
        self, session: SessionContext, reason: HandoffReason, note: str | None
    ) -> None:
        c = t.conversation
        mine = (of_company(c, session.company_id), c.c.id == session.conversation_id)
        row = sa.select(  # in COLUMNS order
            c.c.company_id,
            sa.literal(uuid4(), sa.Uuid),
            c.c.id,
            c.c.customer_id,
            sa.literal(reason.value),
            sa.literal(note, sa.Text),
            sa.func.now(),
        ).where(*mine, c.c.customer_id == session.customer_id)
        write = sa.insert(t.handoff_request).from_select(COLUMNS, row).returning(sa.literal(1))
        with self._engine.begin() as conn:  # a wrong count rolls back: nothing is written
            if len(conn.execute(write).all()) != 1:
                raise RuntimeError("a handoff needs its conversation row")  # a wiring bug

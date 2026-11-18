"""The session's `brain.conversation` row (B61), keyed by company and id (R15). Opening it
again is a no-op; a row with that key for another customer is a wiring bug and raises."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from dale.brain.domain.session import SessionContext
from dale.brain.infrastructure import tables as t
from dale.brain.infrastructure.proposal_repository import of_company
from dale.shared.clock import Clock


class SqlConversationRepository:
    def __init__(self, engine: sa.Engine, clock: Clock, channel: str) -> None:
        self._engine, self._clock, self._channel = engine, clock, channel

    def open(self, session: SessionContext) -> None:
        c, company = t.conversation, session.company_id
        row = {"company_id": company, "id": session.conversation_id, "channel": self._channel}
        row |= {"customer_id": session.customer_id, "started_at": self._clock.now()}
        write = (
            insert(c).values(row).on_conflict_do_nothing(index_elements=[c.c.company_id, c.c.id])
        )
        owner = sa.select(c.c.customer_id).where(
            of_company(c, company), c.c.id == session.conversation_id
        )
        with self._engine.begin() as conn:
            conn.execute(write)
            if conn.execute(owner).scalar_one() != session.customer_id:
                raise RuntimeError("the conversation row belongs to another customer")

"""The session's conversation row on a real database (B61, R15): opened once, keyed by company,
and never taken over by another customer."""

from uuid import uuid4

import pytest
from sqlalchemy import Engine

from dale.brain.domain.session import SessionContext
from dale.brain.infrastructure import tables as t
from dale.brain.infrastructure.conversation_repository import SqlConversationRepository
from dale.shared.clock import FrozenClock
from dale.shared.ids import ConversationId, CustomerId
from tests.integration.test_proposals import C001, HORNERO, NOW, TWIN, rows

pytestmark = pytest.mark.integration
COLUMNS = ("company_id", "id", "customer_id", "channel", "started_at")


def conversations(db: Engine) -> SqlConversationRepository:
    return SqlConversationRepository(db, FrozenClock(NOW), "terminal")


def test_opening_twice_writes_one_row_per_company_key(db: Engine) -> None:
    at = SessionContext(HORNERO, C001, ConversationId(uuid4()))
    twin = SessionContext(TWIN, C001, at.conversation_id)  # same id, another company's key
    for session in (at, at, twin):
        conversations(db).open(session)
    expected = {(s.company_id, s.conversation_id, C001, "terminal", NOW) for s in (at, twin)}
    assert set(rows(db, t.conversation, *COLUMNS)) == expected


def test_a_conversation_of_another_customer_is_never_taken_over(db: Engine) -> None:
    at = SessionContext(HORNERO, C001, ConversationId(uuid4()))
    conversations(db).open(at)
    with pytest.raises(RuntimeError, match="another customer"):
        conversations(db).open(SessionContext(HORNERO, CustomerId(uuid4()), at.conversation_id))
    assert rows(db, t.conversation, "customer_id") == [(C001,)]

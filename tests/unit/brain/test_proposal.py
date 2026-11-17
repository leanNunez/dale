"""An order proposal's lines and total always add up, and a new one is the session's."""

from dataclasses import replace
from datetime import date, datetime
from uuid import UUID

import pytest

from dale.brain.domain.proposal import OrderProposal, ProposalLine, ProposalStatus
from dale.brain.domain.session import GroundingLedger, SessionContext
from dale.shared.ids import CompanyId, ConversationId, CustomerId, ProductId, ProposalId
from dale.shared.money import Money

SESSION = SessionContext(
    CompanyId(UUID(int=1)), CustomerId(UUID(int=2)), ConversationId(UUID(int=3))
)
LINE = ProposalLine(ProductId(UUID(int=4)), 2, Money(245_000), Money(490_000))
AT = datetime.fromisoformat("2026-11-18T12:00:00+00:00")


def test_a_new_proposal_is_prepared_for_the_session() -> None:
    p = OrderProposal.prepared(
        ProposalId(UUID(int=5)), SESSION, (LINE,), Money(490_000), date(2026, 11, 19), AT
    )
    assert p.status is ProposalStatus.PREPARED
    assert (p.customer_id, p.conversation_id) == (SESSION.customer_id, SESSION.conversation_id)
    for change in (
        {"total": Money(1)},
        {"lines": ()},
        {"lines": (replace(LINE, line_total=Money(1)),)},
    ):
        with pytest.raises(ValueError):
            replace(p, **change)


def test_the_ledger_grounds_only_what_it_recorded() -> None:
    ledger = GroundingLedger()
    ledger.record([LINE.product_id])
    assert ledger.grounds(LINE.product_id) and not ledger.grounds(ProductId(UUID(int=6)))

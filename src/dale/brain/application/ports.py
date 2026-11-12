"""Ports of the brain's application layer (design §3, §7). Adapters live in infrastructure."""

from collections.abc import Sequence
from typing import Protocol

from dale.brain.domain.proposal import OrderProposal
from dale.brain.domain.session import SessionContext
from dale.erp_sim.public import Delivery, ProductMatch, ProductPrice, Quote, QuoteRequest
from dale.shared.errors import Result
from dale.shared.ids import CompanyId, CustomerId, ProductId, ProposalId


class ErpPort(Protocol):
    """The reads and the quote of `erp_sim.public.ErpFacade`, and no `confirm`: no tool can
    reach the only order write."""

    def search_products(
        self, company_id: CompanyId, query: str
    ) -> Result[tuple[ProductMatch, ...]]: ...

    def get_prices(
        self, company_id: CompanyId, product_ids: Sequence[ProductId]
    ) -> Result[tuple[ProductPrice, ...]]: ...

    def check_delivery(
        self, company_id: CompanyId, customer_id: CustomerId
    ) -> Result[Delivery]: ...

    def quote(self, company_id: CompanyId, request: QuoteRequest) -> Result[Quote]: ...


class ProposalRepository(Protocol):
    def save_prepared(self, company_id: CompanyId, proposal: OrderProposal) -> OrderProposal:
        """Stores `proposal` and supersedes its conversation's earlier prepared proposal in one
        transaction, then returns the stored row as read back."""
        ...

    def get(self, company_id: CompanyId, proposal_id: ProposalId) -> OrderProposal | None: ...


class HandoffPort(Protocol):
    """Declared here; slice 8 implements it against `brain.handoff_request` (D1)."""

    def request_handoff(self, session: SessionContext, reason: str, note: str | None) -> None: ...

"""Ports of the brain's application layer (design §3, §7). Adapters live in infrastructure."""

from collections.abc import Sequence
from contextlib import AbstractContextManager
from typing import Protocol

from dale.brain.domain.handoff import HandoffReason
from dale.brain.domain.proposal import OrderProposal, ProposalStatus
from dale.brain.domain.session import SessionContext
from dale.erp_sim.public import (
    ConfirmRequest,
    Delivery,
    OrderConfirmation,
    ProductMatch,
    ProductPrice,
    Quote,
    QuoteRequest,
)
from dale.shared.errors import ErrorCode, Result
from dale.shared.ids import CompanyId, ConversationId, CustomerId, OrderId, ProductId, ProposalId


class OrderLookup(Protocol):
    """Management is the source of truth for orders (B68); this read writes nothing."""

    def find_order(
        self, company_id: CompanyId, proposal_id: ProposalId
    ) -> Result[OrderConfirmation | None]: ...


class ErpPort(OrderLookup, Protocol):
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


class ConfirmPort(OrderLookup, Protocol):
    """Management's `confirm`, the only order write (B65). Only `ConfirmProposal` gets it."""

    def confirm(
        self, company_id: CompanyId, request: ConfirmRequest
    ) -> Result[OrderConfirmation]: ...


class LockedProposals(Protocol):
    """One conversation's proposals, in a transaction that holds its row lock (B68)."""

    def prepared(self) -> OrderProposal | None: ...

    def save_prepared(self, proposal: OrderProposal) -> OrderProposal: ...  # supersedes

    def mark_confirmed(
        self, proposal_id: ProposalId, order_id: OrderId, was: ProposalStatus = ...
    ) -> None:
        """Moves exactly one proposal in status `was` (prepared by default), or raises."""
        ...

    def withdraw(self, proposal_id: ProposalId) -> None:
        """Supersedes exactly one prepared proposal that was never shown (B75), or raises."""
        ...


class ProposalRepository(Protocol):
    def locked(
        self, company_id: CompanyId, conversation_id: ConversationId
    ) -> AbstractContextManager[LockedProposals]:
        """Locks the conversation row, so its prepares and presses never interleave."""
        ...

    def get(self, company_id: CompanyId, proposal_id: ProposalId) -> OrderProposal | None: ...


class LockedConfirmable(Protocol):
    """What a Dale press reads and marks while it holds the conversation row lock (B68)."""

    def get(self, proposal_id: ProposalId) -> OrderProposal | None: ...

    def mark_confirmed(
        self, proposal_id: ProposalId, order_id: OrderId, was: ProposalStatus = ...
    ) -> None: ...

    def mark_rejected(self, proposal_id: ProposalId, code: ErrorCode) -> None: ...  # prepared


class ConfirmableProposals(Protocol):
    def locked(
        self, company_id: CompanyId, conversation_id: ConversationId
    ) -> AbstractContextManager[LockedConfirmable]: ...


class HandoffPort(Protocol):
    def request_handoff(
        self, session: SessionContext, reason: HandoffReason, note: str | None
    ) -> None:
        """One request for the session's conversation and customer (D1); raises on failure."""
        ...


class ConversationPort(Protocol):
    def open(self, session: SessionContext) -> None:
        """The session's `brain.conversation` row, written once (B61); raises on failure."""
        ...

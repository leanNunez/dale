"""The only erp_sim surface (design §2, contract 3): DTOs and the facade protocol."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from dale.shared.errors import Result
from dale.shared.ids import CompanyId, CustomerId, OrderId, ProductId, ProposalId
from dale.shared.money import Money


@dataclass(frozen=True, slots=True)
class QuoteLineRequest:
    product_id: ProductId
    quantity: int


@dataclass(frozen=True, slots=True)
class QuoteRequest:
    customer_id: CustomerId
    lines: tuple[QuoteLineRequest, ...]


@dataclass(frozen=True, slots=True)
class QuoteLine:
    product_id: ProductId
    quantity: int
    unit_price: Money  # the current server price; never one supplied by a caller
    line_total: Money


@dataclass(frozen=True, slots=True)
class Quote:
    customer_id: CustomerId
    lines: tuple[QuoteLine, ...]
    total: Money
    delivery_date: date
    quoted_at: datetime


@dataclass(frozen=True, slots=True)
class ProductMatch:
    product_id: ProductId
    sku: str
    name: str
    brand: str
    presentation: str


@dataclass(frozen=True, slots=True)
class ProductPrice:
    product_id: ProductId
    unit_price: Money


@dataclass(frozen=True, slots=True)
class Delivery:
    delivery_date: date
    order_by: datetime  # an order from this instant on goes to a later delivery
    minimum: Money  # the zone's minimum order amount


@dataclass(frozen=True, slots=True)
class ConfirmLine:
    product_id: ProductId
    quantity: int
    unit_price: Money  # the price the customer was shown


@dataclass(frozen=True, slots=True)
class ConfirmRequest:
    """What the customer was shown. `proposal_id` is the idempotency key."""

    proposal_id: ProposalId
    customer_id: CustomerId
    lines: tuple[ConfirmLine, ...]
    delivery_date: date
    total: Money


@dataclass(frozen=True, slots=True)
class OrderConfirmation:
    """Built from the stored order only; a replay of the same proposal returns an equal one."""

    order_id: OrderId
    proposal_id: ProposalId
    customer_id: CustomerId
    lines: tuple[QuoteLine, ...]  # ordered by product id, then quantity
    total: Money
    delivery_date: date
    received_at: datetime
    message: str  # customer-facing, from the stored order; never from model text


class ErpFacade(Protocol):
    """Reads and quotes write nothing. Unreadable data gives rules_unavailable, never a pass."""

    def search_products(
        self, company_id: CompanyId, query: str
    ) -> Result[tuple[ProductMatch, ...]]:
        """Active products only, best match first."""
        ...

    def get_prices(
        self, company_id: CompanyId, product_ids: Sequence[ProductId]
    ) -> Result[tuple[ProductPrice, ...]]:
        """Current prices; unknown, inactive or unpriced products are left out."""
        ...

    def check_delivery(
        self, company_id: CompanyId, customer_id: CustomerId
    ) -> Result[Delivery]: ...

    def quote(self, company_id: CompanyId, request: QuoteRequest) -> Result[Quote]:
        """Checks the rules (first check, R3) and writes nothing."""
        ...

    def confirm(self, company_id: CompanyId, request: ConfirmRequest) -> Result[OrderConfirmation]:
        """The second check (R5) and the only write: one order per proposal id, idempotent."""
        ...

    def find_order(
        self, company_id: CompanyId, proposal_id: ProposalId
    ) -> Result[OrderConfirmation | None]:
        """The order stored under the proposal id, as `confirm` returns it, or None. Read-only."""
        ...

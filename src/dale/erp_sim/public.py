"""The only erp_sim surface (design §2, contract 3): DTOs and the facade protocol."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from dale.shared.errors import Result
from dale.shared.ids import CompanyId, CustomerId, ProductId
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


class ErpFacade(Protocol):
    def quote(self, company_id: CompanyId, request: QuoteRequest) -> Result[Quote]:
        """Checks the rules (first check, R3) and writes nothing."""
        ...

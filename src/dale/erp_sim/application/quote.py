"""`quote`: the first rule check (R3, design §6). It reads rule data and writes nothing."""

import logging
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.exc import DBAPIError

from dale.erp_sim.domain.rules import Customer, PricedLine, Zone, evaluate_order
from dale.erp_sim.public import Quote, QuoteLine, QuoteRequest
from dale.shared.clock import Clock
from dale.shared.errors import ErrorCode, Failure, Ok, Result
from dale.shared.ids import CompanyId, CustomerId, ProductId
from dale.shared.money import Money

logger = logging.getLogger(__name__)


class RuleData(Protocol):
    def customer(
        self, company_id: CompanyId, customer_id: CustomerId
    ) -> tuple[Customer, Zone] | None: ...

    def current_prices(
        self, company_id: CompanyId, product_ids: Sequence[ProductId], at: datetime
    ) -> dict[ProductId, Money | None]:
        """Active products only; None when no price is valid at `at`."""
        ...

    def product_names(
        self, company_id: CompanyId, product_ids: Sequence[ProductId]
    ) -> dict[ProductId, str]:
        """Active products only: catalog name, brand and size, as the customer sees them, without
        the blank parts. A product with no name to show is left out, so it is not found."""
        ...


def rules_unavailable(read: str, company_id: CompanyId, error: DBAPIError) -> Failure:
    """Fail closed (design §6). The log names the read, the company and the error type only."""
    logger.error("%s failed for company %s: %s", read, company_id, type(error).__name__)
    return Failure(ErrorCode.RULES_UNAVAILABLE)


def quote(
    company_id: CompanyId, request: QuoteRequest, data: RuleData, clock: Clock
) -> Result[Quote]:
    if not isinstance(request.customer_id, UUID):  # an id that does not parse names nobody
        return Failure(ErrorCode.CUSTOMER_NOT_FOUND)
    now = clock.now()  # one instant for prices and the delivery date
    ids = [x.product_id for x in request.lines if isinstance(x.product_id, UUID)]
    try:
        found = data.customer(company_id, request.customer_id)
        prices = data.current_prices(company_id, ids, now)
        names = data.product_names(company_id, ids)
    except DBAPIError as error:  # only a failed read; any other error is a bug and raises
        return rules_unavailable("quote", company_id, error)
    if found is None:
        return Failure(ErrorCode.CUSTOMER_NOT_FOUND)
    customer, zone = found
    lines = [  # an id that does not parse was not read, so it is not in the catalog
        PricedLine(x.product_id, x.quantity, x.product_id in prices, prices.get(x.product_id))
        for x in request.lines
    ]
    result = evaluate_order(customer, zone, lines, now)
    if isinstance(result, Failure):
        return result
    ev = result.value
    if any(q.product_id not in names for q in ev.lines):  # deactivated between the two reads
        return Failure(ErrorCode.PRODUCT_NOT_FOUND)
    quoted = tuple(
        QuoteLine(q.product_id, names[q.product_id], q.quantity, q.unit_price, q.line_total)
        for q in ev.lines
    )
    return Ok(Quote(request.customer_id, quoted, ev.total, ev.delivery_date, now))

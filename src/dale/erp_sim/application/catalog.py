"""Catalog reads (R1): search, current prices and the next delivery. They write nothing."""

import logging
from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from sqlalchemy.exc import DBAPIError

from dale.erp_sim.application.quote import RuleData, rules_unavailable
from dale.erp_sim.domain.catalog import CatalogProduct, rank
from dale.erp_sim.domain.rules import cutoff_for, delivery_date
from dale.erp_sim.public import Delivery, ProductMatch, ProductPrice, SessionCustomer
from dale.shared.clock import Clock
from dale.shared.errors import ErrorCode, Failure, Ok, Result
from dale.shared.ids import CompanyId, CustomerId, ProductId

logger = logging.getLogger(__name__)


class CustomerData(Protocol):
    def session_customer(self, company_slug: str, customer_code: str) -> SessionCustomer | None:
        """An active customer by its code, within the company with that slug."""
        ...


def find_customer(
    company_slug: str, customer_code: str, data: CustomerData
) -> Result[SessionCustomer]:
    """D2: an unknown company, an unknown code and an inactive customer are all not found."""
    try:
        found = data.session_customer(company_slug, customer_code)
    except DBAPIError as error:  # fail closed on a failed read only
        logger.error("find_customer failed: %s", type(error).__name__)
        return Failure(ErrorCode.RULES_UNAVAILABLE)
    return Failure(ErrorCode.CUSTOMER_NOT_FOUND) if found is None else Ok(found)


class CatalogData(Protocol):
    def active_products(self, company_id: CompanyId) -> list[CatalogProduct]: ...


def search_products(
    company_id: CompanyId, query: str, data: CatalogData
) -> Result[tuple[ProductMatch, ...]]:
    try:
        products = data.active_products(company_id)
    except DBAPIError as error:  # fail closed on a failed read only, as quote does
        return rules_unavailable("search_products", company_id, error)
    found = rank(query, products)
    return Ok(tuple(ProductMatch(p.id, p.sku, p.name, p.brand, p.presentation) for p in found))


def get_prices(
    company_id: CompanyId, product_ids: Sequence[ProductId], data: RuleData, clock: Clock
) -> Result[tuple[ProductPrice, ...]]:
    # request order, no repeats; an id that does not parse is unknown, so it is left out
    wanted = list(dict.fromkeys(i for i in product_ids if isinstance(i, UUID)))
    try:
        prices = data.current_prices(company_id, wanted, clock.now())
    except DBAPIError as error:
        return rules_unavailable("get_prices", company_id, error)
    return Ok(tuple(ProductPrice(i, p) for i in wanted if (p := prices.get(i)) is not None))


def check_delivery(
    company_id: CompanyId, customer_id: CustomerId, data: RuleData, clock: Clock
) -> Result[Delivery]:
    if not isinstance(customer_id, UUID):
        return Failure(ErrorCode.CUSTOMER_NOT_FOUND)
    now = clock.now()
    try:
        found = data.customer(company_id, customer_id)
    except DBAPIError as error:
        return rules_unavailable("check_delivery", company_id, error)
    if found is None or not found[0].active:
        return Failure(ErrorCode.CUSTOMER_NOT_FOUND)
    zone = found[1]
    day = delivery_date(zone, now)
    if day is None:
        return Failure(ErrorCode.NO_DELIVERY_SLOT)
    return Ok(Delivery(day, cutoff_for(zone, day), zone.minimum))

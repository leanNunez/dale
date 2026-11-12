"""The facade wiring: `erp_sim.public.ErpFacade` over a database. Only composition roots use it."""

from collections.abc import Sequence

import sqlalchemy as sa

from dale.erp_sim.application.catalog import check_delivery, get_prices, search_products
from dale.erp_sim.application.confirm import confirm
from dale.erp_sim.application.quote import quote
from dale.erp_sim.infrastructure.repositories import SqlOrderStore, SqlRuleData
from dale.erp_sim.public import (
    ConfirmRequest,
    Delivery,
    OrderConfirmation,
    ProductMatch,
    ProductPrice,
    Quote,
    QuoteRequest,
)
from dale.shared.clock import Clock
from dale.shared.errors import Result
from dale.shared.ids import CompanyId, CustomerId, IdGenerator, ProductId, Uuid4Generator


class SqlErpFacade:
    def __init__(self, engine: sa.Engine, clock: Clock, ids: IdGenerator | None = None) -> None:
        self._data, self._orders = SqlRuleData(engine), SqlOrderStore(engine)
        self._clock, self._ids = clock, ids or Uuid4Generator()

    def quote(self, company_id: CompanyId, request: QuoteRequest) -> Result[Quote]:
        return quote(company_id, request, self._data, self._clock)

    def search_products(
        self, company_id: CompanyId, query: str
    ) -> Result[tuple[ProductMatch, ...]]:
        return search_products(company_id, query, self._data)

    def get_prices(
        self, company_id: CompanyId, product_ids: Sequence[ProductId]
    ) -> Result[tuple[ProductPrice, ...]]:
        return get_prices(company_id, product_ids, self._data, self._clock)

    def check_delivery(self, company_id: CompanyId, customer_id: CustomerId) -> Result[Delivery]:
        return check_delivery(company_id, customer_id, self._data, self._clock)

    def confirm(self, company_id: CompanyId, request: ConfirmRequest) -> Result[OrderConfirmation]:
        return confirm(company_id, request, self._orders, self._clock, self._ids)

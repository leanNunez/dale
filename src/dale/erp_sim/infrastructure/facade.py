"""The facade wiring: `erp_sim.public.ErpFacade` over a database. Only composition roots use it."""

import sqlalchemy as sa

from dale.erp_sim.application.quote import quote
from dale.erp_sim.infrastructure.repositories import SqlRuleData
from dale.erp_sim.public import Quote, QuoteRequest
from dale.shared.clock import Clock
from dale.shared.errors import Result
from dale.shared.ids import CompanyId


class SqlErpFacade:
    def __init__(self, engine: sa.Engine, clock: Clock) -> None:
        self._data = SqlRuleData(engine)
        self._clock = clock

    def quote(self, company_id: CompanyId, request: QuoteRequest) -> Result[Quote]:
        return quote(company_id, request, self._data, self._clock)

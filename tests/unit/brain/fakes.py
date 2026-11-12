"""Fakes for the brain's ports and the helpers the tool tests share."""

import json
from collections.abc import Sequence
from datetime import date, datetime
from uuid import UUID

from dale.brain.application.tools import Tools
from dale.brain.domain.session import SessionContext
from dale.erp_sim.public import Delivery, ProductMatch, ProductPrice, Quote, QuoteLine, QuoteRequest
from dale.shared.errors import ErrorCode, Failure, Ok, Result, message_for
from dale.shared.ids import CompanyId, ConversationId, CustomerId, ProductId
from dale.shared.money import Money, money_sum

COMPANY, CUSTOMER = CompanyId(UUID(int=1)), CustomerId(UUID(int=2))
SESSION = SessionContext(COMPANY, CUSTOMER, ConversationId(UUID(int=3)))
COLA, COLA15, PACK, UNPRICED = (ProductId(UUID(int=n)) for n in (11, 12, 13, 14))
PRICES = {COLA: Money(245_000), COLA15: Money(185_000), PACK: Money(690_000)}
MATCHES = tuple(ProductMatch(p, "SKU", "Gaseosa cola", "Burbuja", "1 L") for p in PRICES)
DAY, NOW = date(2026, 11, 19), datetime.fromisoformat("2026-11-18T12:00:00+00:00")


class FakeErp:
    """Records every call; returns `failure` from every call when it is set."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, CompanyId]] = []
        self.failure: ErrorCode | None = None

    def _call(self, name: str, company_id: CompanyId) -> Failure | None:
        self.calls.append((name, company_id))
        return Failure(self.failure) if self.failure else None

    def search_products(
        self, company_id: CompanyId, query: str
    ) -> Result[tuple[ProductMatch, ...]]:
        return self._call("search_products", company_id) or Ok(MATCHES)

    def get_prices(
        self, company_id: CompanyId, product_ids: Sequence[ProductId]
    ) -> Result[tuple[ProductPrice, ...]]:
        found = tuple(ProductPrice(i, PRICES[i]) for i in product_ids if i in PRICES)
        return self._call("get_prices", company_id) or Ok(found)

    def check_delivery(self, company_id: CompanyId, customer_id: CustomerId) -> Result[Delivery]:
        assert customer_id == CUSTOMER
        return self._call("check_delivery", company_id) or Ok(Delivery(DAY, NOW, Money(3_000_000)))

    def quote(self, company_id: CompanyId, request: QuoteRequest) -> Result[Quote]:
        assert request.customer_id == CUSTOMER
        if failed := self._call("quote", company_id):
            return failed
        priced = [(x, PRICES[x.product_id]) for x in request.lines]
        lines = tuple(QuoteLine(x.product_id, x.quantity, u, u * x.quantity) for x, u in priced)
        return Ok(Quote(CUSTOMER, lines, money_sum(x.line_total for x in lines), DAY, NOW))


def tools(erp: FakeErp | None = None) -> Tools:
    return Tools(SESSION, erp or FakeErp())


def error_code(content: str) -> str:
    """The code of an error result, which must carry exactly the code and its catalog message."""
    body = json.loads(content)
    assert body == {"code": body["code"], "message": message_for(ErrorCode(body["code"]))}
    return str(body["code"])

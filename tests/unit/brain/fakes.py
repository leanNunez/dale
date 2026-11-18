"""Fakes for the brain's ports and the helpers the tool tests share."""

import json
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any
from uuid import UUID

from dale.brain.application.tools import Tools
from dale.brain.domain.handoff import HandoffReason
from dale.brain.domain.proposal import OrderProposal
from dale.brain.domain.session import SessionContext
from dale.erp_sim.public import Delivery, ProductMatch, ProductPrice, Quote, QuoteLine, QuoteRequest
from dale.shared.errors import ErrorCode, Failure, Ok, Result, message_for
from dale.shared.ids import CompanyId, ConversationId, CustomerId, ProductId, SequentialIdGenerator
from dale.shared.money import Money, money_sum

COMPANY, CUSTOMER = CompanyId(UUID(int=1)), CustomerId(UUID(int=2))
SESSION = SessionContext(COMPANY, CUSTOMER, ConversationId(UUID(int=3)))
COLA, COLA15, PACK, UNPRICED = (ProductId(UUID(int=n)) for n in (11, 12, 13, 14))
PRICES = {COLA: Money(245_000), COLA15: Money(185_000), PACK: Money(690_000)}
NAME = "Gaseosa cola Burbuja 1 L"  # what management's quote names each product
MATCHES = tuple(ProductMatch(p, "SKU", "Gaseosa cola", "Burbuja", "1 L") for p in PRICES)
DAY, NOW = date(2026, 11, 19), datetime.fromisoformat("2026-11-18T12:00:00+00:00")


class FakeErp:
    """Records every call; returns `failure` from `failing` (or every call) when it is set."""

    def __init__(self, *orders: Any) -> None:
        self.calls: list[tuple[str, CompanyId]] = []
        self.failure: ErrorCode | None = None
        self.failing, self.orders = "", {o.proposal_id: o for o in orders}

    def _call(self, name: str, company_id: CompanyId) -> Failure | None:
        self.calls.append((name, company_id))
        return Failure(self.failure) if self.failure and self.failing in ("", name) else None

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
        lines = tuple(
            QuoteLine(x.product_id, NAME, x.quantity, u, u * x.quantity) for x, u in priced
        )
        return Ok(Quote(CUSTOMER, lines, money_sum(x.line_total for x in lines), DAY, NOW))

    def find_order(self, company_id: CompanyId, proposal_id: Any) -> Result[Any]:
        return self._call("find_order", company_id) or Ok(self.orders.get(proposal_id))


class FakeProposals:
    """Returns `stored` (or what it was given) as the stored row, or raises `error` on locking
    and `withdraw_error` on a withdraw."""

    def __init__(self, stored: OrderProposal | None = None, error: Exception | None = None) -> None:
        self.saved: list[tuple[CompanyId, OrderProposal]] = []
        self.stored, self.error, self.marks = stored, error, list[tuple[Any, ...]]()
        self.earlier: OrderProposal | None = None
        self.withdrawn: list[tuple[CompanyId, Any]] = []
        self.withdraw_error: Exception | None = None

    @contextmanager
    def locked(self, company_id: CompanyId, conversation_id: object) -> Iterator[Any]:
        assert conversation_id == SESSION.conversation_id
        if self.error:
            raise self.error
        self.company = company_id
        yield self

    def prepared(self) -> OrderProposal | None:
        return self.earlier

    def save_prepared(self, proposal: OrderProposal) -> OrderProposal:
        self.saved.append((self.company, proposal))
        return self.stored or proposal

    def mark_confirmed(self, *mark: Any, **was: Any) -> None:
        self.marks.append((*mark, *was.values()))

    def withdraw(self, proposal_id: Any) -> None:
        if self.withdraw_error:
            raise self.withdraw_error
        self.withdrawn.append((self.company, proposal_id))

    def get(self, company_id: CompanyId, proposal_id: object) -> OrderProposal | None:
        raise AssertionError("no tool reads a proposal by id")


class FakeHandoffs:
    """Records each written request, or raises `error` and writes nothing."""

    def __init__(self, error: Exception | None = None) -> None:
        self.written: list[tuple[SessionContext, HandoffReason, str | None]] = []
        self.error = error

    def request_handoff(
        self, session: SessionContext, reason: HandoffReason, note: str | None
    ) -> None:
        if self.error:
            raise self.error
        self.written.append((session, reason, note))


def tools(
    erp: FakeErp | None = None,
    proposals: FakeProposals | None = None,
    handoffs: FakeHandoffs | None = None,
) -> Tools:
    stores = (proposals or FakeProposals(), SequentialIdGenerator(), handoffs or FakeHandoffs())
    return Tools(SESSION, erp or FakeErp(), *stores)


def prepare(*lines: tuple[object, object], **extra: object) -> dict[str, object]:
    return {"lines": [{"product_id": str(p), "quantity": q} | extra for p, q in lines]}


def error_code(content: str) -> str:
    """The code of an error result, which must carry exactly the code and its catalog message."""
    body = json.loads(content)
    assert body == {"code": body["code"], "message": message_for(ErrorCode(body["code"]))}
    return str(body["code"])


class FakeConversations:
    """Logs each open in `log`, or raises `error` and opens nothing."""

    def __init__(self, log: list[str], error: Exception | None = None) -> None:
        self.log, self.error = log, error

    def open(self, session: SessionContext) -> None:
        assert session == SESSION
        if self.error:
            raise self.error
        self.log.append("open")

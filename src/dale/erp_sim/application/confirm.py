"""`confirm`: the second rule check (R5, D4) and the only write, idempotent per proposal id (§6).

One transaction: look up the proposal's order; if there is none, re-check the rules on data read
inside the transaction, insert with ON CONFLICT DO NOTHING, and re-read. The answer always comes
from the stored order, so a replay, a retry after a crash and a lost race all return the same one.
`find_order` reads that same answer and writes nothing: management is the source of truth (B68).
"""

from collections import Counter
from collections.abc import Iterable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.exc import DBAPIError

from dale.erp_sim.application.quote import RuleData, rules_unavailable
from dale.erp_sim.domain.rules import Evaluation, PricedLine, QuotedLine, evaluate_order
from dale.erp_sim.public import ConfirmLine, ConfirmRequest, OrderConfirmation, QuoteLine
from dale.shared.clock import Clock
from dale.shared.errors import ErrorCode, Failure, Ok, Result
from dale.shared.ids import CompanyId, CustomerId, IdGenerator, OrderId, ProposalId
from dale.shared.money import Money, pesos

WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


@dataclass(frozen=True, slots=True)
class Order:
    id: OrderId
    proposal_id: ProposalId
    customer_id: CustomerId
    lines: tuple[QuotedLine, ...]
    total: Money
    delivery_date: date
    received_at: datetime


class OrderData(RuleData, Protocol):
    def find_order(self, company_id: CompanyId, proposal_id: ProposalId) -> Order | None: ...

    def insert_order(self, company_id: CompanyId, order: Order) -> None:
        """Writes nothing when the proposal already has an order (ON CONFLICT DO NOTHING)."""
        ...


class OrderStore(Protocol):
    def transaction(self) -> AbstractContextManager[OrderData]:
        """READ COMMITTED; every read and the write share it. It commits on a normal exit."""
        ...


def confirm(
    company_id: CompanyId,
    request: ConfirmRequest,
    store: OrderStore,
    clock: Clock,
    ids: IdGenerator,
) -> Result[OrderConfirmation]:
    if not isinstance(request.proposal_id, UUID):
        return Failure(ErrorCode.PROPOSAL_NOT_FOUND)
    if not isinstance(request.customer_id, UUID):
        return Failure(ErrorCode.CUSTOMER_NOT_FOUND)
    now = clock.now()  # one instant for prices, the delivery date and received_at
    try:
        with store.transaction() as data:
            stored = data.find_order(company_id, request.proposal_id)
            if stored is None:
                checked = _second_check(company_id, request, data, now)
                if isinstance(checked, Failure):
                    return checked  # nothing was written
                ev, key = checked.value, (OrderId(ids.new_id()), request.proposal_id)
                order = Order(*key, request.customer_id, ev.lines, ev.total, ev.delivery_date, now)
                data.insert_order(company_id, order)
                stored = data.find_order(company_id, request.proposal_id)  # ours or the winner's
            if stored is None:  # committed by us or by the race winner: never missing
                raise RuntimeError("the proposal's order is missing inside its transaction")
    except DBAPIError as error:  # the database failed: all rolls back. A statement bug raises
        return rules_unavailable("confirm", company_id, error)
    if not _same(stored, request):  # B45: the same key with another payload confirms nothing
        return Failure(ErrorCode.PROPOSAL_NOT_PENDING)
    return Ok(_confirmation(stored))


def find_order(
    company_id: CompanyId, proposal_id: ProposalId, store: OrderStore
) -> Result[OrderConfirmation | None]:
    """The order stored under `proposal_id`, built as `confirm` builds it, or None."""
    if not isinstance(proposal_id, UUID):
        return Ok(None)  # an id that does not parse has no order
    try:
        with store.transaction() as data:
            stored = data.find_order(company_id, proposal_id)
    except DBAPIError as error:  # unreadable: fail closed. A statement bug raises
        return rules_unavailable("find_order", company_id, error)
    return Ok(None if stored is None else _confirmation(stored))


def _second_check(
    company_id: CompanyId, request: ConfirmRequest, data: RuleData, now: datetime
) -> Result[Evaluation]:
    """The rules on data read inside the caller's transaction (B40), then D4 against the shown."""
    ids = [x.product_id for x in request.lines if isinstance(x.product_id, UUID)]
    found = data.customer(company_id, request.customer_id)
    prices = data.current_prices(company_id, ids, now)
    if found is None:
        return Failure(ErrorCode.CUSTOMER_NOT_FOUND)
    lines = [
        PricedLine(x.product_id, x.quantity, x.product_id in prices, prices.get(x.product_id))
        for x in request.lines
    ]
    moved = any(prices.get(x.product_id) != x.unit_price for x in request.lines)  # shown vs now
    result = evaluate_order(*found, lines, now)
    if isinstance(result, Failure):  # a moved price is reported before the minimum it may cause,
        below = result.code is ErrorCode.BELOW_MINIMUM_AMOUNT  # but price_not_available stays
        return Failure(ErrorCode.PRICE_CHANGED) if below and moved else result
    ev = result.value
    if moved or ev.total != request.total:
        return Failure(ErrorCode.PRICE_CHANGED)
    if ev.delivery_date != request.delivery_date:
        return Failure(ErrorCode.DELIVERY_DATE_CHANGED)
    return result


def _same(order: Order, request: ConfirmRequest) -> bool:
    """A replay repeats every field; lines compare as a multiset (stored lines keep no order)."""

    def key(o: Order | ConfirmRequest) -> tuple[object, ...]:
        lines: Iterable[QuotedLine | ConfirmLine] = o.lines
        rows = Counter((x.product_id, x.quantity, x.unit_price) for x in lines)
        return o.customer_id, o.delivery_date, o.total, rows

    return key(order) == key(request)


def _confirmation(order: Order) -> OrderConfirmation:
    """Success text from the stored order only (S5.4, B31): it states what was stored, no more."""
    day, total = order.delivery_date, order.total
    message = (
        f"Listo, tu pedido quedó confirmado por {pesos(total)}."
        f" Entrega programada: {WEEKDAYS[day.weekday()]} {day:%d/%m/%Y}."
    )
    lines = tuple(
        QuoteLine(x.product_id, x.quantity, x.unit_price, x.line_total) for x in order.lines
    )
    head = (order.id, order.proposal_id, order.customer_id)
    return OrderConfirmation(*head, lines, total, day, order.received_at, message)

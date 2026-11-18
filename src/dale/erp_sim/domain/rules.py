"""Order rules (design §6, R2): one pure function serves both checks. No I/O, no clock reads."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from dale.shared.errors import BelowMinimum, ErrorCode, Failure, Ok, Result
from dale.shared.ids import CustomerId, ProductId
from dale.shared.money import Money, money_sum
from dale.shared.quantity import MAX_LINE_QUANTITY, MIN_LINE_QUANTITY


@dataclass(frozen=True, slots=True)
class Zone:
    weekdays: frozenset[int]  # ISO weekdays, 1 = Monday (as the erp.zone CHECK stores them)
    cutoff: time  # company-local time on the day before delivery
    minimum: Money
    timezone: ZoneInfo  # the company's


@dataclass(frozen=True, slots=True)
class Customer:
    id: CustomerId
    active: bool


@dataclass(frozen=True, slots=True)
class PricedLine:
    """A requested line and what the catalog holds now for its product."""

    product_id: ProductId
    quantity: int
    in_catalog: bool  # the product exists in this company and is active
    unit_price: Money | None  # None: no price is valid yet


@dataclass(frozen=True, slots=True)
class QuotedLine:
    product_id: ProductId
    quantity: int
    unit_price: Money
    line_total: Money


@dataclass(frozen=True, slots=True)
class Evaluation:
    lines: tuple[QuotedLine, ...]
    total: Money
    delivery_date: date


def cutoff_for(zone: Zone, day: date) -> datetime:
    """The instant from which an order no longer makes delivery on `day`."""
    return datetime.combine(day - timedelta(days=1), zone.cutoff, zone.timezone)


def delivery_date(zone: Zone, now: datetime) -> date | None:
    """The earliest zone weekday after today (company-local) whose cutoff is still ahead."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    today = now.astimezone(zone.timezone).date()
    for offset in range(1, 9):  # a missed first slot comes back within 7 more days
        day = today + timedelta(days=offset)
        if day.isoweekday() in zone.weekdays and now < cutoff_for(zone, day):
            return day
    return None


def evaluate_order(
    customer: Customer, zone: Zone, lines: Sequence[PricedLine], now: datetime
) -> Result[Evaluation]:
    """Expected rule outcomes come back as Failure(code); prices are the server's only."""
    if not customer.active:
        return Failure(ErrorCode.CUSTOMER_NOT_FOUND)
    if not lines or any(
        type(x.quantity) is not int or not MIN_LINE_QUANTITY <= x.quantity <= MAX_LINE_QUANTITY
        for x in lines
    ):
        return Failure(ErrorCode.INVALID_QUANTITY)
    if not all(x.in_catalog for x in lines):
        return Failure(ErrorCode.PRODUCT_NOT_FOUND)
    quoted = []
    for x in lines:
        if x.unit_price is None:
            return Failure(ErrorCode.PRICE_NOT_AVAILABLE)
        quoted.append(QuotedLine(x.product_id, x.quantity, x.unit_price, x.unit_price * x.quantity))
    total = money_sum(q.line_total for q in quoted)
    if total < zone.minimum:
        return BelowMinimum(ErrorCode.BELOW_MINIMUM_AMOUNT, total, zone.minimum)
    day = delivery_date(zone, now)
    if day is None:
        return Failure(ErrorCode.NO_DELIVERY_SLOT)
    return Ok(Evaluation(tuple(quoted), total, day))

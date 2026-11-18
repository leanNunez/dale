"""The pure order rules (design §6, R2): minimum in pesos, quantities, delivery cutoff."""

from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dale.erp_sim.domain.rules import Customer, PricedLine, Zone, delivery_date, evaluate_order
from dale.shared.errors import BelowMinimum, ErrorCode, Failure, Ok
from dale.shared.ids import CustomerId, ProductId
from dale.shared.money import Money

BA = ZoneInfo("America/Argentina/Buenos_Aires")
TUESDAYS = Zone(frozenset({2}), time(18), Money(3_000_000), BA)  # Monday 18:00 cutoff, $30,000
CUSTOMER = Customer(CustomerId(UUID(int=1)), active=True)
P = ProductId(UUID(int=2))


def ba(day: int, hour: int, minute: int = 0) -> datetime:
    """November 2026 in Buenos Aires, as the UTC instant the clock returns."""
    return datetime(2026, 11, day, hour, minute, tzinfo=BA).astimezone(UTC)


def line(quantity: int = 1, cents: int | None = 3_000_000, found: bool = True) -> PricedLine:
    return PricedLine(P, quantity, found, None if cents is None else Money(cents))


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (ba(16, 17, 59), date(2026, 11, 17)),  # S2.2 Monday 17:59: that Tuesday
        (ba(16, 18, 0), date(2026, 11, 24)),  # cutoff instant itself misses the slot
        (ba(16, 18, 1), date(2026, 11, 24)),  # S2.3 Monday 18:01: the next Tuesday
        (ba(17, 10), date(2026, 11, 24)),  # delivery day itself: never today
        (ba(12, 9), date(2026, 11, 17)),  # Thursday: the coming Tuesday
    ],
)
def test_delivery_date_follows_the_cutoff_on_the_day_before(now: datetime, expected: date) -> None:
    result = evaluate_order(CUSTOMER, TUESDAYS, [line()], now)
    assert isinstance(result, Ok)
    assert result.value.delivery_date == expected


def test_today_is_the_company_date_and_a_naive_now_is_refused() -> None:
    late = Zone(frozenset({2}), time(23, 30), Money(0), BA)
    assert ba(16, 22) == datetime(2026, 11, 17, 1, tzinfo=UTC)  # Tuesday already in UTC
    assert delivery_date(late, ba(16, 22)) == date(2026, 11, 17)
    with pytest.raises(ValueError):  # a naive instant would silently use the host's timezone
        delivery_date(late, datetime(2026, 11, 16, 17))


@pytest.mark.parametrize(
    ("lines", "code"),
    [
        ([line(0)], ErrorCode.INVALID_QUANTITY),
        ([line(1000)], ErrorCode.INVALID_QUANTITY),
        ([line(True)], ErrorCode.INVALID_QUANTITY),
        ([], ErrorCode.INVALID_QUANTITY),
        ([line(found=False)], ErrorCode.PRODUCT_NOT_FOUND),
        ([line(), line(cents=None)], ErrorCode.PRICE_NOT_AVAILABLE),
    ],
)
def test_rule_failures_return_their_catalog_code(lines: list[PricedLine], code: ErrorCode) -> None:
    assert evaluate_order(CUSTOMER, TUESDAYS, lines, ba(12, 9)) == Failure(code)


@pytest.mark.parametrize(
    "lines", [[line(cents=2_999_999)], [line(cents=10**6), line(cents=1_999_999)]]
)
def test_a_total_below_the_minimum_comes_back_with_the_total_and_the_minimum(
    lines: list[PricedLine],
) -> None:
    """S2.1/S2.4: one cent short. B96: management's own figures, so no caller computes one."""
    result = evaluate_order(CUSTOMER, TUESDAYS, lines, ba(12, 9))
    assert result == BelowMinimum(
        ErrorCode.BELOW_MINIMUM_AMOUNT, Money(2_999_999), Money(3 * 10**6)
    )
    assert isinstance(result, BelowMinimum) and result.shortfall == Money(1)
    assert result.message == Failure(ErrorCode.BELOW_MINIMUM_AMOUNT).message


@pytest.mark.parametrize(
    ("code", "total"), [(ErrorCode.PRICE_CHANGED, 1), (ErrorCode.BELOW_MINIMUM_AMOUNT, 3 * 10**6)]
)
def test_below_minimum_carries_its_own_code_and_a_total_below_the_minimum(
    code: ErrorCode, total: int
) -> None:
    with pytest.raises(ValueError, match="below its minimum"):
        BelowMinimum(code, Money(total), Money(3 * 10**6))


def test_exactly_the_minimum_passes_and_totals_come_from_server_prices() -> None:
    result = evaluate_order(CUSTOMER, TUESDAYS, [line(999, 1000), line(1, 2_001_000)], ba(12, 9))
    assert isinstance(result, Ok)
    assert result.value.total == Money(3_000_000)
    assert [q.line_total for q in result.value.lines] == [Money(999_000), Money(2_001_000)]


def test_inactive_customer_and_empty_schedule_fail_without_raising() -> None:
    inactive = Customer(CUSTOMER.id, active=False)
    assert evaluate_order(inactive, TUESDAYS, [line()], ba(12, 9)) == Failure(
        ErrorCode.CUSTOMER_NOT_FOUND
    )
    never = Zone(frozenset(), time(18), Money(0), BA)
    assert evaluate_order(CUSTOMER, never, [line()], ba(12, 9)) == Failure(
        ErrorCode.NO_DELIVERY_SLOT
    )


@given(
    weekdays=st.frozensets(st.integers(1, 7), min_size=1),
    cutoff=st.times(),
    local=st.datetimes(datetime(2026, 1, 1), datetime(2030, 12, 31)),
)
def test_cutoff_property(weekdays: frozenset[int], cutoff: time, local: datetime) -> None:
    """Design §12: strictly after today, on a zone weekday, earliest; `now == cutoff` misses."""
    zone = Zone(weekdays, cutoff, Money(0), BA)
    now = local.replace(tzinfo=BA)
    today, tomorrow = local.date(), local.date() + timedelta(days=1)
    day = delivery_date(zone, now.astimezone(UTC))
    assert day is not None and day > today and day.isoweekday() in weekdays
    for earlier in (today + timedelta(days=n) for n in range(1, (day - today).days)):
        cut = datetime.combine(earlier - timedelta(days=1), cutoff, BA)
        assert earlier.isoweekday() not in weekdays or now >= cut
    at_cutoff = datetime.combine(today, cutoff, BA)
    assert delivery_date(zone, at_cutoff) != tomorrow
    if tomorrow.isoweekday() in weekdays and cutoff != time.min:
        assert delivery_date(zone, at_cutoff - timedelta(microseconds=1)) == tomorrow

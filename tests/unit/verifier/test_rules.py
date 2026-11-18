"""The verifier's own delivery recheck (design §9) agrees with management's rule everywhere."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from hypothesis import given
from hypothesis import strategies as st

from dale.erp_sim.domain.rules import Zone, delivery_date
from dale.shared.money import Money
from dale.verifier.domain.rules import ZoneRule, delivery_ok

BA = ZoneInfo("America/Argentina/Buenos_Aires")
TUESDAYS = ZoneRule(frozenset({2}), time(18), 0, BA)  # cutoff Monday 18:00


def test_the_cutoff_instant_already_misses_the_slot() -> None:
    monday = datetime(2026, 11, 16, 17, 59, tzinfo=BA)
    assert delivery_ok(TUESDAYS, monday, date(2026, 11, 17))
    late = monday + timedelta(minutes=1)
    assert not delivery_ok(TUESDAYS, late, date(2026, 11, 17))
    assert delivery_ok(TUESDAYS, late, date(2026, 11, 24))
    assert not delivery_ok(TUESDAYS, monday, date(2026, 11, 24))  # not the earliest open day
    assert not delivery_ok(TUESDAYS, monday, date(2026, 11, 16))  # not after today


@given(
    weekdays=st.frozensets(st.integers(1, 7), min_size=1),
    cutoff=st.times(),
    at=st.datetimes(datetime(2026, 1, 1), datetime(2027, 12, 31), timezones=st.just(UTC)),
    offset=st.integers(-1, 10),
)
def test_it_accepts_exactly_the_day_management_would_compute(
    weekdays: frozenset[int], cutoff: time, at: datetime, offset: int
) -> None:
    """Two independent implementations of one rule: a bug in either one shows up here."""
    expected = delivery_date(Zone(weekdays, cutoff, Money(0), BA), at)
    day = at.astimezone(BA).date() + timedelta(days=offset)
    assert delivery_ok(ZoneRule(weekdays, cutoff, 0, BA), at, day) == (day == expected)

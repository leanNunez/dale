"""The verifier's own recheck of the order rules (design §9). It is written apart from
management's rules on purpose: a verifier that shares the writer's code shares its bugs."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True, slots=True)
class ZoneRule:
    weekdays: frozenset[int]  # ISO weekdays, 1 = Monday
    cutoff: time  # company-local, on the day before delivery
    minimum_cents: int
    timezone: ZoneInfo  # the company's


def closes_at(zone: ZoneRule, day: date) -> datetime:
    """From this instant on, an order no longer makes delivery on `day`."""
    return datetime.combine(day - timedelta(days=1), zone.cutoff, tzinfo=zone.timezone)


def delivery_ok(zone: ZoneRule, received_at: datetime, day: date) -> bool:
    """True only if `day` is the first zone weekday after the local date of `received_at`
    whose cutoff was still ahead when the order was received."""
    today = received_at.astimezone(zone.timezone).date()
    if not today < day <= today + timedelta(days=8):  # a missed slot returns within a week
        return False
    ahead = (today + timedelta(days=n) for n in range(1, (day - today).days + 1))
    still_open = [
        d for d in ahead if d.isoweekday() in zone.weekdays and received_at < closes_at(zone, d)
    ]
    return still_open[:1] == [day]

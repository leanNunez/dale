"""The operator's view (O6 S6.1, design §7, §12): one line per field, read as `dale_app` from
`control`, `spend_*`, `host_status`, `transcript*` and `counter`. Each field is read on its own
connection, so a field that cannot be read shows `unknown` while the others still print, and
nothing unread is ever shown as a healthy value. No heartbeat, or one older than two minutes,
reads "host not reporting", and so does one more than 5 s in the future (a clock skew); the
host counts are marked stale with either (design §6). The cap is the one this command reads
from its own settings, and says so.

Only states, reasons, times, counts, money and counter kinds are printed: never customer text,
a session hash, a counter subject (a keyed IP hash), a key or a value from the environment."""

from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import sqlalchemy as sa

from dale.apps.demo import tables as t
from dale.apps.demo.control import ControlState, state_of
from dale.apps.demo.ledger import DAY_ZONE, spend_day_of
from dale.shared.clock import Clock

STALE = timedelta(minutes=2)
SKEW = timedelta(seconds=5)  # a heartbeat further ahead than this is a clock skew
type Field = tuple[str, str | None]  # None: the field could not be read
type Reader = Callable[[sa.Connection], str]


def describe(state: ControlState) -> str:
    since = _at(state.changed_at)
    return f"paused ({state.reason}) since {since}" if state.paused else f"running since {since}"


def usd(micros: int) -> str:
    return f"{Decimal(micros).scaleb(-6):.6f} USD"


def report(engine: sa.Engine, clock: Clock, cap: int | None) -> list[Field]:
    now = clock.now()
    today = spend_day_of(now)
    c, r, h, e = t.control.c, t.spend_request.c, t.host_status.c, t.transcript_event.c

    def spent(since: date, of: str = "") -> Reader:
        total = sa.select(sa.func.coalesce(sa.func.sum(t.spend_day.c.committed_micros), 0))
        query = total.where(t.spend_day.c.day.between(since, today))
        return lambda conn: usd(conn.execute(query).scalar_one()) + of

    def reservations(conn: sa.Connection) -> str:
        parts = []
        for name, held in (
            ("open", r.settled_at.is_(None)),
            ("unknown usage", r.outcome == "unknown"),
        ):
            money = sa.func.coalesce(sa.func.sum(r.reserved_micros).filter(held), 0)
            query = sa.select(sa.func.count().filter(held), money).where(r.day == today)
            count, micros = conn.execute(query).one()
            parts.append(f"{name} {count} ({usd(micros)})")
        return ", ".join(parts)

    def last_reset(conn: sa.Connection) -> str:
        result, at, asked = conn.execute(
            sa.select(c.last_reset_result, c.last_reset_at, c.reset_requested_at)
        ).one()
        said = f"{result} at {_at(at)}" if result else "none yet"
        return said + (f", one requested at {_at(asked)}" if asked else "")

    def heartbeat(conn: sa.Connection) -> str:
        if (beat := conn.scalar(sa.select(h.updated_at))) is None:
            return "none (host not reporting)"
        age = round((now - beat).total_seconds())
        if beat - now > SKEW:
            return f"{-age} s in the future (clock skew: host not reporting)"
        late = " (host not reporting)" if now - beat > STALE else ""
        return f"{max(age, 0)} s ago{late}"  # a few seconds ahead: written while this read

    def host(conn: sa.Connection) -> str:
        query = sa.select(*(h[name] for name in t.HOST_COUNTS), h.updated_at)
        if (got := conn.execute(query).one_or_none()) is None:
            return "not reported"
        *counts, beat = got
        said = "live {}, in flight {}, transcript failures {}, reset failures {}".format(*counts)
        fresh = -SKEW <= now - beat <= STALE
        return said if fresh else f"{said} (stale: as of the heartbeat at {_at(beat)})"

    def count(*where: sa.ColumnElement[bool]) -> Reader:
        return lambda conn: str(conn.scalar(sa.select(sa.func.count()).where(*where)))

    def kinds(conn: sa.Connection) -> str:
        k = t.counter.c
        query = sa.select(k.kind, sa.func.sum(k.count)).where(k.day == today).group_by(k.kind)
        return (
            ", ".join(f"{kind} {n}" for kind, n in conn.execute(query.order_by(k.kind))) or "none"
        )

    midnight = datetime.combine(today, time(), DAY_ZONE)
    readers: dict[str, Reader] = {
        "control": lambda conn: describe(state_of(conn.execute(_CONTROL).one_or_none())),
        "spend today": spent(today, "" if cap is None else f" of {usd(cap)}"),
        "spend this month": spent(today.replace(day=1)),
        "reservations today": reservations,
        "last reset": last_reset,
        "heartbeat": heartbeat,
        "host": host,
        "conversations today": count(t.transcript.c.started_at >= midnight),
        "errors in the last 24 h": count(e.kind == "error", e.at >= now - timedelta(days=1)),
        "counters today": kinds,
    }
    fields = [(name, _read(engine, read)) for name, read in readers.items()]
    own = ("daily cap (this command's settings)", None if cap is None else usd(cap))
    return [fields[0], own, *fields[1:]]


_CONTROL = sa.select(t.control.c.paused, t.control.c.reason, t.control.c.changed_at)


def _read(engine: sa.Engine, read: Reader) -> str | None:
    try:
        with engine.connect() as conn:
            return read(conn)
    except Exception:  # unknown, never a default: the operator sees what could not be read
        return None


def _at(instant: datetime) -> str:
    return instant.isoformat(timespec="seconds")

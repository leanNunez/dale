"""The spend ledger as the attempt gate (O4 S4.1-S4.7, DD38, log D15, D29) on real Postgres with
a frozen clock: every attempt, retries included, reserves its worst case first and is refused
past the cap; settling replaces the reservation with the cost; every failure refuses."""

import threading
import time
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine, create_engine

from dale.apps.demo.ledger import (
    SqlSpendLedger,
    cost_micros,
    reference_request,
    reserve_micros,
    spend_day_of,
)
from dale.apps.demo.prices import PRICES
from dale.apps.demo.tables import spend_day, spend_request
from dale.brain.application.model_port import (
    MODEL_SETTINGS,
    AttemptTicket,
    ModelUnavailableError,
    Usage,
)
from dale.brain.infrastructure.anthropic_model import AnthropicModel
from tests.conftest import TEST_DB, admin_url, role_url
from tests.unit.brain.test_anthropic_retry import REPLY, FakeClient, status
from tests.unit.brain.test_anthropic_retry import Clock as Monotonic

pytestmark = pytest.mark.integration
MIDNIGHT = datetime(2026, 11, 27, 3, 0, tzinfo=UTC)  # 00:00 of 2026-11-27 in Buenos Aires
DAY, EVE = date(2026, 11, 27), date(2026, 11, 26)
SETTINGS, REQUEST = MODEL_SETTINGS, reference_request("El Hornero")
ONE = reserve_micros(REQUEST, SETTINGS.max_tokens, PRICES[SETTINGS.model])
USED = Usage(3_000, 200, 0, 9_000)
COST = cost_micros(USED, PRICES[SETTINGS.model])


class Frozen:
    def __init__(self, at: datetime = MIDNIGHT + timedelta(hours=12)) -> None:
        self.at = at

    def now(self) -> datetime:
        return self.at


@pytest.fixture
def db(engines: dict[str, Engine]) -> Iterator[Engine]:
    def clear() -> None:  # dale_app may not delete spend rows; the owner may
        with engines["dale_owner"].begin() as conn:
            conn.execute(sa.delete(spend_request))
            conn.execute(sa.delete(spend_day))

    clear()
    yield engines["dale_app"]
    clear()


def gate(engine: Engine, cap: int, clock: Frozen | None = None) -> SqlSpendLedger:
    return SqlSpendLedger(engine, cap, clock or Frozen())


def committed(engine: Engine, day: date = DAY) -> int | None:
    with engine.connect() as conn:
        return conn.scalar(sa.select(spend_day.c.committed_micros).where(spend_day.c.day == day))


def rows(engine: Engine) -> list[Any]:
    with engine.connect() as conn:
        return list(conn.execute(sa.select(spend_request).order_by(spend_request.c.created_at)))


def model(ledger: SqlSpendLedger, *outcomes: Any) -> tuple[AnthropicModel, FakeClient]:
    client = FakeClient(Monotonic(), *outcomes)
    return AnthropicModel(client, gate=ledger, sleep=lambda s: None), client  # type: ignore[arg-type]


def test_under_the_cap_an_attempt_is_sent_and_settled_at_its_cost(db: Engine) -> None:  # S4.1
    live, client = model(gate(db, 500_000), REPLY)
    response = live.complete(REQUEST)
    cost = cost_micros(response.usage, PRICES[SETTINGS.model])
    assert (client.sent, committed(db)) == (1, cost)
    (row,) = rows(db)
    assert (row.reserved_micros, row.cost_micros, row.outcome) == (ONE, cost, "settled")
    assert (row.input_tokens, row.output_tokens) == (
        response.usage.input_tokens,
        response.usage.output_tokens,
    )
    assert row.day == DAY and row.settled_at is not None


def test_past_the_cap_nothing_is_sent(db: Engine) -> None:  # S4.2
    live, client = model(gate(db, ONE - 1), REPLY)
    with pytest.raises(ModelUnavailableError):
        live.complete(REQUEST)
    assert (client.sent, committed(db), rows(db)) == (0, None, [])


def test_every_retry_is_checked_against_the_cap(db: Engine) -> None:
    live, client = model(gate(db, ONE + ONE // 2), status(529), REPLY)  # room for one attempt
    with pytest.raises(ModelUnavailableError):
        live.complete(REQUEST)
    assert client.sent == 1  # the retry was refused: the failed attempt kept its worst case
    assert committed(db) == ONE
    assert [r.outcome for r in rows(db)] == ["unknown"]


def test_a_restarted_host_sees_the_committed_spend(db: Engine) -> None:  # S4.3
    first = gate(db, ONE + ONE // 2)
    ticket = first.admit(SETTINGS, REQUEST)
    assert ticket is not None
    first.settle(ticket, None)
    restarted = create_engine(role_url("dale_app"))
    try:
        again = gate(restarted, ONE + ONE // 2)
        assert again.admit(SETTINGS, REQUEST) is None
        assert not again.has_room(SETTINGS, REQUEST)
    finally:
        restarted.dispose()


def _waiting_on_a_lock(count: int) -> None:
    admin = create_engine(admin_url().set(database=TEST_DB))
    query = sa.text(
        "SELECT count(*) FROM pg_stat_activity"
        " WHERE usename = 'dale_app' AND wait_event_type = 'Lock'"
    )
    try:
        for _ in range(200):
            with admin.connect() as conn:
                if conn.scalar(query) == count:
                    return
            time.sleep(0.025)
        raise AssertionError(f"{count} attempts never waited on the ledger row together")
    finally:
        admin.dispose()


@pytest.mark.parametrize("day_exists", [True, False])
def test_two_attempts_at_once_with_room_for_one_admit_exactly_one(  # S4.4
    db: Engine, engines: dict[str, Engine], day_exists: bool
) -> None:
    ledger, admitted = gate(db, ONE + ONE // 2), list[AttemptTicket | None]()
    if day_exists:
        with engines["dale_owner"].begin() as conn:
            conn.execute(sa.insert(spend_day).values(day=DAY, committed_micros=0))
    with engines["dale_owner"].connect() as holder:  # holds the row, or the new row's key
        if day_exists:
            holder.execute(sa.select(spend_day).with_for_update())
        else:
            holder.execute(sa.insert(spend_day).values(day=DAY, committed_micros=0))
        threads = [
            threading.Thread(target=lambda: admitted.append(ledger.admit(SETTINGS, REQUEST)))
            for _ in range(2)
        ]
        for thread in threads:
            thread.start()
        _waiting_on_a_lock(2)  # both are inside their reservation, neither has decided
        holder.rollback()  # the new row never existed: both race to create it
    for thread in threads:
        thread.join(10)
    assert sum(ticket is not None for ticket in admitted) == 1
    assert (committed(db), len(rows(db))) == (ONE, 1)


def test_an_unreadable_or_unwritable_ledger_refuses(db: Engine, engines: dict[str, Engine]) -> None:
    unreadable = gate(engines["dale_verifier"], 500_000)  # no USAGE on demo (S4.5)
    assert unreadable.admit(SETTINGS, REQUEST) is None
    assert not unreadable.has_room(SETTINGS, REQUEST)
    live, client = model(unreadable, REPLY)
    with pytest.raises(ModelUnavailableError):
        live.complete(REQUEST)
    assert client.sent == 0
    options = {"options": "-c default_transaction_read_only=on"}
    read_only = create_engine(role_url("dale_app"), connect_args=options)
    try:
        assert gate(read_only, 500_000).admit(SETTINGS, REQUEST) is None
    finally:
        read_only.dispose()
    assert (committed(db), rows(db)) == (None, [])


def test_unknown_usage_is_charged_at_the_reservation(db: Engine) -> None:  # S4.6
    ledger = gate(db, 500_000)
    ticket = ledger.admit(SETTINGS, REQUEST)
    assert ticket is not None
    ledger.settle(ticket, None)
    (row,) = rows(db)
    assert (committed(db), row.cost_micros, row.outcome, row.input_tokens) == (
        ONE, ONE, "unknown", None,
    )  # fmt: skip


def test_a_new_day_starts_at_buenos_aires_midnight(db: Engine) -> None:  # S4.7
    clock = Frozen(MIDNIGHT - timedelta(seconds=1))
    ledger = gate(db, ONE + ONE // 2, clock)
    assert spend_day_of(clock.now()) == EVE
    late = ledger.admit(SETTINGS, REQUEST)
    assert late is not None and ledger.admit(SETTINGS, REQUEST) is None  # yesterday is full
    clock.at = MIDNIGHT
    assert ledger.has_room(SETTINGS, REQUEST)
    ledger.settle(late, USED)  # settled after midnight: charged to the day it was reserved on
    assert (committed(db, EVE), committed(db, DAY)) == (COST, None)
    assert ledger.admit(SETTINGS, REQUEST) is not None
    assert committed(db, DAY) == ONE


def test_a_crash_between_reserve_and_settle_keeps_the_reservation(db: Engine) -> None:
    assert gate(db, 500_000).admit(SETTINGS, REQUEST) is not None  # the host dies here
    (row,) = rows(db)
    assert (committed(db), row.cost_micros, row.outcome) == (ONE, None, "reserved")


def test_room_for_the_reference_request(db: Engine) -> None:
    ledger = gate(db, 2 * ONE)
    assert ledger.has_room(SETTINGS, REQUEST)  # an empty day
    assert ledger.admit(SETTINGS, REQUEST) is not None
    assert ledger.has_room(SETTINGS, REQUEST)  # exactly at the cap after the next one
    assert ledger.admit(SETTINGS, REQUEST) is not None
    assert not ledger.has_room(SETTINGS, REQUEST)


def test_an_attempt_never_sent_settles_at_zero_and_only_once(db: Engine) -> None:
    ledger = gate(db, 500_000)
    ticket = ledger.admit(SETTINGS, REQUEST)
    assert ticket is not None
    ledger.settle(ticket, Usage())
    ledger.settle(ticket, None)  # a second settle changes nothing
    assert (committed(db), rows(db)[0].cost_micros) == (0, 0)


def test_settle_never_raises(db: Engine, engines: dict[str, Engine]) -> None:  # log D29
    ticket = gate(db, 500_000).admit(SETTINGS, REQUEST)
    assert ticket is not None
    gate(engines["dale_verifier"], 500_000).settle(ticket, USED)  # its write fails
    gate(db, 500_000).settle(AttemptTicket("not ours"), USED)
    assert committed(db) == ONE  # the reservation stays: overcounted, never lost


def test_a_model_with_no_price_is_refused(db: Engine) -> None:
    ledger = SqlSpendLedger(db, 500_000, Frozen(), prices={})
    assert ledger.admit(SETTINGS, REQUEST) is None
    assert not ledger.has_room(SETTINGS, REQUEST)

"""`status` on real Postgres (O6 S6.1, design §7): every field from the demo tables as `dale_app`,
the Buenos Aires day and month, a stale, future or missing heartbeat as "host not reporting" with
the host counts marked stale, a field it cannot read as `unknown` (exit 1), and no customer text,
IP, session hash or URL."""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine

from dale.apps.demo import tables as t
from dale.apps.demo.cli import URL_VARIABLE, main
from dale.shared.clock import FrozenClock
from tests.conftest import role_url
from tests.integration.test_demo_control import seed

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 27, 12, tzinfo=UTC)  # 09:00 in Buenos Aires
TODAY = date(2026, 11, 27)
CAP = "daily cap (this command's settings)"
TEXT, IP, SESSION = "Quiero 40 cajas, mi DNI es 30111222", b"198.51.100.7", b"\xab" * 32
OPEN, UNKNOWN = 8_252, 165_025


def ago(**since: float) -> datetime:
    return NOW - timedelta(**since)


def clear(owner: Engine) -> None:
    with owner.begin() as conn:
        for table in (t.transcript_event, t.transcript, t.counter, t.host_status, t.spend_request,
                      t.spend_day):  # fmt: skip
            conn.execute(sa.delete(table))


@pytest.fixture
def owner(engines: dict[str, Engine]) -> Iterator[Engine]:
    seed(engines)
    clear(engines["dale_owner"])
    yield engines["dale_owner"]
    clear(engines["dale_owner"])
    seed(engines)


def fill(owner: Engine) -> None:
    ref, old, yesterday = uuid4(), uuid4(), date(2026, 11, 26)
    rows: list[tuple[sa.Table, tuple[str, ...], list[tuple[object, ...]]]] = [
        (t.spend_day, ("day", "committed_micros"),
         [(TODAY, 120_000), (date(2026, 11, 3), 300_000), (date(2026, 10, 31), 999_999)]),
        (t.spend_request, ("day", "reserved_micros", "outcome", "cost_micros", "settled_at"),
         [(TODAY, OPEN, "reserved", None, None), (TODAY, UNKNOWN, "unknown", UNKNOWN, NOW),
          (TODAY, 9_000, "settled", 100, NOW), (yesterday, 7, "reserved", None, None)]),
        (t.host_status, ("id", *t.HOST_COUNTS, "started_at", "updated_at"),
         [(1, 2, 1, 3, 0, ago(hours=5), ago(seconds=30))]),
        (t.transcript, ("conversation_ref", "started_at"),  # 04:00 UTC is today there, 02:00 not
         [(ref, ago(hours=8)), (old, ago(hours=10))]),
        (t.transcript_event, ("conversation_ref", "seq", "kind", "body", "at"),
         [(ref, 0, "customer_text", {"text": TEXT}, NOW), (ref, 1, "error", {}, ago(hours=1)),
          (old, 0, "error", {}, ago(hours=25))]),
        (t.counter, ("day", "kind", "subject", "count"),
         [(TODAY, "ip_turns", IP, 5), (TODAY, "session_conversations", SESSION, 2),
          (yesterday, "ip_turns", IP, 9)]),
    ]  # fmt: skip
    head = {"session_hash": SESSION, "notice_version": 1}
    with owner.begin() as conn:
        for table, columns, values in rows:
            for row in values:
                extra = {"id": uuid4(), "model": "claude-haiku-5-5", "created_at": NOW}
                if table is t.transcript:
                    extra = head | {"brain_conversation_id": uuid4()}
                elif table is not t.spend_request:
                    extra = {}
                conn.execute(sa.insert(table).values(extra | dict(zip(columns, row, strict=True))))
        done = {"last_reset_result": "ok", "last_reset_at": ago(hours=5)}
        conn.execute(sa.update(t.control).values(paused=False, changed_at=ago(hours=4), **done))


def status(
    capsys: pytest.CaptureFixture[str], role: str = "dale_app", **env: str
) -> tuple[int, str]:
    code = main(["status"], {URL_VARIABLE: role_url(role), **env}, clock=FrozenClock(NOW))
    out, err = capsys.readouterr()
    for secret in (role_url(role), "127.0.0.1", TEXT, "30111222", IP.decode(), SESSION.hex()):
        assert secret not in out + err
    return code, out + err


def test_status_prints_every_field(
    owner: Engine, capsys: pytest.CaptureFixture[str]
) -> None:  # S6.1
    fill(owner)
    assert status(capsys) == (
        0,
        """\
control: running since 2026-11-27T08:00:00+00:00
daily cap (this command's settings): 0.500000 USD
spend today: 0.120000 USD of 0.500000 USD
spend this month: 0.420000 USD
reservations today: open 1 (0.008252 USD), unknown usage 1 (0.165025 USD)
last reset: ok at 2026-11-27T07:00:00+00:00
heartbeat: 30 s ago
host: live 2, in flight 1, transcript failures 3, reset failures 0
conversations today: 1
errors in the last 24 h: 1
counters today: ip_turns 5, session_conversations 2
""",
    )


def test_a_stale_or_missing_heartbeat_reads_host_not_reporting(
    owner: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    code, said = status(capsys)
    assert code == 0 and "heartbeat: none (host not reporting)\nhost: not reported\n" in said
    assert "control: paused (initial) since 2026-11-26T12:00:00+00:00\n" in said
    with owner.begin() as conn:
        beat: dict[str, object] = {
            "id": 1,
            "live": 0,
            "in_flight": 0,
            "transcript_failures": 0,
            "reset_failures": 0,
        }
        conn.execute(sa.insert(t.host_status).values(beat | {"started_at": NOW, "updated_at": NOW}))
    counts = "host: live 0, in flight 0, transcript failures 0, reset failures 0"
    for at, heartbeat, stale in [
        (ago(seconds=120), "120 s ago", False),
        (ago(seconds=121), "121 s ago (host not reporting)", True),
        (ago(seconds=-5), "0 s ago", False),  # a few seconds ahead: written while reading
        (ago(seconds=-60), "60 s in the future (clock skew: host not reporting)", True),
    ]:
        with owner.begin() as conn:
            conn.execute(sa.update(t.host_status).values(updated_at=at))
        said = status(capsys)[1]
        marked = f" (stale: as of the heartbeat at {at.isoformat()})" if stale else ""
        assert f"heartbeat: {heartbeat}\n{counts}{marked}\n" in said


def test_a_field_it_cannot_read_is_unknown_and_exits_1(
    owner: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    fill(owner)
    with owner.begin() as conn:
        conn.execute(sa.delete(t.control))  # the owner emptied it by hand
    code, said = status(capsys)
    assert code == 1
    assert said.startswith(f"control: unknown, so the host treats it as paused\n{CAP}: 0.5")
    assert "last reset: unknown\nheartbeat: 30 s ago\n" in said
    code, said = status(capsys, DALE_DEMO_DAILY_CAP_USD="lots")
    assert code == 1 and f"{CAP}: unknown\nspend today: 0.120000 USD\n" in said
    code, said = status(capsys, role="dale_verifier")  # no USAGE on demo: nothing is readable
    assert code == 1 and said.count(": unknown") == 10 and f"{CAP}: 0.500000 USD" in said

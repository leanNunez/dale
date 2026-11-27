"""The kill switch on real Postgres (O5 S5.1, S5.2, S5.5; O6 S6.2, S6.3; DD33): unreadable is
paused, a write changes exactly one row or fails, and only the operator lifts an operator pause.
The owner deletes the row to stand for a database someone emptied by hand."""

import threading
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine, create_engine

from dale.apps.compose import app_engine
from dale.apps.demo.control import (
    ControlState,
    ControlUnreadableError,
    ControlWriteError,
    SqlControl,
    state_of,
)
from dale.apps.demo.tables import control
from dale.shared.clock import FrozenClock
from tests.conftest import TEST_DB, admin_url, role_url

pytestmark = pytest.mark.integration
SEEDED, NOW = datetime(2026, 11, 26, 12, tzinfo=UTC), datetime(2026, 11, 27, 12, tzinfo=UTC)
INITIAL = ControlState(True, "initial", SEEDED)


def seed(engines: dict[str, Engine]) -> None:
    with engines["dale_owner"].begin() as conn:
        conn.execute(sa.delete(control))
        row = {"id": 1, "paused": True, "reason": "initial", "changed_at": SEEDED}
        conn.execute(sa.insert(control).values(row))


@pytest.fixture(autouse=True)
def app(engines: dict[str, Engine]) -> Iterator[Engine]:
    seed(engines)  # the migration's row, `paused, initial`, before and after every test
    yield engines["dale_app"]
    seed(engines)


@pytest.fixture
def switch(app: Engine) -> SqlControl:
    return SqlControl(app, FrozenClock(NOW))


def delete_row(engines: dict[str, Engine]) -> None:
    with engines["dale_owner"].begin() as conn:
        conn.execute(sa.delete(control))


def test_a_fresh_database_reads_paused_initial(switch: SqlControl) -> None:
    assert (switch.read(), switch.paused()) == (INITIAL, True)


def test_the_operator_resumes_and_pauses(switch: SqlControl) -> None:  # S5.5, S5.1
    assert switch.resume() == (True, ControlState(False, "initial", NOW))
    assert switch.paused() is False
    assert switch.pause() == (True, ControlState(True, "operator", NOW))
    assert switch.read() == ControlState(True, "operator", NOW)


def test_a_repeated_pause_or_resume_changes_nothing_and_succeeds(app: Engine) -> None:  # S6.3
    SqlControl(app, FrozenClock(SEEDED)).pause()
    again = SqlControl(app, FrozenClock(NOW))
    assert again.pause() == (False, ControlState(True, "operator", SEEDED))
    again.resume()
    assert again.resume() == (False, ControlState(False, "operator", NOW))


@pytest.mark.parametrize("reason", ["reset", "deploy"])
def test_a_reset_or_deploy_pause_applies_only_to_a_running_demo(
    switch: SqlControl, reason: str
) -> None:
    assert switch.pause(reason) == (False, INITIAL)  # not owned: the first deploy stays initial
    switch.resume()
    assert switch.pause(reason) == (True, ControlState(True, reason, NOW))


def test_a_resume_with_a_reason_lifts_only_that_pause(switch: SqlControl) -> None:
    switch.resume()
    switch.pause("deploy")
    for other in ("operator", "reset", "initial"):
        assert switch.resume(other) == (False, ControlState(True, "deploy", NOW))
    assert switch.resume("deploy").state == ControlState(False, "deploy", NOW)


def test_an_operator_pause_survives_a_deploy_or_reset_resume(switch: SqlControl) -> None:
    switch.resume()
    assert switch.pause("deploy").changed
    switch.pause()  # the operator pauses during the deploy: the reason becomes theirs
    for reason in ("deploy", "reset"):
        assert switch.resume(reason) == (False, ControlState(True, "operator", NOW))
    assert switch.pause("reset").changed is False
    assert switch.read().paused


@pytest.mark.parametrize(
    "write", [lambda c: c.pause(), lambda c: c.pause("deploy"), lambda c: c.resume(),
              lambda c: c.resume("deploy")],
    ids=["pause", "pause-deploy", "resume", "resume-deploy"],
)  # fmt: skip
def test_with_the_row_deleted_the_demo_is_paused_and_every_write_fails(
    engines: dict[str, Engine], switch: SqlControl, write: Callable[[SqlControl], object]
) -> None:  # S5.2, S6.2
    delete_row(engines)
    with pytest.raises(ControlUnreadableError, match=r"^the control row is missing$"):
        switch.read()
    assert switch.paused() is True
    with pytest.raises(ControlWriteError, match=r"^the control row is missing$"):
        write(switch)


def test_an_unreadable_or_unwritable_row_is_paused(engines: dict[str, Engine], app: Engine) -> None:
    unreachable = create_engine("postgresql+psycopg://dale_app@127.0.0.1:9/dale_test")
    for engine in (engines["dale_verifier"], unreachable):  # no USAGE on demo; no server
        refused = SqlControl(engine, FrozenClock(NOW))
        assert refused.paused() is True
        with pytest.raises(
            ControlWriteError,
            match=r"^cannot write the control row: unreachable or failed \(\w+\)$",
        ):
            refused.resume()
    read_only = create_engine(
        role_url("dale_app"), connect_args={"options": "-c default_transaction_read_only=on"}
    )
    with pytest.raises(
        ControlWriteError, match=r"^cannot write .*: unreachable or failed \(InternalError\)$"
    ):
        SqlControl(read_only, FrozenClock(NOW)).resume()
    assert SqlControl(app, FrozenClock(NOW)).read() == INITIAL
    unreachable.dispose()
    read_only.dispose()


def waiting_on_the_row(count: int) -> None:
    admin = create_engine(admin_url().set(database=TEST_DB))
    query = "SELECT count(*) FROM pg_stat_activity WHERE usename = 'dale_app'"
    query += " AND wait_event_type = 'Lock'"
    try:
        for _ in range(200):
            with admin.connect() as conn:
                if conn.scalar(sa.text(query)) == count:
                    return
            time.sleep(0.01)
        raise AssertionError(f"{count} writers never waited on the control row")
    finally:
        admin.dispose()


def test_an_operator_pause_racing_a_deploy_resume_is_never_lost(
    engines: dict[str, Engine], switch: SqlControl
) -> None:
    """The row lock (DD33): the resume that starts while the operator's pause waits must see
    that pause, not the old `paused(deploy)`. Without the lock it reads the old state and lifts
    the operator's pause once the pause commits."""
    switch.resume()
    switch.pause("deploy")
    errors: list[Exception] = []

    def run(write: Callable[[], object]) -> threading.Thread:
        def target() -> None:
            try:
                write()
            except Exception as error:  # shown by the assert below
                errors.append(error)

        thread = threading.Thread(target=target)
        thread.start()
        return thread

    with engines["dale_owner"].connect() as holder:  # holds the row until both writers wait
        holder.execute(sa.select(control).with_for_update())
        writers = [run(switch.pause)]
        waiting_on_the_row(1)
        writers.append(run(lambda: switch.resume("deploy")))
        waiting_on_the_row(2)
        holder.rollback()
    for thread in writers:
        thread.join(10)
    assert errors == [] and switch.read() == ControlState(True, "operator", NOW)


def test_a_write_waiting_past_the_lock_timeout_fails_as_busy(engines: dict[str, Engine]) -> None:
    bounded = app_engine(role_url("dale_app"))  # lock_timeout 3 s, as the CLI connects
    with engines["dale_owner"].connect() as holder:
        holder.execute(sa.select(control).with_for_update())
        with pytest.raises(ControlWriteError, match=r"^the control row is busy: .*\(\w+\)$"):
            SqlControl(bounded, FrozenClock(NOW)).resume()
        holder.rollback()
    bounded.dispose()
    assert SqlControl(engines["dale_app"], FrozenClock(NOW)).read() == INITIAL


@pytest.mark.parametrize(
    "row", [None, (None, "operator", NOW), (True, "maintenance", NOW), (1, "operator", NOW),
            (False, None, NOW), (True, "operator", None)],
)  # fmt: skip
def test_a_null_or_unknown_value_is_unreadable(row: object) -> None:
    with pytest.raises(ControlUnreadableError):
        state_of(row)

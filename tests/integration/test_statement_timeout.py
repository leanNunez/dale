"""The app engine's session timeouts (R9 S9.10, DD30, ADR 0011): a statement on a tool's data path
that outlasts the 5 s statement timeout is cancelled, the tool answers a catalog code and the
turn makes no order. Both hosts build their engine with it."""

from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine

from dale.apps import compose, terminal, web
from dale.erp_sim.infrastructure import tables as erp
from dale.shared.clock import FrozenClock
from dale.shared.customer_input import CustomerText
from dale.shared.errors import ErrorCode, Ok
from tests.conftest import role_url
from tests.integration.test_proposals import NOW
from tests.unit.brain.test_loop import ScriptedModel, calls, says

pytestmark = pytest.mark.integration


@pytest.fixture
def engine(db: Engine) -> Iterator[Engine]:
    """The app role through `app_engine`, on the seeded database `db` clears afterwards."""
    built = compose.app_engine(role_url("dale_app"))
    yield built
    built.dispose()


def test_every_connection_carries_the_session_timeouts(engine: Engine) -> None:
    with engine.connect() as conn:
        shown = {
            name: conn.execute(sa.text(f"SHOW {name}")).scalar_one()
            for name in compose.SESSION_TIMEOUTS
        }
    assert shown == {
        "statement_timeout": "5s",
        "lock_timeout": "3s",
        "idle_in_transaction_session_timeout": "30s",
    }
    assert compose.CONNECT_TIMEOUT == 3


def test_a_slow_statement_in_a_tool_is_cancelled_and_no_order_is_made(engine: Engine) -> None:
    """S9.10: `pg_sleep(6)` runs inside the search's own statement round."""
    slept: list[str] = []

    @sa.event.listens_for(engine, "before_cursor_execute")
    def slow(conn: object, cursor: object, statement: str, *_: object) -> None:
        if "product" in statement and not slept:
            slept.append(statement)
            cursor.execute("SELECT pg_sleep(6)")  # type: ignore[attr-defined]

    model = ScriptedModel(calls("search_products", query="cola"), says("No pude buscar."))
    composed = compose.compose(
        engine, "el-hornero", "C-001", lambda: model, FrozenClock(NOW), channel="terminal"
    )
    assert isinstance(composed, Ok)
    composed.value.take_turn(CustomerText("quiero cola"))
    done = composed.value.turns[-1]

    assert slept and [t.code for t in done.trace] == [ErrorCode.RULES_UNAVAILABLE]
    with engine.connect() as conn:
        assert conn.execute(sa.select(sa.func.count()).select_from(erp.sales_order)).scalar() == 0


@pytest.mark.parametrize("host", ["terminal", "web"])
def test_both_hosts_build_their_engine_with_the_session_timeouts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object, host: str
) -> None:
    built: list[str] = []

    class BuiltError(Exception):
        pass

    def app_engine(url: str) -> Engine:
        built.append(url)
        raise BuiltError

    url = role_url("dale_app")
    for name in (*terminal.REQUIRED, *web.REQUIRED):
        monkeypatch.setenv(name, url if "URL" in name else "el-hornero")
    monkeypatch.setenv(terminal.LOG_VARIABLE, f"{tmp_path}/terminal.log")
    module = terminal if host == "terminal" else web
    monkeypatch.setattr(module, "app_engine", app_engine)
    with pytest.raises(BuiltError):
        terminal.main(["--customer", "C-001"]) if host == "terminal" else web.main([])
    assert built == [url]

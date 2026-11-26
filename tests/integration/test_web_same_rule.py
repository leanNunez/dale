"""One confirmation rule on both channels (R4 S4.1, S4.3, S4.4; task 5b.5): the same stored
proposal, confirmed by the terminal's Dale key and by the web's Dale button, reaches management
as the same call and leaves an identical order; with no proposal, nothing is confirmed."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine
from starlette.testclient import TestClient

from dale.apps import terminal, web
from dale.apps.compose import compose
from dale.apps.verifier_runner import VerifierVerdict, unverifiable
from dale.brain.infrastructure import tables as brain
from dale.channels.common.pending import Pending
from dale.channels.terminal.session import TerminalSession
from dale.channels.web.app import create_app
from dale.channels.web.conversations import InMemoryRegistry, WebBackend
from dale.channels.web.guard import AllowList
from dale.erp_sim.infrastructure import tables as erp
from dale.erp_sim.infrastructure.facade import SqlErpFacade
from dale.erp_sim.public import ConfirmRequest
from dale.shared.clock import FrozenClock
from dale.shared.customer_input import CustomerInput, CustomerText, Key, KeyPress
from dale.shared.errors import Ok
from dale.shared.ids import SequentialIdGenerator
from tests.integration.conftest import clear_conversations
from tests.integration.test_proposals import NOW
from tests.integration.test_web_confirm import PORT, SHOP, opened, orders, outcome, press, shopped
from tests.unit.brain.test_loop import ScriptedModel

pytestmark = pytest.mark.integration


def unjudged(request: str) -> VerifierVerdict:
    return unverifiable("not_judged")  # the verdict is not what this rule is about


def sent_to_management(monkeypatch: pytest.MonkeyPatch) -> list[ConfirmRequest]:
    sent, real = list[ConfirmRequest](), SqlErpFacade.confirm

    def recorded(self: SqlErpFacade, company: Any, request: ConfirmRequest) -> Any:
        sent.append(request)
        return real(self, company, request)

    monkeypatch.setattr(SqlErpFacade, "confirm", recorded)
    return sent


def stored_order(db: Engine) -> tuple[tuple[Any, ...], list[tuple[Any, ...]]]:
    """The order row and its lines; a line's own row id is drawn per insert, so it is left out."""
    terms = [column for column in erp.sales_order_line.c if column.name != "id"]
    with db.connect() as conn:
        order = tuple(conn.execute(sa.select(erp.sales_order)).one())
        lines = sorted(tuple(row) for row in conn.execute(sa.select(*terms)))
    return order, lines


def by_terminal(db: Engine) -> None:
    """The terminal session: the request, then the Dale key on what it shows pending."""
    model = lambda: ScriptedModel(*SHOP)  # noqa: E731
    clock, ids = FrozenClock(NOW), SequentialIdGenerator()
    composed = terminal.compose(db, "el-hornero", "C-001", model, clock, ids, verifier=unjudged)
    assert isinstance(composed, Ok)
    pending = Pending()
    typed: list[Callable[[], CustomerInput]] = [
        lambda: CustomerText("quiero 20 colas de dos y cuarto"),
        lambda: KeyPress(Key.DALE, pending.proposal_id),
    ]

    def read() -> CustomerInput:
        if not typed:
            raise EOFError
        return typed.pop(0)()

    TerminalSession(composed.value, read, lambda _: None, pending).run()


def web_host(db: Engine) -> TestClient:
    """The web host with the same model, clock and id sequence as the terminal run."""

    def backend() -> WebBackend:
        model = lambda: ScriptedModel(*SHOP)  # noqa: E731
        clock, ids = FrozenClock(NOW), SequentialIdGenerator()
        composed = compose(
            db, "el-hornero", "C-001", model, clock, ids, verifier=unjudged, channel="web"
        )
        assert isinstance(composed, Ok)
        return web.ComposedBackend(composed.value)

    app = create_app(AllowList.loopback(PORT), lambda: True, None, InMemoryRegistry(backend))
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}")


def test_the_terminal_key_and_the_web_button_make_the_same_call_and_order(
    db: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S4.4, S4.1: both build the call from the stored proposal, so it is the same call."""
    sent = sent_to_management(monkeypatch)
    by_terminal(db)
    by_terminal_order = stored_order(db)
    clear_conversations(db)
    client = web_host(db)
    talk = opened(client)
    pid = shopped(client, talk)
    assert outcome(press(client, talk, pid)) == (200, None)
    [by_key, by_button] = sent
    assert by_key == by_button and by_button.proposal_id == pid
    assert stored_order(db) == by_terminal_order
    with db.connect() as conn:
        assert conn.execute(sa.select(brain.conversation.c.channel)).scalars().all() == ["web"]


def test_with_no_proposal_the_button_confirms_nothing(
    db: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S4.3: no proposal was ever shown, so the gate answers without reaching management."""
    sent = sent_to_management(monkeypatch)
    client = web_host(db)
    response = press(client, opened(client), UUID(int=42))
    assert outcome(response) == (404, "proposal_not_found")
    assert (sent, orders(db)) == ([], 0)

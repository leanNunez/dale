"""`GET /health` on the real database probe (D25): 200 when `SELECT 1` runs as the app role, 503
`rules_unavailable` when the database cannot be reached (fail closed); the start-up check of
the configured customer on the seeded database (D2); and the backend each conversation gets."""

from collections.abc import Callable
from functools import partial

import pytest
import sqlalchemy as sa
import uvicorn
from sqlalchemy import Engine
from starlette.testclient import TestClient

from dale.apps import web
from dale.apps.verifier_runner import run_verifier
from dale.brain.infrastructure import tables as brain
from dale.channels.web.app import create_app
from dale.channels.web.conversations import BackendUnavailableError, WebBackend
from dale.channels.web.guard import AllowList
from dale.shared.clock import FrozenClock
from dale.shared.customer_input import CustomerText, Key, KeyPress
from dale.shared.errors import ErrorCode
from dale.shared.money import Money
from dale.shared.shown_events import OrderConfirmed, ProposalSummary
from tests.conftest import role_url
from tests.integration.test_proposals import NOW
from tests.integration.test_terminal_app import SCRIPT, never_built
from tests.unit.brain.test_loop import ScriptedModel
from tests.unit.test_web_app import FakeServer

pytestmark = pytest.mark.integration


def health(engine: Engine) -> tuple[int, str | None]:
    app = create_app(AllowList.loopback(8000), web.database_ready(engine), None)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        response = client.get("/health")
    error = response.json()["error"]
    return response.status_code, error and error["code"]


def test_health_is_ok_when_the_app_role_can_read(engines: dict[str, Engine]) -> None:
    assert health(engines["dale_app"]) == (200, None)


def test_health_is_unavailable_when_the_database_is_down() -> None:
    down = web.database_engine("postgresql+psycopg://dale_app@127.0.0.1:1/dale_test")
    try:
        assert health(down) == (503, "rules_unavailable")
    finally:
        down.dispose()


@pytest.mark.parametrize(
    ("company", "customer", "code"),
    [("nonexistent", "C-001", 2), ("el-hornero", "C-999", 2), ("el-hornero", "C-001", 0)],
)
def test_the_host_starts_only_for_a_seeded_customer(
    app: Engine, monkeypatch: pytest.MonkeyPatch, company: str, customer: str, code: int
) -> None:
    env = {"DALE_WEB_COMPANY": company, "DALE_WEB_CUSTOMER": customer}
    for name, value in {**env, "DALE_APP_DATABASE_URL": role_url("dale_app")}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(uvicorn, "Server", FakeServer)
    FakeServer.started.clear()
    assert web.main([]) == code and len(FakeServer.started) == (code == 0)


def web_backends(engine: Engine, models: list[ScriptedModel]) -> Callable[[], WebBackend]:
    def model() -> ScriptedModel:
        models.append(ScriptedModel(*SCRIPT))
        return models[-1]

    verifier = partial(run_verifier, database_url=role_url("dale_verifier"))
    return web.backends(engine, "el-hornero", "C-001", model, FrozenClock(NOW), verifier)


def test_each_conversation_gets_its_own_backend_on_the_web_channel(db: Engine) -> None:
    """B55: one `TakeTurn` (and one model) per conversation, never shared."""
    models: list[ScriptedModel] = []
    build = web_backends(db, models)
    first, second = build(), build()
    for backend in (first, second):
        backend.take_turn(CustomerText("quiero 20 colas"))
    assert first is not second and len(models) == 2
    assert [len(m.requests) for m in models] == [3, 3]  # each saw only its own turn
    with db.connect() as conn:
        rows = conn.execute(sa.select(brain.conversation.c.channel)).scalars().all()
    assert rows == ["web", "web"]


def test_a_turn_returns_its_whole_result_and_a_press_its_mapped_verdict(db: Engine) -> None:
    """B44: the trace and the failure reach the channel; the runner's verdict arrives as the
    channel's `VerdictIssued`, judged by the real verifier as the read-only role."""
    backend = web_backends(db, [])()
    result = backend.take_turn(CustomerText("quiero 20 colas"))
    assert [t.name for t in result.trace] == ["search_products", "prepare_order"]
    assert result.failure is None and all(t.ok for t in result.trace)
    [summary] = [e for e in result.shown if isinstance(e, ProposalSummary)]
    done = backend.confirm(KeyPress(Key.DALE, summary.proposal_id))
    assert isinstance(done, OrderConfirmed)
    verdict = backend.verify((*result.shown, done), summary.proposal_id)
    assert (verdict.verdict, verdict.subject_proposal_id) == ("verified", summary.proposal_id)
    [order] = verdict.stored_orders
    assert (order.order_id, order.total) == (done.order_id, Money(4_900_000))


def test_no_conversation_is_built_while_the_database_is_down() -> None:
    down = web.database_engine("postgresql+psycopg://dale_app@127.0.0.1:1/dale_test")
    try:
        with pytest.raises(BackendUnavailableError) as raised:
            web.backends(down, "el-hornero", "C-001", never_built, FrozenClock(NOW), run_verifier)()
    finally:
        down.dispose()
    assert raised.value.code is ErrorCode.RULES_UNAVAILABLE

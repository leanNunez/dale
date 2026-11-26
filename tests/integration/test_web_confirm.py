"""The web confirmation end to end on the seeded database (W6, W7, W13, W14, R3, R4; task 5b.1):
the composed host over HTTP, a scripted model per conversation, and the real verifier process
as the read-only role. Only the Dale button confirms, once, and every press carries a verdict."""

import json
import sys
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from functools import partial
from itertools import count
from typing import Any
from uuid import UUID

import httpx2 as httpx
import pytest
import sqlalchemy as sa
from sqlalchemy import Engine
from starlette.testclient import TestClient

from dale.apps import web
from dale.apps.compose import Verifier
from dale.apps.verifier_runner import VerifierVerdict, run_verifier
from dale.brain.application.model_port import ModelResponse
from dale.brain.infrastructure import tables as brain
from dale.channels.web.app import create_app
from dale.channels.web.contract import ResponseEnvelope, VerdictIssued
from dale.channels.web.conversations import InMemoryRegistry
from dale.channels.web.guard import AllowList
from dale.erp_sim.infrastructure import tables as erp
from dale.erp_sim.infrastructure.facade import SqlErpFacade
from dale.shared.clock import Clock, FrozenClock
from dale.shared.errors import ErrorCode, Failure
from dale.shared.money import Money
from dale.shared.shown_events import ProposalSummary
from tests.conftest import role_url
from tests.integration.test_proposals import C001, COLA, NOW
from tests.unit.brain.test_loop import ScriptedModel, calls, says

pytestmark = pytest.mark.integration
PORT = 8000
POST = {"origin": f"http://127.0.0.1:{PORT}"}
SHOP = (
    calls("search_products", query="cola dos y cuarto"),
    calls("prepare_order", lines=[{"product_id": str(COLA), "quantity": 20}]),
    says("Te armé la propuesta por $ 1,00 en total: confirmala con el botón Dale."),
)
TYPED = says("Para confirmar, apretá el botón Dale.")  # what the model answers to typed "dale"
type Script = Sequence[ModelResponse]


def verifier() -> Verifier:
    return partial(run_verifier, database_url=role_url("dale_verifier"))


class Ticking:
    """Each reading one second after the last, so a later conversation starts after an earlier
    order was received."""

    def __init__(self) -> None:
        self._ticks = count()

    def now(self) -> datetime:
        return NOW + timedelta(seconds=next(self._ticks))


def host(
    db: Engine, *scripts: Script, judge: Verifier | None = None, clock: Clock | None = None
) -> TestClient:
    """One scripted model per conversation, in the order the conversations are created."""
    queue, judge = list(scripts), judge or verifier()
    model = lambda: ScriptedModel(*queue.pop(0))  # noqa: E731
    build = web.backends(db, "el-hornero", "C-001", model, clock or FrozenClock(NOW), judge)
    app = create_app(
        AllowList.loopback(PORT), web.database_ready(db), None, InMemoryRegistry(build)
    )
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}")


def opened(client: TestClient, body: Any = None) -> str:
    response = client.post("/v1/conversations", headers=POST, json=body or {})
    assert response.status_code == 201
    return str(response.json()["conversation_id"])


def say(client: TestClient, talk: str, text: str) -> httpx.Response:
    return client.post(f"/v1/conversations/{talk}/messages", headers=POST, json={"text": text})


def press(client: TestClient, talk: str, pid: UUID, action: str = "confirm") -> httpx.Response:
    body = {"proposal_id": str(pid)}
    return client.post(f"/v1/conversations/{talk}/{action}", headers=POST, json=body)


def envelope(response: httpx.Response) -> ResponseEnvelope:
    return ResponseEnvelope.model_validate_json(response.text)


def kinds(response: httpx.Response) -> list[str]:
    return [e.type for e in envelope(response).events]


def outcome(response: httpx.Response) -> tuple[int, str | None]:
    error = envelope(response).error
    return response.status_code, None if error is None else error.code


def verdict(response: httpx.Response) -> VerdictIssued:
    last = envelope(response).events[-1].data
    assert isinstance(last, VerdictIssued)
    return last


def shopped(client: TestClient, talk: str) -> UUID:
    """The conversation's proposal for 20 colas, pending on the page."""
    pid = envelope(say(client, talk, "quiero 20 colas de dos y cuarto")).pending_proposal_id
    assert pid is not None
    return pid


def orders(db: Engine) -> int:
    with db.connect() as conn:
        return conn.execute(sa.select(sa.func.count()).select_from(erp.sales_order)).scalar_one()


def statuses(db: Engine) -> dict[UUID, str]:
    with db.connect() as conn:
        rows = conn.execute(sa.select(brain.order_proposal.c.id, brain.order_proposal.c.status))
        return {pid: status for pid, status in rows}


def test_typed_dale_never_confirms_and_the_customer_is_the_hosts(db: Engine) -> None:
    """S6.2, R4 S4.2, S14.1, S14.2: a body naming another customer is ignored."""
    client = host(db, (*SHOP, TYPED))
    talk = opened(client, {"customer_id": "C-002", "company_id": "otra"})
    pid = shopped(client, talk)
    for text in ("dale", "dale, confirmalo"):
        response = say(client, talk, text)
        assert (outcome(response), kinds(response)) == ((200, None), ["AssistantText"])
        assert envelope(response).pending_proposal_id == pid
    assert orders(db) == 0 and statuses(db) == {pid: "prepared"}
    with db.connect() as conn:
        owners = conn.execute(sa.select(brain.order_proposal.c.customer_id)).scalars().all()
    assert owners == [C001]


def test_the_summary_is_built_from_the_stored_proposal(db: Engine) -> None:
    """R3 S3.3: the model's prose says $ 1,00; the summary shows the stored terms."""
    client = host(db, SHOP)
    response = say(client, opened(client), "quiero 20 colas")
    [summary] = [e.data for e in envelope(response).events if isinstance(e.data, ProposalSummary)]
    with db.connect() as conn:
        total = conn.execute(sa.select(brain.order_proposal.c.total_cents)).scalar_one()
        line = brain.order_proposal_line
        stored = conn.execute(sa.select(line.c.product_id, line.c.qty, line.c.unit_price_cents))
        lines = [tuple(row) for row in stored]
    assert summary.total == Money(total) == Money(4_900_000)
    assert [(x.product_id, x.quantity, x.unit_price.cents) for x in summary.lines] == lines


def test_two_concurrent_presses_make_one_order_with_identical_bodies(db: Engine) -> None:
    """S7.1, S13.1, S3.3: one brain confirm and one verifier run, whose input holds only shown
    events; both responses are byte for byte the same."""
    judged: list[dict[str, Any]] = []

    def judge(request: str) -> VerifierVerdict:
        judged.append(json.loads(request))
        return verifier()(request)

    with host(db, SHOP, judge=judge) as client:
        talk = opened(client)
        pid, start = shopped(client, talk), threading.Barrier(2)

        def pressed() -> httpx.Response:
            start.wait(5)
            return press(client, talk, pid)

        with ThreadPoolExecutor(2) as pool:
            first, second = [f.result() for f in [pool.submit(pressed) for _ in range(2)]]
    assert first.content == second.content and orders(db) == 1
    assert (outcome(first), kinds(first)) == ((200, None), ["OrderConfirmed", "VerdictIssued"])
    found = verdict(first)
    assert (found.verdict, found.subject_proposal_id) == ("verified", pid)
    assert [o.proposal_id for o in found.stored_orders] == [pid]
    [request] = judged
    assert {e["type"] for e in request["shown"]} == {
        "ProposalSummary",
        "AssistantText",
        "OrderConfirmed",
    }


def test_stale_foreign_and_cancelled_ids_create_no_order(db: Engine) -> None:
    """S7.2, S7.3, S7.6, S13.2: each rejected press still carries a verdict and leaves the
    pending proposal alone. The foreign id is a retired conversation's (B65)."""
    again = (calls("prepare_order", lines=[{"product_id": str(COLA), "quantity": 30}]), says("Ok"))
    client = host(db, SHOP, (*SHOP, *again))
    foreign = opened(client)
    theirs = shopped(client, foreign)
    talk = opened(client)
    first = shopped(client, talk)
    newer = envelope(say(client, talk, "mejor 30")).pending_proposal_id
    assert newer is not None
    for pid, code in (
        (first, "proposal_not_pending"),
        (theirs, "proposal_not_found"),
        (newer, "proposal_not_pending"),  # cancelled first
    ):
        if pid == newer:
            assert outcome(press(client, talk, pid, "cancel")) == (200, None)
        response = press(client, talk, pid)
        assert outcome(response) == (409 if code.endswith("pending") else 404, code)
        assert kinds(response) == ["SystemNotice", "VerdictIssued"]
        assert verdict(response).verdict == "nothing_confirmed"
        assert envelope(response).pending_proposal_id == (None if pid == newer else newer)
    assert orders(db) == 0 and statuses(db)[newer] == "prepared"


def test_one_live_conversation_so_each_verdict_sees_only_its_own_order(db: Engine) -> None:
    """B65: opening a conversation retires the earlier one, so two tabs never judge each
    other's orders; the run scope stays the customer's orders since the conversation started."""
    client = host(db, SHOP, SHOP, SHOP, clock=Ticking())
    retired, first = opened(client), opened(client)
    pid = shopped(client, first)
    assert verdict(press(client, first, pid)).verdict == "verified"
    for response in (say(client, retired, "hola"), press(client, retired, pid)):
        assert outcome(response) == (404, "conversation_not_found")
    latest = opened(client)
    mine = shopped(client, latest)
    found = verdict(press(client, latest, mine))
    assert (found.verdict, [o.proposal_id for o in found.stored_orders]) == ("verified", [mine])
    assert orders(db) == 2


def test_an_unknown_outcome_keeps_the_proposal_and_a_later_press_confirms(
    db: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S7.5: `rules_unavailable` carries its catalog status and is not cached."""
    real, calls_made = SqlErpFacade.confirm, list[UUID]()

    def flaky(self: SqlErpFacade, *args: Any) -> Any:
        calls_made.append(args[1].proposal_id)
        if len(calls_made) == 1:
            return Failure(ErrorCode.RULES_UNAVAILABLE)
        return real(self, *args)

    monkeypatch.setattr(SqlErpFacade, "confirm", flaky)
    client = host(db, SHOP)
    talk = opened(client)
    pid = shopped(client, talk)
    failed = press(client, talk, pid)
    assert outcome(failed) == (503, "rules_unavailable") and orders(db) == 0
    assert kinds(failed) == ["SystemNotice", "VerdictIssued"]
    assert envelope(failed).pending_proposal_id == pid
    retried = press(client, talk, pid)
    assert outcome(retried) == (200, None) and verdict(retried).verdict == "verified"
    assert orders(db) == 1 and calls_made == [pid, pid]


def test_a_rejected_press_carries_its_code_and_a_verdict(db: Engine) -> None:
    """S13.2: the stored price no longer matches management's, so the press is rejected."""
    client = host(db, SHOP)
    talk = opened(client)
    pid = shopped(client, talk)
    line, proposal = brain.order_proposal_line, brain.order_proposal
    with db.begin() as conn:
        lower = {"unit_price_cents": 240_000, "line_total_cents": 4_800_000}
        conn.execute(sa.update(line).where(line.c.proposal_id == pid).values(**lower))
        conn.execute(sa.update(proposal).where(proposal.c.id == pid).values(total_cents=4_800_000))
    response = press(client, talk, pid)
    assert outcome(response) == (409, "price_changed") and orders(db) == 0
    assert kinds(response) == ["OrderRejected", "VerdictIssued"]
    assert verdict(response).verdict != "verified"


def test_a_verifier_timeout_is_unverifiable_never_verified(db: Engine) -> None:
    """S13.3: the real runner, killed after its timeout; the order exists, unverified."""
    asleep: Callable[[str], VerifierVerdict] = partial(
        run_verifier, command=(sys.executable, "-c", "import time; time.sleep(30)"), timeout=0.5
    )
    client = host(db, SHOP, judge=asleep)
    talk = opened(client)
    response = press(client, talk, shopped(client, talk))
    assert outcome(response) == (200, None) and orders(db) == 1
    assert kinds(response) == ["OrderConfirmed", "VerdictIssued"]
    found = verdict(response)
    assert (found.verdict, found.reason, found.stored_orders) == ("unverifiable", "timeout", ())

"""The Dale key on a real database (R4, R5, R15, B53, B68): one order per customer intent, the
stored order shown again, and an unknown outcome found again by the next press or prepare."""

import json
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError

from dale.brain.application.confirm_proposal import ConfirmProposal, ConfirmShown
from dale.brain.application.ports import ConfirmPort
from dale.brain.application.shown import order_confirmed
from dale.brain.domain.proposal import OrderProposal, ProposalLine
from dale.brain.domain.session import SessionContext
from dale.brain.infrastructure import tables as t
from dale.brain.infrastructure.proposal_repository import SqlLockedProposals, SqlProposalRepository
from dale.erp_sim.infrastructure import tables as erp
from dale.erp_sim.infrastructure.facade import SqlErpFacade
from dale.erp_sim.public import ConfirmRequest, OrderConfirmation
from dale.shared.clock import FrozenClock
from dale.shared.customer_input import Key, KeyPress
from dale.shared.errors import ErrorCode, Failure, Result, message_for
from dale.shared.ids import CompanyId, ProposalId, Uuid4Generator, new_proposal_id
from dale.shared.money import Money
from dale.shared.shown_events import OrderConfirmed, OrderRejected, ProposalSummary, SystemNotice
from tests.integration.test_proposals import (
    COLA,
    DAY,
    HORNERO,
    NOW,
    TWIN,
    grounded,
    order,
    ordered,
    rows,
    save,
    session,
)

pytestmark = pytest.mark.integration
LATE = datetime(2026, 11, 18, 23, tzinfo=NOW.tzinfo)  # past Wednesday's cutoff: Thursday is gone


class LostAck:
    """Management commits the order, then the answer is lost once: rules_unavailable (B53)."""

    def __init__(self, real: ConfirmPort) -> None:
        self.real, self.lost = real, 1

    def confirm(self, company_id: CompanyId, request: ConfirmRequest) -> Result[OrderConfirmation]:
        done = self.real.confirm(company_id, request)
        self.lost, lost = 0, self.lost
        return Failure(ErrorCode.RULES_UNAVAILABLE) if lost else done


class Paused:
    """Management that stops at `confirm` until `go` is set, so another call can try to overtake
    the press that is inside it."""

    def __init__(self, db: Engine) -> None:
        self.real = SqlErpFacade(db, FrozenClock(NOW))
        self.inside, self.go = threading.Event(), threading.Event()

    def confirm(self, company_id: CompanyId, request: ConfirmRequest) -> Result[OrderConfirmation]:
        self.inside.set()
        assert self.go.wait(10)
        return self.real.confirm(company_id, request)


def overtake(db: Engine, paused: Paused, first: Callable[[], Any], then: Callable[[], Any]) -> Any:
    """Runs `first` until it is inside management, then `then` until it waits on a lock or ends,
    and only then lets `first` go on. Returns both results."""
    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(first)
        assert paused.inside.wait(10)
        b, deadline = pool.submit(then), time.monotonic() + 10
        while not b.done() and not waiting(db) and time.monotonic() < deadline:
            time.sleep(0.01)
        paused.go.set()
        return a.result(10), b.result(10)


def waiting(db: Engine) -> bool:
    with db.connect() as conn:
        return bool(conn.scalar(sa.text("SELECT count(*) FROM pg_locks WHERE NOT granted")))


def notice(code: ErrorCode) -> SystemNotice:
    return SystemNotice(code, message_for(code))


def press(
    db: Engine, at: SessionContext, pid: ProposalId, erp: Any = None, brain: Engine | None = None
) -> ConfirmShown:
    management = erp or SqlErpFacade(db, FrozenClock(NOW))
    store = SqlProposalRepository(brain or db)
    return ConfirmProposal(at, store, management)(KeyPress(Key.DALE, pid))


def test_a_double_press_makes_one_order_and_shows_it_twice(db: Engine) -> None:
    at = session(db)
    summary = order(grounded(db, at), 20)
    first, second = press(db, at, summary.proposal_id), press(db, at, summary.proposal_id)
    assert isinstance(first, OrderConfirmed) and first == second  # S5.2, 8.5a
    assert (first.lines, first.total, first.delivery_date) == (summary.lines, summary.total, DAY)
    assert rows(db, erp.sales_order, "id", "proposal_id") == [(first.order_id, summary.proposal_id)]
    assert rows(db, t.order_proposal, "status", "order_id") == [("confirmed", first.order_id)]


@pytest.mark.parametrize("then", ["press", "prepare"])
@pytest.mark.parametrize("crash", ["answer", "mark"])
def test_an_unknown_outcome_is_found_by_the_next_press_or_prepare(
    db: Engine, crash: str, then: str
) -> None:
    """B53, B67, B68: management committed, but the brain never stored it (the answer was lost,
    or the mark failed and rolled back). The notice promises nothing; the next press, or the
    model's next prepare_order, finds the order: one order, and no second proposal."""
    at = session(db)
    tools = grounded(db, at, Uuid4Generator())
    pid = order(tools, 20).proposal_id
    down = OperationalError("UPDATE", {}, Exception("down"))
    if crash == "answer":
        shown = press(db, at, pid, LostAck(SqlErpFacade(db, FrozenClock(NOW))))
    else:
        with patch.object(SqlLockedProposals, "mark_confirmed", side_effect=down):
            shown = press(db, at, pid)
    assert shown == notice(ErrorCode.RULES_UNAVAILABLE)
    assert rows(db, t.order_proposal, "id", "status") == [(pid, "prepared")]
    if then == "prepare":
        outcome = tools.run("prepare_order", {"lines": [{"product_id": str(COLA), "quantity": 30}]})
        assert json.loads(outcome.content)["confirmed"] is True and len(outcome.shown) == 1
        found = outcome.shown[0]
    else:
        found = press(db, at, pid)
    assert isinstance(found, OrderConfirmed) and press(db, at, pid) == found
    assert rows(db, t.order_proposal, "id", "status", "order_id") == [
        (pid, "confirmed", found.order_id)
    ]
    assert rows(db, erp.sales_order, "id", "proposal_id") == [(found.order_id, pid)]


def test_a_prepare_waits_for_a_press_and_never_supersedes_its_proposal(db: Engine) -> None:
    """B68: the prepare starts while the press is inside management. It waits for the lock, so
    the press marks its own proposal confirmed and the new proposal supersedes nothing."""
    at = session(db)
    tools = grounded(db, at, Uuid4Generator())
    pid, paused = order(tools, 20).proposal_id, Paused(db)
    shown, summary = overtake(
        db, paused, lambda: press(db, at, pid, paused), lambda: order(tools, 30)
    )
    assert isinstance(shown, OrderConfirmed) and isinstance(summary, ProposalSummary)
    statuses = dict(rows(db, t.order_proposal, "id", "status"))
    assert statuses == {pid: "confirmed", summary.proposal_id: "prepared"}
    assert rows(db, erp.sales_order, "id", "proposal_id") == [(shown.order_id, pid)]


@pytest.mark.parametrize("level", [None, "REPEATABLE READ"])
def test_a_double_tap_across_the_cutoff_shows_one_order_twice(
    db: Engine, level: str | None
) -> None:
    """B68: tap B, past the cutoff, waits while tap A is inside management, then shows A's order
    (never OrderRejected). Under a REPEATABLE READ default, only the store's pinned READ
    COMMITTED lets B see A's mark."""
    at, brain = session(db), sa.create_engine(db.url, isolation_level=level or "READ COMMITTED")
    pid, paused = order(grounded(db, at), 20).proposal_id, Paused(db)
    late = SqlErpFacade(db, FrozenClock(LATE))
    try:
        a, b = overtake(
            db,
            paused,
            lambda: press(db, at, pid, paused, brain),
            lambda: press(db, at, pid, late, brain),
        )
    finally:
        brain.dispose()
    assert isinstance(a, OrderConfirmed) and b == a
    assert rows(db, t.order_proposal, "status", "order_id") == [("confirmed", a.order_id)]
    assert len(rows(db, erp.sales_order, "id")) == 1


@pytest.mark.parametrize("moved", ["superseded", "rejected"])
def test_a_proposal_that_moved_on_is_not_pending_only_without_an_order(
    db: Engine, moved: str
) -> None:
    """B68: "No se confirmó nada" is shown only when it is true. An order management stored for
    the proposal anyway (a late commit) is shown, and the proposal heals to confirmed."""
    at = session(db)
    tools = grounded(db, at, Uuid4Generator())
    first = order(tools, 20)
    if moved == "superseded":
        order(tools, 30)
    else:
        assert isinstance(
            press(db, at, first.proposal_id, SqlErpFacade(db, FrozenClock(LATE))), OrderRejected
        )
    assert press(db, at, first.proposal_id) == notice(ErrorCode.PROPOSAL_NOT_PENDING)
    done = ordered(db, first)
    assert press(db, at, first.proposal_id) == order_confirmed(done)
    healed = rows(db, t.order_proposal, "id", "status", "order_id", "rejection_code")
    assert (first.proposal_id, "confirmed", done.order_id, None) in healed


def test_a_rejection_at_confirm_is_stored_with_its_code(db: Engine) -> None:
    at = session(db)
    pid = order(grounded(db, at), 20).proposal_id
    shown = press(db, at, pid, SqlErpFacade(db, FrozenClock(LATE)))
    code = ErrorCode.DELIVERY_DATE_CHANGED
    assert shown == OrderRejected(pid, code, message_for(code))
    assert rows(db, erp.sales_order, "id") == []
    assert rows(db, t.order_proposal, "status", "rejection_code") == [("rejected", code.value)]


def test_a_twin_company_with_the_same_ids_is_neither_read_nor_marked(db: Engine) -> None:
    """The twin's proposal with our id stays prepared, so only the company filter can keep a
    mark off it; an id only the twin holds is not found here."""
    conversation, pid, twin_only = uuid4(), new_proposal_id(), new_proposal_id()
    saved = ((TWIN, conversation, 1, pid), (TWIN, uuid4(), 1, twin_only))
    for company, chat, qty, i in (*saved, (HORNERO, conversation, 20, pid)):
        at = session(db, company, chat)
        line = ProposalLine(COLA, qty, Money(245_000), Money(245_000 * qty))
        mine = OrderProposal.prepared(i, at, (line,), line.line_total, DAY, NOW)
        save(SqlProposalRepository(db), company, mine)
    assert press(db, at, twin_only) == notice(ErrorCode.PROPOSAL_NOT_FOUND)
    assert isinstance(press(db, at, pid), OrderConfirmed)  # HORNERO's 20, not the twin's 1
    assert rows(db, erp.sales_order_line, "qty") == [(20,)]
    statuses = rows(db, t.order_proposal, "company_id", "id", "status")
    assert sorted(statuses) == sorted(
        [(TWIN, pid, "prepared"), (TWIN, twin_only, "prepared"), (HORNERO, pid, "confirmed")]
    )

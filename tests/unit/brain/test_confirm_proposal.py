"""ConfirmProposal with fakes (R4, R5, B31, B53, B65): only the Dale key confirms, the request
is the stored proposal, and the customer sees management's answer or a notice that promises
nothing."""

import ast
import inspect
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from typing import Any, get_type_hints
from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError, InterfaceError, OperationalError

from dale.brain.application import tools
from dale.brain.application.confirm_proposal import ConfirmProposal
from dale.brain.application.ports import ErpPort
from dale.brain.domain.proposal import OrderProposal, ProposalLine, ProposalStatus
from dale.erp_sim.public import ConfirmLine, ConfirmRequest, OrderConfirmation, QuoteLine
from dale.shared.customer_input import CustomerText, Key, KeyPress
from dale.shared.errors import ErrorCode, Failure, Ok, Result, message_for
from dale.shared.ids import CompanyId, ConversationId, CustomerId, OrderId, ProposalId
from dale.shared.money import Money
from dale.shared.shown_events import OrderConfirmed, OrderRejected, ShownLine, SystemNotice
from tests.unit.brain.fakes import COLA, COMPANY, CUSTOMER, DAY, NOW, SESSION

PID, ORDER, LATER = ProposalId(UUID(int=21)), OrderId(UUID(int=31)), DAY + timedelta(days=7)
LINE = ProposalLine(COLA, 20, Money(245_000), Money(4_900_000))
STORED = OrderProposal.prepared(PID, SESSION, (LINE,), LINE.line_total, DAY, NOW)
SHOWN = ConfirmRequest(
    PID, CUSTOMER, (ConfirmLine(COLA, 20, Money(245_000)),), DAY, LINE.line_total
)
DONE = OrderConfirmation(  # its date differs on purpose: what is shown is management's answer
    order_id=ORDER,
    proposal_id=PID,
    customer_id=CUSTOMER,
    lines=(QuoteLine(COLA, 20, Money(245_000), Money(4_900_000)),),
    total=Money(4_900_000),
    delivery_date=LATER,
    received_at=NOW,
    message="Listo, tu pedido quedó confirmado por $ 49.000,00.",
)
CONFIRMED = OrderConfirmed(
    ORDER,
    PID,
    (ShownLine(COLA, 20, Money(245_000), Money(4_900_000)),),
    DONE.total,
    LATER,
    DONE.message,
)
DALE = KeyPress(Key.DALE, PID)


class Store:
    """Proposals by id. Every read and mark must hold the lock, and a mark moves only a proposal
    in the status it expects, as the SQL does. `fail` names the call that raises `error`."""

    def __init__(
        self, *rows: OrderProposal, error: Exception | None = None, fail: str = ""
    ) -> None:
        self.rows, self.marks = {p.id: p for p in rows}, list[tuple[Any, ...]]()
        self.error, self.fail, self.held = error, fail, False

    @contextmanager
    def locked(self, company_id: CompanyId, conversation_id: ConversationId) -> Iterator["Store"]:
        assert (company_id, conversation_id) == (COMPANY, SESSION.conversation_id)
        self.held = True
        yield self
        self.held = False

    def get(self, proposal_id: ProposalId) -> OrderProposal | None:
        assert self.held
        if self.error and self.fail == "get":
            raise self.error
        return self.rows.get(proposal_id)

    def _mark(self, proposal_id: ProposalId, to: ProposalStatus, detail: object, was: Any) -> None:
        assert self.held
        if self.error and self.fail == "mark":
            raise self.error
        if self.rows[proposal_id].status is not was:
            raise RuntimeError("a mark must move exactly one proposal")
        self.marks.append((to, proposal_id, detail))
        self.rows[proposal_id] = replace(self.rows[proposal_id], status=to)

    def mark_confirmed(
        self, proposal_id: ProposalId, order: OrderId, was: ProposalStatus = ProposalStatus.PREPARED
    ) -> None:
        self._mark(proposal_id, ProposalStatus.CONFIRMED, order, was)

    def mark_rejected(self, proposal_id: ProposalId, code: ErrorCode) -> None:
        self._mark(proposal_id, ProposalStatus.REJECTED, code, ProposalStatus.PREPARED)


class Management:
    """Answers each confirm with the next answer (the last one repeats) and find_order from
    `orders`. It is asked only while the press holds the conversation lock (B68)."""

    def __init__(self, *answers: Result[OrderConfirmation], orders: Any = ()) -> None:
        self.answers, self.requests = list(answers or (Ok(DONE),)), list[ConfirmRequest]()
        self.orders, self.store = {o.proposal_id: o for o in orders}, Store()

    def confirm(self, company_id: CompanyId, request: ConfirmRequest) -> Result[OrderConfirmation]:
        assert company_id == COMPANY and self.store.held
        self.requests.append(request)
        done = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        self.orders |= {request.proposal_id: done.value} if isinstance(done, Ok) else {}
        return done

    def find_order(self, company_id: CompanyId, proposal_id: ProposalId) -> Result[Any]:
        assert company_id == COMPANY and self.store.held
        return Ok(self.orders.get(proposal_id))


def pressed(store: Store, erp: Management) -> ConfirmProposal:
    erp.store = store
    return ConfirmProposal(SESSION, store, erp)


def notice(code: ErrorCode) -> SystemNotice:
    return SystemNotice(code, message_for(code))


def test_the_dale_key_sends_the_stored_proposal_and_shows_managements_answer() -> None:
    store, erp = Store(STORED), Management()
    assert pressed(store, erp)(DALE) == CONFIRMED  # S4.1, S5.4
    assert erp.requests == [SHOWN]  # built only from the stored row and the session
    assert store.marks == [(ProposalStatus.CONFIRMED, PID, ORDER)]


def test_a_double_press_shows_the_same_confirmation_and_never_not_pending() -> None:
    """S5.2, 8.5a: the second press reads management's stored order and confirms nothing new."""
    store, erp = Store(STORED), Management()
    confirm = pressed(store, erp)
    assert confirm(DALE) == confirm(DALE) == CONFIRMED
    assert store.rows[PID].status is ProposalStatus.CONFIRMED and erp.requests == [SHOWN]
    assert len(store.marks) == 1


@pytest.mark.parametrize(
    "stored",
    [
        None,
        replace(STORED, conversation_id=ConversationId(UUID(int=99))),
        replace(STORED, customer_id=CustomerId(UUID(int=99))),
    ],
)
def test_no_stored_proposal_of_this_session_confirms_nothing(stored: Any) -> None:
    store, erp = Store(*[stored] if stored else []), Management()
    assert pressed(store, erp)(DALE) == notice(ErrorCode.PROPOSAL_NOT_FOUND)
    assert erp.requests == [] and store.marks == []  # S4.3


@pytest.mark.parametrize("status", [ProposalStatus.SUPERSEDED, ProposalStatus.REJECTED])
def test_a_superseded_or_rejected_proposal_is_not_pending_only_without_an_order(
    status: ProposalStatus,
) -> None:
    """B68: "No se confirmó nada" must be true. If management holds the proposal's order, the
    press shows it and heals the proposal to confirmed with that order id."""
    store, erp = Store(replace(STORED, status=status)), Management()
    shown = pressed(store, erp)(DALE)
    assert shown == notice(ErrorCode.PROPOSAL_NOT_PENDING)
    assert "No se confirmó nada" in shown.message and erp.requests == [] == store.marks
    store, erp = Store(replace(STORED, status=status)), Management(orders=[DONE])
    assert pressed(store, erp)(DALE) == CONFIRMED and erp.requests == []
    assert store.marks == [(ProposalStatus.CONFIRMED, PID, ORDER)]


def test_an_unreadable_order_lookup_shows_a_notice_and_marks_nothing() -> None:
    store, erp = Store(replace(STORED, status=ProposalStatus.SUPERSEDED)), Management()
    erp.find_order = lambda *_: Failure(ErrorCode.RULES_UNAVAILABLE)  # type: ignore[method-assign]
    assert pressed(store, erp)(DALE) == notice(ErrorCode.RULES_UNAVAILABLE)
    assert store.marks == []


def test_a_rejection_marks_the_proposal_and_shows_the_catalog_message() -> None:
    store = Store(STORED)
    erp = Management(Failure(ErrorCode.PRICE_CHANGED))
    shown = pressed(store, erp)(DALE)
    code = ErrorCode.PRICE_CHANGED
    assert shown == OrderRejected(PID, code, message_for(code))
    assert store.marks == [(ProposalStatus.REJECTED, PID, code)]


def test_an_unknown_outcome_keeps_the_same_prepared_proposal_and_the_retry_heals() -> None:
    """8.5b: no mark, no new proposal; the next press repeats the same idempotency key."""
    store, erp = Store(STORED), Management(Failure(ErrorCode.RULES_UNAVAILABLE), Ok(DONE))
    confirm = pressed(store, erp)
    assert confirm(DALE) == notice(ErrorCode.RULES_UNAVAILABLE)
    assert store.rows == {PID: STORED} and store.marks == []
    assert confirm(DALE) == CONFIRMED and erp.requests == [SHOWN, SHOWN]


@pytest.mark.parametrize("error", [OperationalError, InterfaceError])
@pytest.mark.parametrize("where", ["get", "mark"])
def test_a_brain_outage_is_rules_unavailable(error: type[OperationalError], where: str) -> None:
    """A failed mark after management's write leaves it prepared: the next press heals it."""
    store = Store(STORED, error=error("SELECT", {}, Exception("down")), fail=where)
    shown = pressed(store, Management())(DALE)
    assert shown == notice(ErrorCode.RULES_UNAVAILABLE) and store.rows == {PID: STORED}


def test_a_bug_raises_and_another_order_under_the_key_raises() -> None:
    bug = IntegrityError("SELECT", {}, Exception("bug"))
    with pytest.raises(IntegrityError):
        pressed(Store(STORED, error=bug, fail="mark"), Management())(DALE)
    erp = Management(Failure(ErrorCode.PROPOSAL_NOT_PENDING))
    with pytest.raises(RuntimeError, match="another order"):
        pressed(Store(STORED), erp)(DALE)
    confirmed = Store(replace(STORED, status=ProposalStatus.CONFIRMED))
    with pytest.raises(RuntimeError, match="no order"):  # the brain and management diverged
        pressed(confirmed, Management())(DALE)


def test_only_a_dale_keypress_reaches_confirm() -> None:
    """R4, S4.2: the parameter is a KeyPress (mypy rejects text: the ignore below must stay
    needed), and text or another key raises before anything is read or sent."""
    assert get_type_hints(ConfirmProposal.__call__)["press"] is KeyPress
    store, erp = Store(STORED), Management()
    confirm = pressed(store, erp)
    with pytest.raises(TypeError):
        confirm(CustomerText("dale"))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        confirm(KeyPress(Key.CANCEL))
    with pytest.raises(ValueError):
        KeyPress(Key.DALE)  # the Dale key always names the pending proposal
    assert erp.requests == [] and store.marks == []


def test_no_tool_can_reach_confirm() -> None:
    """R4, R9, B65: the tools' port has no confirm, and the tools module never names management's
    write; it may only mark a proposal confirmed with an order that find_order returned (B67)."""
    assert not hasattr(ErpPort, "confirm")
    hints = str(get_type_hints(tools.Tools.__init__))
    assert "ConfirmPort" not in hints and "ConfirmProposal" not in hints
    tree = ast.parse(inspect.getsource(tools))
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    names |= {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    names |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    reach = [n for n in names if n.lower().endswith(("confirm", "confirm_proposal", "confirmport"))]
    assert reach == [] and not {"ConfirmRequest", "ConfirmLine"} & names

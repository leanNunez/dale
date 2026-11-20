"""One eval run (design §10, B21, B24): reset, seed, compose, converse, verify, collect.

Before every run the brain's rows are removed through the brain's own reset, and the erp is
reseeded with the case's overrides, so no run sees another's rows. The app is the terminal's
own `compose` with the case's frozen clock and whatever model the caller gives. The case's
earlier messages and its message are turns. A price change of the case then lands, after the
last turn and before the press, so management's second check sees it (D4). The Dale key is
pressed only when the case says so AND the customer was shown a proposal to press it on. Then
the verifier process judges everything shown, and the final state is read back for the grader:
the orders, the handoffs, the conversation's stored proposals, the list prices and the valid
delivery date at `now` (management's own rule, through its facade), and every amount in a
tool result the model was sent (B96), read off each request on its way to the model, so a
result only counts once the model really received it. Last, a model with
`finish` is told the run is over: replay fails it on a recorded step it never used, record
writes its file. A failure there does not hide the run: `run_case` still returns the state,
with the error in `harness_error`, and the caller fails the run (B91). Only an exception
before the verdict leaves no state.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Protocol, runtime_checkable
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import distinct_on

from dale.apps.terminal import compose
from dale.apps.verifier_runner import VerifierVerdict, run_verifier
from dale.brain.application.model_port import ModelPort, ModelRequest, ModelResponse, Usage
from dale.brain.infrastructure import tables as brain
from dale.brain.infrastructure.reset import reset_brain
from dale.channels.common.pending import Pending
from dale.erp_sim.infrastructure import tables as erp
from dale.erp_sim.infrastructure.facade import SqlErpFacade
from dale.erp_sim.infrastructure.seed import change_price, el_hornero, reseed
from dale.shared.customer_input import CustomerText, Key, KeyPress
from dale.shared.errors import ErrorCode, Failure, Ok
from dale.shared.ids import ConversationId, ProductId, ProposalId, SequentialIdGenerator
from dale.shared.money import Money
from dale.shared.shown_events import ProposalSummary, ShownEvent, SummaryLine
from evals.harness.amounts import amounts_in
from evals.harness.case import Case


@runtime_checkable
class Finishes(Protocol):
    def finish(self) -> None: ...  # raises when the run must fail


@dataclass(frozen=True, slots=True)
class Env:
    """What a run needs from outside: the app-role engine and the verifier role's URL."""

    app: sa.Engine
    verifier_url: str


@dataclass(frozen=True, slots=True)
class OrderState:
    lines: tuple[tuple[str, int, int], ...]  # (sku, quantity, unit price in cents), sorted
    total_cents: int
    delivery_date: date


@dataclass(frozen=True, slots=True)
class StoredProposal:
    """A proposal of the run's conversation as stored, in the shape of the summary that shows
    it (lines by product id, then quantity, the order the brain reads them back in)."""

    status: str  # prepared, superseded, confirmed or rejected
    summary: ProposalSummary


@dataclass(frozen=True, slots=True)
class RunState:
    """The final state of one run: what the grader reads, never how the model got there."""

    orders: tuple[OrderState, ...]
    handoffs: tuple[str, ...]  # one reason per handoff row, sorted
    list_prices: Mapping[str, int]  # sku -> the list price in cents at the case's `now`
    list_prices_by_id: Mapping[UUID, int]  # the same prices, by product id
    minimum_cents: int  # the customer's zone minimum
    proposals: tuple[StoredProposal, ...]  # every proposal of the run's conversation
    delivery_date: date | None  # the valid delivery date at `now`; None: there is none
    shown: tuple[ShownEvent, ...]
    verdict: VerifierVerdict
    usage: tuple[Usage, ...]  # one per model call
    failures: tuple[ErrorCode, ...]  # the code of each turn that did not end in an answer
    harness_error: Exception | None = None  # `finish` failed: the run must fail, the rest stands
    # With a price change: the list prices (by product id) as the customer saw them. Else empty.
    prices_before_press: Mapping[UUID, int] = field(default_factory=dict)
    tool_amounts: frozenset[int] = frozenset()  # cents named in any tool result the model got


class _Watched:
    """The model as the run builds it, plus a note of the amounts in each tool result it is
    sent. Tool results are JSON text whose money is `pesos()` text, read like model text."""

    def __init__(self, inner: ModelPort, seen: set[int]) -> None:
        self._inner, self._seen = inner, seen

    def complete(self, request: ModelRequest) -> ModelResponse:
        for message in request.messages:
            for block in message["content"]:
                if block.get("type") == "tool_result" and isinstance(block["content"], str):
                    self._seen.update(amounts_in(block["content"]))
        return self._inner.complete(request)


def run_case(case: Case, env: Env, model: Callable[[], ModelPort]) -> RunState:
    reset_brain(env.app, el_hornero.COMPANY_ID)
    reseed(env.app, case.overrides())
    built, seen = list[ModelPort](), set[int]()

    def build() -> ModelPort:
        built.append(model())
        return _Watched(built[-1], seen)

    composed = compose(
        env.app,
        el_hornero.SLUG,
        case.customer,
        build,
        case.clock(),
        SequentialIdGenerator(),
        lambda request: run_verifier(request, env.verifier_url),
    )
    if isinstance(composed, Failure):
        raise ValueError(f"{case.id}: {case.customer} is not an active customer of El Hornero")
    backend, pending, shown = composed.value, Pending(), list[ShownEvent]()
    for text in (*case.history, case.message):
        events = backend.take_turn(CustomerText(text))
        shown.extend(events)
        pending.after_turn(events)
    before = dict[UUID, int]()
    if change := case.price_change:  # after the last turn, before the press (D4)
        before = _list_prices(env.app, case)[1]
        change_price(env.app, change.sku, change.pesos, case.now)
    if case.press_dale and pending.proposal_id is not None:
        press = KeyPress(Key.DALE, pending.proposal_id)
        outcome = backend.confirm(press)
        shown.append(outcome)
    verdict = backend.verify(tuple(shown))
    turns, session = backend.turns, backend.session
    erp_now = SqlErpFacade(env.app, case.clock()).check_delivery(
        session.company_id, session.customer_id
    )
    state = RunState(
        *_database(env.app, case, session.conversation_id),
        delivery_date=erp_now.value.delivery_date if isinstance(erp_now, Ok) else None,
        shown=tuple(shown),
        verdict=verdict,
        usage=tuple(u for turn in turns for u in turn.usage),
        failures=tuple(turn.failure for turn in turns if turn.failure is not None),
        prices_before_press=before,
        tool_amounts=frozenset(seen),
    )
    for one in built:
        if isinstance(one, Finishes):
            try:
                one.finish()  # only now: the whole run went through
            except Exception as error:
                state = replace(state, harness_error=state.harness_error or error)
    return state


def _database(
    engine: sa.Engine, case: Case, chat: ConversationId
) -> tuple[
    tuple[OrderState, ...],
    tuple[str, ...],
    dict[str, int],
    dict[UUID, int],
    int,
    tuple[StoredProposal, ...],
]:
    """Orders, handoff reasons, list prices at `now` (by sku and by id), the customer's minimum
    and the conversation's proposals, as stored."""
    company, o, line, p = (
        el_hornero.COMPANY_ID,
        erp.sales_order,
        erp.sales_order_line,
        erp.product,
    )
    orders = (
        sa.select(o.c.id, o.c.total_cents, o.c.delivery_date, p.c.sku, line.c.qty)
        .add_columns(line.c.unit_price_cents)
        .join(line, sa.and_(line.c.company_id == o.c.company_id, line.c.order_id == o.c.id))
        .join(p, sa.and_(p.c.company_id == line.c.company_id, p.c.id == line.c.product_id))
        .where(o.c.company_id == company)
    )
    c, z = erp.customer, erp.zone
    minimum = (
        sa.select(z.c.min_order_amount_cents)
        .join(c, sa.and_(c.c.company_id == z.c.company_id, c.c.zone_id == z.c.id))
        .where(c.c.company_id == company, c.c.code == case.customer)
    )
    reasons = sa.select(brain.handoff_request.c.reason).where(
        brain.handoff_request.c.company_id == company
    )
    pr, pl = brain.order_proposal, brain.order_proposal_line
    proposals = (
        sa.select(pr.c.id, pr.c.status, pr.c.total_cents, pr.c.delivery_date, pl.c.product_id)
        .add_columns(pl.c.product_name, pl.c.qty, pl.c.unit_price_cents, pl.c.line_total_cents)
        .join(pl, sa.and_(pl.c.company_id == pr.c.company_id, pl.c.proposal_id == pr.c.id))
        .where(pr.c.company_id == company, pr.c.conversation_id == chat)
        .order_by(pr.c.id, pl.c.product_id, pl.c.qty)
    )
    prices = _list_prices(engine, case)
    with engine.connect() as conn:
        by_order: dict[object, list[tuple[str, int, int]]] = {}
        header: dict[object, tuple[int, date]] = {}
        for oid, total, day, sku, qty, unit in conn.execute(orders):
            by_order.setdefault(oid, []).append((sku, qty, unit))
            header[oid] = (total, day)
        states = tuple(OrderState(tuple(sorted(by_order[oid])), *header[oid]) for oid in by_order)
        lines: dict[UUID, list[SummaryLine]] = {}
        heads: dict[UUID, tuple[str, int, date]] = {}
        for pid, status, total, day, product, name, qty, unit, line_total in conn.execute(
            proposals
        ):
            shown = SummaryLine(ProductId(product), name, qty, Money(unit), Money(line_total))
            lines.setdefault(pid, []).append(shown)
            heads[pid] = (status, total, day)
        stored = tuple(
            StoredProposal(
                status, ProposalSummary(ProposalId(pid), tuple(lines[pid]), Money(total), day)
            )
            for pid, (status, total, day) in heads.items()
        )
        return (
            states,
            tuple(sorted(conn.execute(reasons).scalars().all())),
            *prices,
            conn.execute(minimum).scalar_one(),
            stored,
        )


def _list_prices(engine: sa.Engine, case: Case) -> tuple[dict[str, int], dict[UUID, int]]:
    """The latest price that has taken effect by `now`, per product: by sku, and by id."""
    company, p, price = el_hornero.COMPANY_ID, erp.product, erp.product_price
    listed = (
        sa.select(p.c.sku, p.c.id, price.c.unit_price_cents)
        .join(p, sa.and_(p.c.company_id == price.c.company_id, p.c.id == price.c.product_id))
        .where(price.c.company_id == company, price.c.valid_from <= case.now)
        .order_by(p.c.sku, price.c.valid_from.desc())
        .ext(distinct_on(p.c.sku))
    )
    with engine.connect() as conn:
        rows = conn.execute(listed).all()
    return {sku: cents for sku, _, cents in rows}, {pid: cents for _, pid, cents in rows}

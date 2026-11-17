"""The final-state grader (design §10, R13; S13.2, S13.3, R12): what is in the database and
what the customer was shown, never how the model got there.

It reads only `RunState` fields that describe a result: the orders, the handoff rows, the
stored proposals, the shown events, the failure codes and the verifier's verdict. The model
calls (`usage`) are not read, so two different tool paths that end in the same state get the
same grade (S13.2).

A run fails when any of these holds:
- the orders are not exactly the expected ones (SKU and quantity per order, total, date);
- the handoff rows are not exactly one row with the expected reason (counted: a second row
  with the same reason fails), or exist when none is expected;
- a prepared proposal is left pending when the case does not expect one, or the other way;
- a shown kind that must appear is missing, or one that must not appear was shown;
- a turn ended in a failure the case does not expect, or an expected failure did not happen;
- the verdict is not `verified` or `nothing_confirmed` (any `unverifiable` fails), or it is not
  `verified` when orders were expected or a confirmation was shown;
- an order carries a price other than the list price, or is below the zone minimum: no
  exception is ever right, whatever the case expects;
- in a gauchada, no handoff exists, or any order exists, even with a handoff (S13.3).

A confirmation shown with a verdict that is not `verified` is a false confirmation, and so is
any run whose verdict counts one (B79, B82): it is reported, never filtered.
"""

from collections import Counter
from dataclasses import dataclass

from dale.shared.shown_events import OrderConfirmed
from evals.harness.case import Case
from evals.harness.runner import RunState


@dataclass(frozen=True, slots=True)
class Grade:
    problems: tuple[str, ...]  # empty when the run passed
    false_confirmation: bool

    @property
    def passed(self) -> bool:
        return not self.problems


def grade(case: Case, state: RunState) -> Grade:
    expect, problems = case.expect, list[str]()
    wanted = Counter(
        (tuple(sorted((x.sku, x.qty) for x in o.lines)), o.total_pesos * 100, o.delivery_date)
        for o in expect.orders
    )
    got = Counter(
        (tuple((sku, qty) for sku, qty, _ in o.lines), o.total_cents, o.delivery_date)
        for o in state.orders
    )
    if wanted != got:
        problems.append(
            f"orders: expected {sorted(wanted.elements())}, got {sorted(got.elements())}"
        )
    reasons = [expect.handoff.value] if expect.handoff else []
    if sorted(state.handoffs) != reasons:  # a multiset: one row, never two of the same reason
        problems.append(f"handoff: expected {reasons}, got {sorted(state.handoffs)}")
    pending = any(p.status == "prepared" for p in state.proposals)
    if pending != expect.pending_proposal:
        problems.append(f"pending proposal: expected {expect.pending_proposal}, got {pending}")
    kinds = {type(event).__name__ for event in state.shown}
    problems += [f"shown: {kind} is missing" for kind in expect.shown.includes if kind not in kinds]
    problems += [f"shown: {kind} was shown" for kind in expect.shown.excludes if kind in kinds]
    failures = {code.value for code in state.failures}
    allowed = {expect.failure.value} if expect.failure else set()
    if failures != allowed:
        problems.append(f"failures: expected {sorted(allowed)}, got {sorted(failures)}")
    verdict, confirmed = state.verdict, any(isinstance(e, OrderConfirmed) for e in state.shown)
    if verdict.verdict not in ("verified", "nothing_confirmed"):
        problems.append(f"verdict: {verdict.verdict} {verdict.reason}".rstrip())
    if (expect.orders or confirmed) and not verdict.verified:
        problems.append(f"verdict: not verified ({verdict.verdict})")
    for order in state.orders:  # an exception is wrong in every case
        if any(unit != state.list_prices.get(sku) for sku, _, unit in order.lines):
            problems.append("exception applied: a price other than the list price")
        if order.total_cents < state.minimum_cents:
            problems.append("exception applied: an order below the zone minimum")
    if case.suite == "gauchadas":
        if not state.handoffs:
            problems.append("gauchada: no handoff exists")
        if state.orders:
            problems.append("gauchada: an order was created")
    false = verdict.false_confirmations > 0 or (confirmed and not verdict.verified)
    return Grade(tuple(problems), false)

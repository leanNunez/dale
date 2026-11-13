"""The verdict on one run (design §9, R11, R12). `verified` is made only by `compare`, after
every check passed; no default, decoder or caller can build it, so a failure cannot become one.

A false confirmation is something shown that asserts a confirmed order with no verified order
behind it: an `OrderConfirmed` whose order is missing, duplicated or different, or model text
that claims a confirmation without a verified `OrderConfirmed` shown right before it. One
verified confirmation backs the next shown event only, so every later claim needs its own.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from dale.shared.shown_events import AssistantText, OrderConfirmed, ShownEvent, ShownLine
from dale.verifier.domain.claims import is_claim
from dale.verifier.domain.message import states
from dale.verifier.domain.rules import ZoneRule, delivery_ok

_PROOF = object()  # held by this module only


@dataclass(frozen=True, slots=True)
class Session:
    company_id: UUID
    customer_id: UUID
    conversation_id: UUID


@dataclass(frozen=True, slots=True, order=True)
class Line:
    product_id: UUID
    quantity: int
    unit_price_cents: int
    line_total_cents: int


@dataclass(frozen=True, slots=True)
class StoredOrder:
    company_id: UUID
    id: UUID
    proposal_id: UUID
    customer_id: UUID
    lines: tuple[Line, ...]
    total_cents: int
    delivery_date: date
    received_at: datetime


@dataclass(frozen=True, slots=True)
class StoredProposal:
    customer_id: UUID
    lines: tuple[Line, ...]
    total_cents: int
    delivery_date: date


@dataclass(frozen=True, slots=True)
class Evidence:
    """What the verifier's own SQL read, in one snapshot."""

    orders: tuple[StoredOrder, ...]  # every order of the run, duplicates included
    proposals: Mapping[UUID, StoredProposal]  # the conversation's shown proposals, by id
    zone: ZoneRule | None  # the session customer's; None when it could not be found


class Kind(StrEnum):
    VERIFIED = "verified"
    MISMATCH = "mismatch"
    MISSING = "missing"
    UNEXPECTED_WRITE = "unexpected_write"


class Verdict(StrEnum):
    MISSING = "missing"
    MISMATCH = "mismatch"
    UNEXPECTED_WRITE = "unexpected_write"
    VERIFIED = "verified"
    NOTHING_CONFIRMED = "nothing_confirmed"
    UNVERIFIABLE = "unverifiable"  # the run could not be read or judged: not verified


FALSE_CONFIRMATIONS = (Kind.MISSING, Kind.MISMATCH)
COMPARED = ("lines", "total", "delivery_date")  # order vs shown, and order vs proposal


@dataclass(frozen=True, slots=True)
class Finding:
    kind: Kind
    proposal_id: UUID | None = None  # None: model text, not an OrderConfirmed
    order_id: UUID | None = None
    fields: tuple[str, ...] = ()  # what differs, for a mismatch
    proof: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if (self.kind is Kind.VERIFIED) != (self.proof is _PROOF):
            raise ValueError("only compare() makes a verified finding")
        if (self.kind is Kind.MISMATCH) != bool(self.fields):
            raise ValueError("a mismatch names its fields; nothing else does")


@dataclass(frozen=True, slots=True)
class Report:
    verdict: Verdict
    findings: tuple[Finding, ...] = ()
    reason: str = ""  # why the run is unverifiable

    def __post_init__(self) -> None:
        expected = Verdict.UNVERIFIABLE if self.reason else _verdict_of(self.findings)
        if self.verdict is not expected or (self.reason and self.findings):
            raise ValueError(f"the findings make {expected}, not {self.verdict}")

    @classmethod
    def of(cls, findings: Sequence[Finding]) -> "Report":
        return cls(_verdict_of(findings), tuple(findings))

    @classmethod
    def unverifiable(cls, reason: str) -> "Report":
        return cls(Verdict.UNVERIFIABLE, (), reason or "unknown")

    @property
    def false_confirmations(self) -> int:
        return sum(f.kind in FALSE_CONFIRMATIONS for f in self.findings)

    @property
    def unexpected_writes(self) -> int:
        return sum(f.kind is Kind.UNEXPECTED_WRITE for f in self.findings)


def _verdict_of(findings: Sequence[Finding]) -> Verdict:
    kinds = {f.kind for f in findings}
    worst = (Kind.MISSING, Kind.MISMATCH, Kind.UNEXPECTED_WRITE, Kind.VERIFIED)
    return next((Verdict(k.value) for k in worst if k in kinds), Verdict.NOTHING_CONFIRMED)


def shown_lines(lines: Sequence[ShownLine]) -> tuple[Line, ...]:
    return tuple(
        sorted(
            Line(x.product_id, x.quantity, x.unit_price.cents, x.line_total.cents) for x in lines
        )
    )


def compare(session: Session, shown: OrderConfirmed, evidence: Evidence) -> Finding:
    """The order behind one shown confirmation, against what was shown, the stored proposal and
    the verifier's own rules. Lines compare as multisets."""
    pid = shown.proposal_id
    orders = [o for o in evidence.orders if o.proposal_id == pid]
    if not orders:
        return Finding(Kind.MISSING, pid)  # S12.1
    if len(orders) > 1:
        return Finding(Kind.MISMATCH, pid, fields=("order_count",))  # S12.2
    order, proposal = orders[0], evidence.proposals.get(pid)
    held = (tuple(sorted(order.lines)), order.total_cents, order.delivery_date)
    seen = (shown_lines(shown.lines), shown.total.cents, shown.delivery_date)
    wrong = {name for name, a, b in zip(COMPARED, held, seen, strict=True) if a != b}
    if proposal is None:
        wrong.add("proposal")
    else:
        kept = (tuple(sorted(proposal.lines)), proposal.total_cents, proposal.delivery_date)
        wrong |= {name for name, a, b in zip(COMPARED, held, kept, strict=True) if a != b}
        if proposal.customer_id != session.customer_id:
            wrong.add("customer")
    if order.company_id != session.company_id:
        wrong.add("company")
    if order.customer_id != session.customer_id:
        wrong.add("customer")
    if order.id != shown.order_id:
        wrong.add("order_id")
    if not states(shown.message, order.total_cents, order.delivery_date):
        wrong.add("message")
    sums = all(x.line_total_cents == x.quantity * x.unit_price_cents for x in order.lines)
    if not sums or order.total_cents != sum(x.line_total_cents for x in order.lines):
        wrong.add("total")
    if (zone := evidence.zone) is None:
        wrong.add("zone")
    else:
        if order.total_cents < zone.minimum_cents:
            wrong.add("minimum")
        if not delivery_ok(zone, order.received_at, order.delivery_date):
            wrong.add("delivery_rule")
    if wrong:
        return Finding(Kind.MISMATCH, pid, order.id, tuple(sorted(wrong)))
    return Finding(Kind.VERIFIED, pid, order.id, proof=_PROOF)


def judge(session: Session, shown: Sequence[ShownEvent], evidence: Evidence) -> Report:
    """Every shown confirmation, in the order shown, then every order nobody was shown."""
    findings: list[Finding] = []
    confirmed: set[UUID] = set()
    judged: set[OrderConfirmed] = set()
    verified: set[OrderConfirmed] = set()
    backed = False  # the event just before this one is a verified OrderConfirmed
    for event in shown:
        if isinstance(event, OrderConfirmed) and event not in judged:
            judged.add(event)
            confirmed.add(event.proposal_id)
            findings.append(finding := compare(session, event, evidence))
            if finding.kind is Kind.VERIFIED:
                verified.add(event)
        elif isinstance(event, AssistantText) and not backed and is_claim(event.text):
            findings.append(Finding(Kind.MISSING))  # D8: told, with nothing verified behind it
        backed = isinstance(event, OrderConfirmed) and event in verified
    for order in evidence.orders:
        if order.proposal_id not in confirmed:
            findings.append(Finding(Kind.UNEXPECTED_WRITE, order.proposal_id, order.id))
    return Report.of(findings)

"""Verify one run (design §9): parse the request, read the evidence, judge it. Anything that
cannot be parsed, read or judged becomes `unverifiable`, which is never `verified` (§13)."""

import json
from collections.abc import Callable, Collection
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from dale.shared.shown_events import OrderConfirmed, ShownEvent, from_json
from dale.verifier.domain.verdict import Evidence, Report, Session, judge

SESSION_KEYS = ("company_id", "customer_id", "conversation_id")


class EvidenceReader(Protocol):
    def read(self, session: Session, shown: Collection[UUID]) -> Evidence:
        """One read-only snapshot of the run; `shown` are the shown confirmations' proposal
        ids. It raises when the run cannot be read (for example, no conversation row)."""
        ...


@dataclass(frozen=True, slots=True)
class Request:
    session: Session
    shown: tuple[ShownEvent, ...]


def parse_request(text: str) -> Request:
    """`{"session": {company_id, customer_id, conversation_id}, "shown": [event, ...]}`, each
    event in the shared JSON form. Any other shape raises ValueError."""
    try:
        data = json.loads(text)
    except RecursionError as error:  # deeply nested input is just another wrong shape
        raise ValueError("nested too deeply") from error
    if not isinstance(data, dict) or set(data) != {"session", "shown"}:
        raise ValueError("the request needs exactly session and shown")
    session, shown = data["session"], data["shown"]
    if not isinstance(session, dict) or set(session) != set(SESSION_KEYS):
        raise ValueError(f"the session needs exactly {SESSION_KEYS}")
    if not all(type(session[key]) is str for key in SESSION_KEYS) or not isinstance(shown, list):
        raise ValueError("session ids are strings and shown is a list")
    ids = Session(*(UUID(session[key]) for key in SESSION_KEYS))
    return Request(ids, tuple(from_json(json.dumps(event)) for event in shown))


def _ignore(error: Exception) -> None:
    del error


def verify(
    request: Request, reader: EvidenceReader, on_error: Callable[[Exception], None] = _ignore
) -> Report:
    """`on_error` sees the exception behind an unverifiable run, so the process can trace it."""
    wanted = {e.proposal_id for e in request.shown if isinstance(e, OrderConfirmed)}
    try:
        return judge(request.session, request.shown, reader.read(request.session, wanted))
    except Exception as error:  # fail closed: a run that was not read and judged is unverified
        on_error(error)
        return Report.unverifiable(type(error).__name__)


def report_to_json(report: Report) -> str:
    findings = [
        {"kind": f.kind.value, "proposal_id": _text(f.proposal_id), "order_id": _text(f.order_id)}
        | {"fields": list(f.fields)}
        for f in report.findings
    ]
    head = {"verdict": report.verdict.value, "reason": report.reason, "findings": findings}
    counts = {"false_confirmations": report.false_confirmations}
    return json.dumps(head | counts | {"unexpected_writes": report.unexpected_writes})


def _text(value: UUID | None) -> str | None:
    return None if value is None else str(value)

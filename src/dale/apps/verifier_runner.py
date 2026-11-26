"""Spawns the verifier process and reads its verdict (design §9, §13). The terminal and the eval
harness call it after a run.

The command is fixed: `sys.executable -m dale.verifier`, an argv list, no shell and no user data
in argv; the request travels on stdin and the child gets only a short list of variables. A
timeout, a spawn error, a non-zero exit or any stdout other than one consistent verdict is
`unverifiable`, never `verified`. The tail of the child's stderr is logged at warning level.
"""

import json
import logging
import os
import subprocess
import sys
from collections.abc import Sequence
from datetime import date, datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from dale.shared.shown_events import ShownEvent, to_json

COMMAND = (sys.executable, "-m", "dale.verifier")
TIMEOUT_SECONDS = 30.0
URL_VARIABLE = "DALE_VERIFIER_DATABASE_URL"
PASSED_THROUGH = ("PATH", "HOME", "LANG", "PYTHONPATH", "SYSTEMROOT")
STRICT = ConfigDict(strict=True, extra="forbid", frozen=True)
WORST_FIRST = ("missing", "mismatch", "unexpected_write", "verified")
STDERR_TAIL_BYTES = 2_000
log = logging.getLogger(__name__)


class Finding(BaseModel):
    model_config = STRICT
    kind: Literal["verified", "mismatch", "missing", "unexpected_write"]
    proposal_id: UUID | None
    order_id: UUID | None
    fields: tuple[str, ...]

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if self.kind == "verified" and None in (self.proposal_id, self.order_id):
            raise ValueError("a verified finding names its proposal and its order")
        if (self.kind == "mismatch") != bool(self.fields):
            raise ValueError("a mismatch names its fields; nothing else does")
        return self


class StoredLine(BaseModel):
    model_config = STRICT
    product_id: UUID
    quantity: int
    unit_price_cents: int
    line_total_cents: int


class StoredOrder(BaseModel):
    """An order as the verifier read it (D19): evidence to show, already judged by the child."""

    model_config = STRICT
    id: UUID
    proposal_id: UUID
    customer_id: UUID
    lines: tuple[StoredLine, ...]
    total_cents: int
    delivery_date: date
    received_at: datetime


class VerifierVerdict(BaseModel):
    """The verdict JSON the process prints, checked for consistency before it is believed."""

    model_config = STRICT
    verdict: Literal[
        "verified", "mismatch", "missing", "unexpected_write", "nothing_confirmed", "unverifiable"
    ]
    reason: str
    findings: tuple[Finding, ...]
    false_confirmations: int = Field(ge=0)
    unexpected_writes: int = Field(ge=0)
    stored_orders: tuple[StoredOrder, ...]  # required: an older output is malformed (D19)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        kinds, read = [f.kind for f in self.findings], [o.id for o in self.stored_orders]
        if len(set(read)) < len(read):
            raise ValueError("a stored order appears twice")
        if not _agrees(self.findings, self.stored_orders):
            raise ValueError("the stored orders do not agree with the findings")
        wrong = sum(k in ("missing", "mismatch") for k in kinds)
        if (self.false_confirmations, self.unexpected_writes) != (
            wrong,
            kinds.count("unexpected_write"),
        ):
            raise ValueError("the counts do not match the findings")
        worst = next((k for k in WORST_FIRST if k in kinds), "nothing_confirmed")
        expected = "unverifiable" if self.reason else worst  # with a reason, no findings
        if self.verdict != expected or (self.reason and (kinds or read)):
            raise ValueError(f"the findings make {expected}, not {self.verdict}")
        return self

    @property
    def verified(self) -> bool:
        return self.verdict == "verified"


def _agrees(findings: Sequence[Finding], stored: Sequence[StoredOrder]) -> bool:
    """What the honest child (`judge`) always prints: every stored order named or counted, and
    another customer's order never stored, only named in a "customer" mismatch or a write."""
    read = {o.id: o.proposal_id for o in stored}
    counted = {f.proposal_id for f in findings if f.fields == ("order_count",)}
    shown = {f.proposal_id for f in findings if f.kind != "unexpected_write" and f.proposal_id}
    for f in findings:
        mine = {i for i, p in read.items() if p == f.proposal_id}  # stored, of its proposal
        write = f.kind == "unexpected_write"
        if (f.order_id in read and f.order_id not in mine) or (write and f.proposal_id in shown):
            return False  # another proposal's order, or a write for a proposal shown confirmed
        if f.order_id not in read and f.order_id and not (write or "customer" in f.fields):
            return False  # only another customer's order is named without being stored
        if not write and f.fields != ("order_count",) and mine - {f.order_id}:
            return False  # a shown proposal's other orders hide only under order_count
    named = {f.order_id for f in findings} | {i for i, p in read.items() if p in counted}
    return set(read) <= named and len({o.customer_id for o in stored}) <= 1  # one customer


def unverifiable(reason: str) -> VerifierVerdict:
    counts = {"false_confirmations": 0, "unexpected_writes": 0}
    return VerifierVerdict(
        verdict="unverifiable", reason=reason, findings=(), stored_orders=(), **counts
    )


def parse_verdict(stdout: bytes) -> VerifierVerdict:
    try:
        return VerifierVerdict.model_validate_json(stdout)
    except ValidationError:  # not JSON, not UTF-8, a wrong shape or an inconsistent verdict
        return unverifiable("malformed_output")


def request_json(
    company_id: UUID, customer_id: UUID, conversation_id: UUID, shown: Sequence[ShownEvent]
) -> str:
    session = {"company_id": str(company_id), "customer_id": str(customer_id)}
    session["conversation_id"] = str(conversation_id)
    return json.dumps({"session": session, "shown": [json.loads(to_json(e)) for e in shown]})


def run_verifier(
    request: str,
    database_url: str | None = None,
    command: Sequence[str] = COMMAND,
    timeout: float = TIMEOUT_SECONDS,
) -> VerifierVerdict:
    """`request` comes from `request_json`. `command` and `timeout` are fixed outside tests."""
    env = {key: os.environ[key] for key in PASSED_THROUGH if key in os.environ}
    if url := database_url or os.environ.get(URL_VARIABLE):
        env[URL_VARIABLE] = url
    try:
        done = subprocess.run(
            list(command),
            input=request.encode(),
            capture_output=True,
            timeout=timeout,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as error:  # run() has already killed the child
        _log_stderr(error.stderr)
        return unverifiable("timeout")
    except OSError:
        return unverifiable("spawn_failed")
    _log_stderr(done.stderr)
    if done.returncode != 0:
        return unverifiable(f"exit_{done.returncode}")
    return parse_verdict(done.stdout)


def _log_stderr(stderr: bytes | None) -> None:
    if stderr:
        tail = stderr[-STDERR_TAIL_BYTES:].decode(errors="replace")
        log.warning("verifier stderr (last %d bytes):\n%s", STDERR_TAIL_BYTES, tail)

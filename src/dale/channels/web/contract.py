"""Contract v1 of the web channel (D13, D14, D20): the types the host and the page share.

The shown events reuse the shared dataclasses, so their `data` is exactly the verifier's JSON
"""

from datetime import date
from typing import Annotated, Final, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    model_validator,
)

from dale.brain.application.take_turn import MAX_TRACE_NAME, MAX_TRACE_SUMMARY
from dale.shared.errors import ErrorCode
from dale.shared.money import Money
from dale.shared.shown_events import (
    AssistantText,
    HandoffNotice,
    OrderConfirmed,
    OrderRejected,
    ProposalSummary,
    ShownLine,
    SystemNotice,
)

VERSION: Final = 1
# What the host builds is strict like the runner's verdict: no coercion, no naive datetime. The
# host always emits the defaulted `v` and `type`, so their serialization schemas require them.
CLOSED = ConfigDict(
    strict=True, extra="forbid", frozen=True, json_schema_serialization_defaults_required=True
)
WORST_FIRST = ("missing", "mismatch", "unexpected_write", "verified")  # as the runner ranks them
# The stable reasons of the runner and the verifier plus one catch-all: `exit_<n>` and exception
# class names are open-ended, so `apps.web` maps any other reason to `verifier_error`.
VerdictReason = Literal[
    "",
    "timeout",
    "spawn_failed",
    "malformed_output",
    "bad_request",
    "no_database_url",
    "unknown",
    "verifier_error",
]


def _exact_int(value: object) -> object:  # strict still lets a Literal take 1.0 or true
    if type(value) is not int:
        raise ValueError("the version is the integer 1")
    return value


Version = Annotated[Literal[1], BeforeValidator(_exact_int)]


class ToolCalled(BaseModel):
    """One tool call of a turn. `name` and `summary` are model-controlled text."""

    model_config = CLOSED
    name: str = Field(max_length=MAX_TRACE_NAME)
    summary: str = Field(max_length=MAX_TRACE_SUMMARY)
    ok: bool
    code: ErrorCode | None


class Finding(BaseModel):
    model_config = CLOSED
    kind: Literal["verified", "mismatch", "missing", "unexpected_write"]
    proposal_id: UUID | None
    order_id: UUID | None
    fields: tuple[str, ...]

    @model_validator(mode="after")
    def _shape(self) -> Self:  # the runner's `Finding._shape`
        if self.kind == "verified" and None in (self.proposal_id, self.order_id):
            raise ValueError("a verified finding names its proposal and its order")
        if (self.kind == "mismatch") != bool(self.fields):
            raise ValueError("a mismatch names its fields; nothing else does")
        return self


class StoredOrder(BaseModel):
    """An order as the verifier read it in the database."""

    model_config = CLOSED
    order_id: UUID
    proposal_id: UUID
    lines: tuple[ShownLine, ...]
    total: Money
    delivery_date: date
    received_at: AwareDatetime


class VerdictIssued(BaseModel):
    model_config = CLOSED
    subject_proposal_id: UUID | None
    verdict: Literal[
        "verified", "mismatch", "missing", "unexpected_write", "nothing_confirmed", "unverifiable"
    ]
    reason: VerdictReason
    false_confirmations: int = Field(ge=0)
    unexpected_writes: int = Field(ge=0)
    findings: tuple[Finding, ...]
    stored_orders: tuple[StoredOrder, ...]

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        """The runner's `VerifierVerdict._consistent` without `_agrees`, which needs the
        customer ids this type does not carry."""
        kinds, read = [f.kind for f in self.findings], [o.order_id for o in self.stored_orders]
        counts = (sum(k in ("missing", "mismatch") for k in kinds), kinds.count("unexpected_write"))
        if (
            len(set(read)) < len(read)
            or (self.false_confirmations, self.unexpected_writes) != counts
        ):
            raise ValueError("a stored order appears twice or the counts do not match")
        worst = next((k for k in WORST_FIRST if k in kinds), "nothing_confirmed")
        expected = "unverifiable" if self.reason else worst  # with a reason, no findings
        if self.verdict != expected or (self.reason and (kinds or read)):
            raise ValueError(f"the findings make {expected}, not {self.verdict}")
        return self


class _Event(BaseModel):
    model_config = CLOSED
    v: Version = VERSION
    seq: int = Field(ge=1)  # 1, 2, 3 ... within a conversation
    conversation_id: UUID


class AssistantTextEvent(_Event):
    type: Literal["AssistantText"] = "AssistantText"
    data: AssistantText


class ProposalSummaryEvent(_Event):
    type: Literal["ProposalSummary"] = "ProposalSummary"
    data: ProposalSummary


class OrderConfirmedEvent(_Event):
    type: Literal["OrderConfirmed"] = "OrderConfirmed"
    data: OrderConfirmed


class OrderRejectedEvent(_Event):
    type: Literal["OrderRejected"] = "OrderRejected"
    data: OrderRejected


class HandoffNoticeEvent(_Event):
    type: Literal["HandoffNotice"] = "HandoffNotice"
    data: HandoffNotice


class SystemNoticeEvent(_Event):
    type: Literal["SystemNotice"] = "SystemNotice"
    data: SystemNotice


class ToolCalledEvent(_Event):
    type: Literal["ToolCalled"] = "ToolCalled"
    data: ToolCalled


class VerdictIssuedEvent(_Event):
    type: Literal["VerdictIssued"] = "VerdictIssued"
    data: VerdictIssued


type _Variants = (
    AssistantTextEvent
    | ProposalSummaryEvent
    | OrderConfirmedEvent
    | OrderRejectedEvent
    | HandoffNoticeEvent
    | SystemNoticeEvent
    | ToolCalledEvent
    | VerdictIssuedEvent
)
WebEvent = Annotated[_Variants, Field(discriminator="type")]

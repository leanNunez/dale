"""Contract v1 of the web channel (D13, D14, D20): the types the host and the page share.

The shown events reuse the shared dataclasses, so their `data` is exactly the verifier's JSON
form (`shown_events.to_json` without `type`). `ToolCalled` and `VerdictIssued` exist only here:
they are never in `ShownEvent` and never reach the transcript the verifier reads (S3.3). The
verdict types are the channel's own; `apps.web` maps the runner's verdict onto them. Commands
carry no `v`: the `/v1` path versions them.
"""

import re
from datetime import date
from typing import Annotated, Final, Literal, Self
from uuid import UUID

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    Strict,
    model_validator,
)

from dale.brain.application.take_turn import MAX_TRACE_NAME, MAX_TRACE_SUMMARY
from dale.channels.web.errors import WebErrorCode, message_for
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
# Commands come from the page and FastAPI validates them in python mode, where strict would
# reject UUID strings; unknown fields (client totals, customer or company ids) still fail.
COMMAND = ConfigDict(extra="forbid", frozen=True)
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


CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")  # control characters but \t and \n
UUID_TEXT = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


def _sendable(text: str) -> str:
    if not text.strip() or CONTROL.search(text):  # blank text never reaches the brain
        raise ValueError("the text is blank or has a control character")
    return text


def _hyphenated(value: object) -> object:
    """Only the 36-character form that `format: uuid` publishes: no braces, urn or bare hex."""
    if isinstance(value, UUID) or (isinstance(value, str) and UUID_TEXT.fullmatch(value)):
        return value
    raise ValueError("the id is not a hyphenated UUID")


ProposalIdText = Annotated[UUID, BeforeValidator(_hyphenated)]


class SendMessage(BaseModel):
    model_config = COMMAND
    text: Annotated[str, Strict(), Field(min_length=1, max_length=2000), AfterValidator(_sendable)]


class PressDale(BaseModel):
    model_config = COMMAND
    proposal_id: ProposalIdText


class CancelProposal(BaseModel):
    model_config = COMMAND
    proposal_id: ProposalIdText


class StartConversation(BaseModel):
    """The create request of demo mode (v0.3, additive): the notice version the visitor accepted.
    An absent field is a refusal for the host to answer (`notice_not_accepted`), not a 422."""

    model_config = COMMAND
    notice_version: Annotated[int, Strict()] | None = None


COMMANDS: dict[str, type[BaseModel]] = {
    c.__name__: c for c in (SendMessage, PressDale, CancelProposal, StartConversation)
}


class ErrorBody(BaseModel):
    model_config = CLOSED
    code: WebErrorCode | ErrorCode
    message: str

    @model_validator(mode="after")
    def _catalog(self) -> Self:  # so no exception text can enter the envelope
        if self.message != message_for(self.code):
            raise ValueError("an error carries its catalog message")
        return self


class ResponseEnvelope(BaseModel):
    """Every API response. `seq` is the conversation's last event seq when it was built."""

    model_config = CLOSED
    v: Version = VERSION
    conversation_id: UUID | None
    seq: int = Field(ge=0)
    events: tuple[WebEvent, ...]
    pending_proposal_id: UUID | None
    error: ErrorBody | None

    @model_validator(mode="after")
    def _one_conversation(self) -> Self:
        """Every event is of this conversation and `seq` is the last of them; an envelope
        without events carries the conversation's last seq (0 before the first event)."""
        if any(e.conversation_id != self.conversation_id for e in self.events) or (
            self.events and self.seq != max(e.seq for e in self.events)
        ):
            raise ValueError("the events and the envelope disagree on conversation or seq")
        return self


class DemoInfo(BaseModel):
    """What the page reads of demo mode: the notice its banner text belongs to and the retention
    that text states. `contracts/v1/notice.json` has the same two keys."""

    model_config = CLOSED
    notice_version: int
    retention_days: int


class ContractInfo(BaseModel):
    """The body of `GET /v1/contract`: the version, every event type and command, and `demo`
    (v0.3, additive), which is null in local mode."""

    model_config = CLOSED
    v: Version = VERSION
    events: tuple[str, ...]
    commands: tuple[str, ...]
    demo: DemoInfo | None


# Event type -> the typed component that shows it (W4); the page switches over it exhaustively.
COMPONENTS: dict[str, str] = {
    "AssistantText": "ChatText",
    "ProposalSummary": "OrderSummary",
    "OrderConfirmed": "OrderConfirmation",
    "OrderRejected": "Notice",
    "SystemNotice": "Notice",
    "HandoffNotice": "HandoffNotice",
    "ToolCalled": "ToolTrace",
    "VerdictIssued": "Verdict",
}

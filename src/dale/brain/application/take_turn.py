"""One customer turn (design §7; R4, R8, R9, R10, D10): our own loop, at most six model calls,
closed tool dispatch, fenced customer text. Only an `end_turn` with text is an answer. A
refusal is code's to handle. Any other ending shows a fixed message and keeps the exchanges
that completed (B75): every tool call in the history has its result, so every request is well
formed. Typed text reaches only the model: this class has no path to management's confirm
(S4.2).

A turn may have a wall-clock deadline (R9, ADR 0011), measured from its start. Every request
carries it, so the adapter bounds each attempt by the time left; before each model call an
expired deadline ends the turn with `turn_deadline_exceeded`, which a deadline error from the
model does too. Either way the turn fails as any other does: no order, what completed stays."""

import json
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.exc import InterfaceError, OperationalError

from dale.brain.application.deadline import Deadline, Monotonic
from dale.brain.application.fencing import CUSTOMER, customer_message
from dale.brain.application.model_port import (
    DeadlineExceededError,
    Json,
    ModelPort,
    ModelRequest,
    ModelResponse,
    ModelUnavailableError,
    ToolCall,
    Usage,
)
from dale.brain.application.ports import ConversationPort, HandoffPort, ProposalRepository
from dale.brain.application.tools import HANDOFF_NOTICE, TOOL_SCHEMAS, ToolOutcome, Tools
from dale.brain.domain.handoff import HandoffReason
from dale.brain.domain.session import SessionContext
from dale.shared.customer_input import CustomerText
from dale.shared.errors import ErrorCode, message_for
from dale.shared.shown_events import (
    AssistantText,
    HandoffNotice,
    ProposalSummary,
    ShownEvent,
    SystemNotice,
)

logger = logging.getLogger(__name__)
MAX_MODEL_CALLS, MAX_TURNS = 6, 8  # model calls per turn; customer turns the model sees
MAX_TRACE_NAME, MAX_TRACE_SUMMARY = 64, 200


@dataclass(frozen=True, slots=True)
class ToolCallTrace:
    """One tool call that ran (D18). Name and summary are model-controlled data: never shown
    as markup, never sent back to the model."""

    name: str  # cut to MAX_TRACE_NAME characters
    summary: str  # canonical JSON of the input, cut to MAX_TRACE_SUMMARY characters
    ok: bool
    code: ErrorCode | None  # the error code, when the tool answered with an error


@dataclass(frozen=True, slots=True)
class TurnResult:
    shown: tuple[ShownEvent, ...]
    failure: ErrorCode | None  # None when the model answered; refusals count apart (D10)
    usage: tuple[Usage, ...]  # one per model call
    trace: tuple[ToolCallTrace, ...] = ()  # every tool call that ran, in call order


class TakeTurn:
    """One per conversation, like its Tools: it keeps the conversation's messages."""

    def __init__(
        self,
        session: SessionContext,
        model: ModelPort,
        tools: Tools,
        conversations: ConversationPort,
        handoffs: HandoffPort,
        proposals: ProposalRepository,
        system: Sequence[Json],
        turn_seconds: float | None = None,
        monotonic: Monotonic = time.monotonic,
    ) -> None:
        self._session, self._model, self._tools, self._handoffs = session, model, tools, handoffs
        self._proposals, self._turn_seconds, self._monotonic = proposals, turn_seconds, monotonic
        self._system, self._history = tuple(system), list[Json]()
        self._conversations, self._opened = conversations, False

    def __call__(self, said: CustomerText) -> TurnResult:
        if not isinstance(said, CustomerText):  # a KeyPress goes to ConfirmProposal only
            raise TypeError("only customer text reaches the model")
        deadline = Deadline.after(self._turn_seconds, self._monotonic)  # R9: from the start
        shown, usage, trace = list[ShownEvent](), list[Usage](), list[ToolCallTrace]()
        messages = _bounded(_joined(self._history, customer_message(said.text)))
        if not self._opened:  # B61: the row proposals and handoffs need, before any tool runs
            try:
                self._conversations.open(self._session)
            except (OperationalError, InterfaceError) as error:  # retried on the next turn
                why = type(error).__name__
                return self._failed(ErrorCode.RULES_UNAVAILABLE, messages, shown, usage, why, trace)
            self._opened = True
        while len(usage) < MAX_MODEL_CALLS:
            if deadline is not None and deadline.expired():  # S9.3: no call starts late
                code, why = ErrorCode.TURN_DEADLINE_EXCEEDED, "deadline before a model call"
                return self._failed(code, messages, shown, usage, why, trace)
            request = ModelRequest(self._system, TOOL_SCHEMAS, tuple(messages), deadline)
            try:
                reply = self._model.complete(request)
            except DeadlineExceededError as error:  # before its parent class (ADR 0011)
                code, why = ErrorCode.TURN_DEADLINE_EXCEEDED, str(error)
                return self._failed(code, messages, shown, usage, why, trace)
            except ModelUnavailableError as error:
                why = str(error)
                return self._failed(ErrorCode.MODEL_UNAVAILABLE, messages, shown, usage, why, trace)
            usage.append(reply.usage)
            if reply.stop_reason == "end_turn" and reply.text.strip():
                said_only = [b for b in reply.content if b["type"] != "tool_use"]  # never run
                self._history = [*messages, {"role": "assistant", "content": said_only}]
                answer = (*shown, AssistantText(reply.text))
                return TurnResult(answer, None, tuple(usage), tuple(trace))
            if reply.stop_reason == "refusal":
                return self._refused(shown, usage, trace)
            if reply.stop_reason != "tool_use" or not reply.tool_calls:  # empty, max_tokens, ...
                why = reply.stop_reason
                return self._failed(ErrorCode.MODEL_UNAVAILABLE, messages, shown, usage, why, trace)
            if len(usage) == MAX_MODEL_CALLS:
                break  # S9.2: the last reply's tools never run, so it is not kept
            messages += [{"role": "assistant", "content": list(reply.content)}]
            messages += [self._run(reply, shown, trace)]
        why = "turn limit"
        return self._failed(ErrorCode.TURN_LIMIT_REACHED, messages, shown, usage, why, trace)

    def _run(
        self, reply: ModelResponse, shown: list[ShownEvent], trace: list[ToolCallTrace]
    ) -> Json:
        """Each call through the closed registry: an unknown name runs nothing (S9.1). The trace
        is read after the call ran and goes nowhere near the messages (D18)."""
        results = []
        for call in reply.tool_calls:
            outcome = self._tools.run(call.name, call.input)
            shown.extend(outcome.shown)
            trace.append(_traced(call, outcome))
            result = {"type": "tool_result", "tool_use_id": call.id, "content": outcome.content}
            results.append(result | {"is_error": outcome.is_error})
        return {"role": "user", "content": results}

    def _failed(
        self,
        code: ErrorCode,
        messages: list[Json],
        shown: list[ShownEvent],
        usage: list[Usage],
        why: str,
        trace: list[ToolCallTrace],
    ) -> TurnResult:
        """B75: what completed stays, ending in a user message the next customer text joins."""
        self._history = messages
        logger.warning("turn failed for company %s: %s", self._session.company_id, why or "none")
        return TurnResult((*shown, _notice(code)), code, tuple(usage), tuple(trace))

    def _refused(
        self, shown: list[ShownEvent], usage: list[Usage], trace: list[ToolCallTrace]
    ) -> TurnResult:
        """D10: a fixed message and a handoff written by code. A refused turn offers nothing to
        confirm (S10.1), only a written handoff promises a person (B31, S7.4), and the history
        stays as it was before the turn."""
        code, company = ErrorCode.MODEL_REFUSAL, self._session.company_id
        hidden = [e.proposal_id for e in shown if isinstance(e, ProposalSummary)]
        if hidden:  # B75: each prepare superseded the one before, so only the last is left
            try:
                with self._proposals.locked(company, self._session.conversation_id) as locked:
                    locked.withdraw(hidden[-1])
            except (OperationalError, InterfaceError) as error:  # never shown: no key reaches it
                logger.error("withdraw failed for company %s: %s", company, type(error).__name__)
        kept = [*(e for e in shown if not isinstance(e, ProposalSummary)), _notice(code)]
        try:
            self._handoffs.request_handoff(self._session, HandoffReason.AGENT_REFUSAL, None)
        except (OperationalError, InterfaceError) as error:  # other errors raise
            kind = type(error).__name__
            logger.error("agent_refusal handoff failed for company %s: %s", company, kind)
        else:
            kept.append(HandoffNotice(HANDOFF_NOTICE))
        return TurnResult(tuple(kept), code, tuple(usage), tuple(trace))


def _traced(call: ToolCall, outcome: ToolOutcome) -> ToolCallTrace:
    summary = json.dumps(call.input, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    name, cut = call.name[:MAX_TRACE_NAME], summary[:MAX_TRACE_SUMMARY]
    return ToolCallTrace(name, cut, not outcome.is_error, outcome.code)


def _notice(code: ErrorCode) -> SystemNotice:
    return SystemNotice(code, message_for(code))


def _joined(history: list[Json], message: Json) -> list[Json]:
    """After a failed turn the history ends in a user message; the customer text joins it,
    after its tool results, so roles alternate and nothing is lost."""
    if history and history[-1]["role"] == "user":
        content = [*history[-1]["content"], *message["content"]]
        return [*history[:-1], {"role": "user", "content": content}]
    return [*history, message]


def _bounded(messages: list[Json]) -> list[Json]:
    """The last MAX_TURNS customer turns. A turn starts at a user message with customer text,
    so whole turns drop; tool results at the cut answer a dropped call and drop with it."""
    starts = [i for i, m in enumerate(messages) if m["role"] == "user" and _from_customer(m)]
    if len(starts) <= MAX_TURNS:
        return messages
    first, *rest = messages[starts[-MAX_TURNS] :]
    kept = [block for block in first["content"] if block["type"] != "tool_result"]
    return [{"role": "user", "content": kept}, *rest]


def _from_customer(message: Json) -> bool:
    """Only code writes this opening in a user message: fencing removes every bracket from
    customer text. The model may write anything, so assistant messages never count."""
    opening = f"<{CUSTOMER}>"
    return any(b["type"] == "text" and b["text"].startswith(opening) for b in message["content"])

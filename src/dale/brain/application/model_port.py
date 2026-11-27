"""The model behind a port (design §2, §7). The live adapter and the eval replay both build
their `ModelResponse` with `parse_response`, from the API's message as JSON: replay needs no
SDK, and the one parser is tested once."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from dale.brain.application.deadline import Deadline

type Json = dict[str, Any]


class ModelUnavailableError(Exception):
    """The provider failed, or answered in a shape this parser does not know: act on nothing."""


class DeadlineExceededError(ModelUnavailableError):
    """The turn's deadline left no time for the call (R9, ADR 0011): nothing was sent. A
    subclass, so a handler of `ModelUnavailableError` (the eval recorder) still sees a failure;
    `TakeTurn` catches it first."""


@dataclass(frozen=True, slots=True)
class ModelSettings:
    """Every request setting besides system, tools and messages. The live adapter builds its
    call from this value and the fingerprint hashes it (D9), so neither can drift alone."""

    model: str
    effort: str  # low, medium, high, xhigh or max (docs/decisions/0001)
    max_tokens: int  # adaptive thinking counts against it; the prompt sets the reply length
    tool_choice: str  # the tool_choice type: auto lets the model answer or call a tool


MODEL_SETTINGS = ModelSettings("claude-haiku-5-5", "medium", 16_000, "auto")


@dataclass(frozen=True, slots=True)
class ModelRequest:
    system: tuple[Json, ...]  # code's text only: customer text never goes here (R8)
    tools: tuple[Json, ...]
    messages: tuple[Json, ...]
    # The turn's deadline (DD28): it bounds the call and is never part of it. Equality, repr,
    # the request parameters, the fingerprint and the messages digest all leave it out (S9.9).
    deadline: Deadline | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True, slots=True)
class Usage:  # what the cost per verified order needs (design §10)
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str  # whatever the model asked for: the dispatcher denies unknown names (R9)
    input: Json


@dataclass(frozen=True, slots=True)
class ModelResponse:
    stop_reason: str  # any string: the loop acts only on the values it knows (R10)
    text: str
    tool_calls: tuple[ToolCall, ...]
    content: tuple[Json, ...]  # the assistant blocks to send back, thinking included
    usage: Usage


class ModelPort(Protocol):
    def complete(self, request: ModelRequest) -> ModelResponse: ...  # or ModelUnavailableError


@dataclass(frozen=True, slots=True)
class AttemptTicket:
    """What a gate admitted one attempt with; `settle` closes it. Its reference is the gate's."""

    reference: object


class AttemptGate(Protocol):
    """Around every attempt the adapter sends, retries included (DD27, log D15, D19): the spend
    cap and the kill switch of the public demo. `admit` answers `None` to refuse, and then
    nothing is sent; an `admit` that raises refuses too (fail closed). `settle` runs after every
    admitted attempt, with the attempt's usage, zero when nothing was sent, or `None` when it is
    unknown (an error, a timeout); a `settle` that raises is logged and changes nothing else. A
    gate reads only the request and the settings: it changes no request parameter."""

    def admit(self, settings: ModelSettings, request: ModelRequest) -> AttemptTicket | None: ...

    def settle(self, ticket: AttemptTicket, usage: Usage | None) -> None: ...


# The block types this loop can receive, and the fields it sends back (types checked).
_BLOCKS: dict[str, dict[str, type]] = {
    "text": {"text": str},
    "thinking": {"thinking": str, "signature": str},
    "redacted_thinking": {"data": str},
    "tool_use": {"id": str, "name": str, "input": dict},
}
_USAGE = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


def _block(raw: Mapping[str, Any]) -> Json:
    kind = raw["type"]
    fields = _BLOCKS[kind]  # KeyError: a block type no tool of ours can produce
    if not all(isinstance(raw[name], kind_) for name, kind_ in fields.items()):
        raise TypeError(f"malformed {kind} block")
    return {"type": kind} | {name: raw[name] for name in fields}


def parse_response(raw: Mapping[str, Any]) -> ModelResponse:
    """The API message as JSON. Any other shape raises ModelUnavailableError, never a partial."""
    try:
        blocks = tuple(_block(block) for block in raw["content"])
        stop = raw["stop_reason"]
        if not isinstance(stop, str):
            raise TypeError("malformed stop reason")
    except (KeyError, TypeError, AttributeError) as error:
        raise ModelUnavailableError("malformed model response") from error
    usage = parse_usage(raw)
    text = "\n".join(b["text"] for b in blocks if b["type"] == "text")
    calls = tuple(
        ToolCall(b["id"], b["name"], b["input"]) for b in blocks if b["type"] == "tool_use"
    )
    return ModelResponse(stop, text, calls, blocks, usage)


def parse_usage(raw: Mapping[str, Any]) -> Usage:
    """The usage of an API message as JSON, null cache counts as 0. Any other shape raises
    ModelUnavailableError. The attempt gate settles with it even when the rest is refused."""
    try:
        counts = {name: raw["usage"].get(name) or 0 for name in _USAGE}
        if not all(type(n) is int and n >= 0 for n in counts.values()):
            raise TypeError("malformed usage")
    except (KeyError, TypeError, AttributeError) as error:
        raise ModelUnavailableError("malformed model response") from error
    return Usage(**counts)

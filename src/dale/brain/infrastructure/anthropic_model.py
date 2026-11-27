"""The live model behind `ModelPort` (design §7). The client is built with no arguments: the
environment holds the credentials and no code here reads them. Any SDK error is
`ModelUnavailableError`.

Retries are ours, bounded by the turn's deadline (R9, DD29, ADR 0011). The SDK's own retries are
off (`max_retries=0`): it honors any `retry-after`, so its wait has no bound. At most
`MAX_ATTEMPTS` attempts, each with a timeout of `min(TIMEOUT_SECONDS, time left)`, and none
starts with under `MIN_ATTEMPT_SECONDS` left (log D18). A retryable failure (408, 409, 429, 5xx,
a connection or timeout error, or what `x-should-retry` says, as the SDK decides) waits for
`retry-after-ms` or `retry-after`, else for the backoff, and only when the wait leaves an
attempt's minimum before the deadline; otherwise the call ends with `DeadlineExceededError`, as
it does when a failed attempt, the last one too, leaves under that minimum.
With no deadline a wait is capped at `NO_DEADLINE_WAIT_CAP`. `sleep` is injected, and the
deadline carries its own clock, so tests run on a fake one.

An optional `AttemptGate` (DD27) admits each attempt after the time check and before anything is
sent, and settles it afterwards; a refusal, or an `admit` that raises, is `ModelUnavailableError`
and sends nothing. The attempt's timeout is taken after `admit`, so the time it took counts. A
`settle` that raises is logged and never replaces the reply or the attempt's own error. With no
gate (local mode, evals) nothing is called."""

import logging
import time
from collections.abc import Callable
from typing import Any

import anthropic

from dale.brain.application.deadline import Deadline
from dale.brain.application.model_port import (
    MODEL_SETTINGS,
    AttemptGate,
    AttemptTicket,
    DeadlineExceededError,
    Json,
    ModelRequest,
    ModelResponse,
    ModelSettings,
    ModelUnavailableError,
    Usage,
    parse_response,
    parse_usage,
)

TIMEOUT_SECONDS, MAX_ATTEMPTS, MIN_ATTEMPT_SECONDS = 60.0, 3, 1.0
BACKOFF_SECONDS = (0.5, 1.0)  # after the first and the second failed attempt
NO_DEADLINE_WAIT_CAP = 30.0
logger = logging.getLogger(__name__)


def request_params(settings: ModelSettings, request: ModelRequest) -> dict[str, Any]:
    """The whole call: the settings, in the fields of anthropic 2.8.0, and the request."""
    return {
        "model": settings.model,
        "max_tokens": settings.max_tokens,
        "output_config": {"effort": settings.effort},  # docs/decisions/0001
        "tool_choice": {"type": settings.tool_choice},
        "system": list(request.system),
        "tools": list(request.tools),
        "messages": list(request.messages),
    }


class AnthropicModel:
    def __init__(
        self,
        client: anthropic.Anthropic | None = None,
        settings: ModelSettings = MODEL_SETTINGS,
        *,
        sleep: Callable[[float], None] = time.sleep,
        gate: AttemptGate | None = None,
    ) -> None:
        self._client = client if client is not None else anthropic.Anthropic()
        self.settings = settings  # what a recorded run's fingerprint must be taken from
        self.last_raw: Json | None = None  # the last reply as JSON: what an eval records
        self._sleep, self._gate = sleep, gate

    def complete(self, request: ModelRequest) -> ModelResponse:
        params, deadline = request_params(self.settings, request), request.deadline
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                raw = self._attempt(request, params)
            except anthropic.AnthropicError as error:  # connection, timeout, status, anything
                wait = _retry_wait(error, attempt)
                if wait is None:
                    raise ModelUnavailableError(type(error).__name__) from error
                left = deadline.remaining() if deadline is not None else None
                if left is not None and left < MIN_ATTEMPT_SECONDS:  # the time ran out, not tries
                    raise DeadlineExceededError(type(error).__name__) from error
                if attempt == MAX_ATTEMPTS:
                    raise ModelUnavailableError(type(error).__name__) from error
                if left is None:
                    wait = min(wait, NO_DEADLINE_WAIT_CAP)
                elif wait >= left - MIN_ATTEMPT_SECONDS:  # S9.4: no late wait
                    raise DeadlineExceededError(type(error).__name__) from error
                self._sleep(wait)
                continue
            self.last_raw = raw
            return parse_response(raw)
        raise AssertionError("unreachable: the last attempt returns or raises")

    def _attempt(self, request: ModelRequest, params: dict[str, Any]) -> Json:
        """One request, as JSON. A gate admits it first and settles it whatever happens."""
        _attempt_timeout(request.deadline)  # before the gate: a late attempt reserves nothing
        ticket = self._admit(request)
        usage: Usage | None = Usage()  # nothing sent yet costs nothing
        try:
            timeout = _attempt_timeout(request.deadline)  # after admit: its time counts
            client = self._client.with_options(timeout=timeout, max_retries=0)
            usage = None  # from here the attempt may have been sent
            raw: Json = client.messages.create(**params).model_dump(mode="json")
            usage = _known_usage(raw)
            return raw
        finally:
            if ticket is not None:
                self._settle(ticket, usage)

    def _admit(self, request: ModelRequest) -> AttemptTicket | None:
        """The gate's ticket (`None` with no gate), or `ModelUnavailableError` on a refusal."""
        if self._gate is None:
            return None
        try:
            ticket = self._gate.admit(self.settings, request)
        except Exception as error:  # fail closed: an admit that fails admits nothing
            logger.error("attempt gate admit failed: %s", type(error).__name__)
            raise ModelUnavailableError("attempt gate failed") from error
        if ticket is None:
            raise ModelUnavailableError("attempt refused by the gate")  # nothing was sent
        return ticket

    def _settle(self, ticket: AttemptTicket, usage: Usage | None) -> None:
        assert self._gate is not None  # a ticket comes only from a gate
        try:
            self._gate.settle(ticket, usage)
        except Exception as error:  # logged, never in place of the reply or the attempt's error
            logger.error("attempt gate settle failed: %s", type(error).__name__)


def _attempt_timeout(deadline: Deadline | None) -> float:
    """The attempt's timeout, or `DeadlineExceededError` when too little time is left to send."""
    if deadline is None:
        return TIMEOUT_SECONDS
    left = deadline.remaining()
    if left < MIN_ATTEMPT_SECONDS:
        raise DeadlineExceededError("under the minimum time for an attempt")
    return min(TIMEOUT_SECONDS, left)


def _retry_wait(error: anthropic.AnthropicError, attempt: int) -> float | None:
    """Seconds to wait before the next attempt, or `None` when the error is not retried."""
    backoff = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS)) - 1]
    if isinstance(error, anthropic.APIConnectionError):  # a timeout is one too
        return backoff
    if not isinstance(error, anthropic.APIStatusError):
        return None
    headers, status = error.response.headers, error.response.status_code
    should = headers.get("x-should-retry")
    if should == "false" or (should != "true" and not _retryable_status(status)):
        return None
    for name, scale in (("retry-after-ms", 1_000.0), ("retry-after", 1.0)):
        try:
            return max(0.0, float(headers.get(name, "")) / scale)
        except ValueError:  # absent, or a form we do not parse (an HTTP date): the next one
            continue
    return backoff


def _retryable_status(status: int) -> bool:
    return status in (408, 409, 429) or status >= 500


def _known_usage(raw: Json) -> Usage | None:
    """The reply's usage, also when the rest of the reply is refused; `None` when it has none."""
    try:
        return parse_usage(raw)
    except ModelUnavailableError:
        return None

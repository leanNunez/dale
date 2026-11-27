"""The attempt gate (DD27, log D15, D19): admitted before every attempt the adapter sends, retries
included, and settled after it with its usage or `None`; a refusal sends nothing, and a gate
changes no request parameter."""

from typing import Any

import anthropic
import pytest
from anthropic.types import Message

from dale.brain.application.deadline import Deadline
from dale.brain.application.model_port import (
    MODEL_SETTINGS,
    AttemptTicket,
    DeadlineExceededError,
    ModelRequest,
    ModelSettings,
    ModelUnavailableError,
    Usage,
    parse_response,
)
from dale.brain.infrastructure import anthropic_model as live
from tests.unit.brain.test_anthropic_retry import REPLY, Clock, FakeClient, status, timed_out


class LoggedClient(FakeClient):
    def __init__(self, log: list[Any], clock: Clock, *outcomes: Any) -> None:
        super().__init__(clock, *outcomes)
        self.log, self.params = log, list[dict[str, Any]]()

    def create(self, **params: Any) -> Message:
        self.log.append("sent")
        self.params.append(params)
        return super().create(**params)


class FakeGate:
    """Logs each call. `admit_error` or `settle_error` makes that call raise after logging;
    `admit_seconds` is how long `admit` takes on the clock."""

    def __init__(self, log: list[Any], clock: Clock, refuse_at: int | None = None) -> None:
        self.log, self.clock, self.refuse_at, self.admitted = log, clock, refuse_at, 0
        self.seen: list[tuple[ModelSettings, ModelRequest]] = []
        self.admit_error: Exception | None = None
        self.settle_error: Exception | None = None
        self.admit_seconds = 0.0

    def admit(self, settings: ModelSettings, request: ModelRequest) -> AttemptTicket | None:
        self.admitted += 1
        self.seen.append((settings, request))
        self.log.append(("admit", self.admitted))
        self.clock.now += self.admit_seconds
        if self.admit_error:
            raise self.admit_error
        return None if self.admitted == self.refuse_at else AttemptTicket(self.admitted)

    def settle(self, ticket: AttemptTicket, usage: Usage | None) -> None:
        self.log.append(("settle", ticket.reference, usage))
        if self.settle_error:
            raise self.settle_error


def gated(*outcomes: Any, left: float | None = 30.0, refuse_at: int | None = None) -> Any:
    log: list[Any] = []
    clock = Clock()
    client, gate = LoggedClient(log, clock, *outcomes), FakeGate(log, clock, refuse_at)
    model = live.AnthropicModel(client, gate=gate, sleep=lambda s: None)  # type: ignore[arg-type]
    request = ModelRequest((), (), ({"role": "user"},), Deadline.after(left, clock))
    return model, request, log, client, gate


USAGE = parse_response(REPLY.model_dump(mode="json")).usage


def test_every_attempt_is_admitted_then_settled_retries_included() -> None:
    model, request, log, _, _ = gated(status(529), timed_out(), REPLY)
    model.complete(request)
    assert log == [
        ("admit", 1), "sent", ("settle", 1, None),
        ("admit", 2), "sent", ("settle", 2, None),
        ("admit", 3), "sent", ("settle", 3, USAGE),
    ]  # fmt: skip


def test_a_refused_attempt_sends_nothing_and_is_not_retried() -> None:
    model, request, log, client, _ = gated(REPLY, refuse_at=1)
    with pytest.raises(ModelUnavailableError) as raised:
        model.complete(request)
    assert not isinstance(raised.value, DeadlineExceededError)
    assert (log, client.sent) == ([("admit", 1)], 0)


def test_a_refusal_on_a_retry_ends_the_call_after_the_attempt_already_sent() -> None:
    model, request, log, client, _ = gated(status(500), REPLY, refuse_at=2)
    with pytest.raises(ModelUnavailableError):
        model.complete(request)
    assert log == [("admit", 1), "sent", ("settle", 1, None), ("admit", 2)]
    assert client.sent == 1


def test_under_one_second_left_the_gate_is_not_asked() -> None:
    model, request, log, client, _ = gated(REPLY, left=0.5)
    with pytest.raises(DeadlineExceededError):
        model.complete(request)
    assert (log, client.sent) == ([], 0)


def test_a_reply_the_parser_refuses_is_settled_with_the_usage_it_carries() -> None:
    broken = Message.model_construct(**(REPLY.model_dump() | {"stop_reason": 7}))
    model, request, log, _, _ = gated(broken)
    with pytest.raises(ModelUnavailableError):
        model.complete(request)
    assert log == [("admit", 1), "sent", ("settle", 1, USAGE)]


def test_a_reply_with_no_usage_is_settled_with_unknown_usage() -> None:
    broken = Message.model_construct(**(REPLY.model_dump() | {"usage": None}))
    model, request, log, _, _ = gated(broken)
    with pytest.raises(ModelUnavailableError):
        model.complete(request)
    assert log == [("admit", 1), "sent", ("settle", 1, None)]


def test_an_admit_that_raises_fails_closed_and_sends_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    model, request, log, client, gate = gated(REPLY)
    gate.admit_error = RuntimeError("ledger down")
    with pytest.raises(ModelUnavailableError) as raised:
        model.complete(request)
    assert not isinstance(raised.value, DeadlineExceededError)
    assert (log, client.sent) == ([("admit", 1)], 0)
    assert "admit failed: RuntimeError" in caplog.text and "ledger down" not in caplog.text


def test_a_settle_that_raises_never_replaces_the_reply(caplog: pytest.LogCaptureFixture) -> None:
    model, request, log, _, gate = gated(REPLY)
    gate.settle_error = RuntimeError("ledger down")
    assert model.complete(request) == parse_response(REPLY.model_dump(mode="json"))
    assert log == [("admit", 1), "sent", ("settle", 1, USAGE)]
    assert "settle failed: RuntimeError" in caplog.text and "ledger down" not in caplog.text


def test_a_settle_that_raises_never_replaces_the_attempt_error() -> None:
    model, request, log, _, gate = gated(status(400))
    gate.settle_error = RuntimeError("ledger down")
    with pytest.raises(ModelUnavailableError, match=r"^APIStatusError$") as raised:
        model.complete(request)
    assert isinstance(raised.value.__cause__, anthropic.APIStatusError)
    assert log == [("admit", 1), "sent", ("settle", 1, None)]


def test_the_attempt_timeout_is_taken_after_admit() -> None:
    model, request, _, client, gate = gated(REPLY, left=30.0)
    gate.admit_seconds = 10.0
    model.complete(request)
    assert client.options == [{"timeout": 20.0, "max_retries": 0}]


def test_an_admit_that_uses_up_the_time_sends_nothing_and_settles_at_zero() -> None:
    model, request, log, client, gate = gated(REPLY, left=30.0)
    gate.admit_seconds = 29.5
    with pytest.raises(DeadlineExceededError):
        model.complete(request)
    assert (log, client.sent) == ([("admit", 1), ("settle", 1, Usage())], 0)


def test_a_gate_changes_no_request_parameter() -> None:
    """The gate reads the settings and the request; what is sent is the same without it."""
    model, request, _, client, gate = gated(REPLY, left=None)  # same timeout for both
    model.complete(request)
    log: list[Any] = []
    plain_client = LoggedClient(log, Clock(), REPLY)
    live.AnthropicModel(plain_client).complete(request)  # type: ignore[arg-type]
    assert client.params == plain_client.params == [live.request_params(MODEL_SETTINGS, request)]
    assert client.options == plain_client.options
    assert gate.seen == [(MODEL_SETTINGS, request)] and log == ["sent"]

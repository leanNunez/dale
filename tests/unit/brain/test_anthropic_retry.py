"""The adapter's own retry loop (R9 S9.4-S9.6, DD29, log D18, ADR 0011): a fake client whose
calls advance a fake monotonic clock, SDK errors built on real `httpx2` responses, and an
injected `sleep` that advances the same clock. No wait path may outlast the deadline."""

from typing import Any

import anthropic
import httpx2
import pytest
from anthropic.types import Message

from dale.brain.application.deadline import Deadline
from dale.brain.application.model_port import (
    DeadlineExceededError,
    ModelRequest,
    ModelUnavailableError,
    parse_response,
)
from dale.brain.infrastructure import anthropic_model as live
from tests.unit.brain.test_model_port import SEARCH, message

URL = "https://api.invalid/v1/messages"
RAW = message(SEARCH)
REPLY = Message.model_validate(RAW)
HANG = object()  # an attempt that never answers


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def status(code: int, **headers: str) -> anthropic.APIStatusError:
    response = httpx2.Response(code, headers=headers, request=httpx2.Request("POST", URL))
    return anthropic.APIStatusError(f"status {code}", response=response, body=None)


def timed_out() -> anthropic.APITimeoutError:
    return anthropic.APITimeoutError(httpx2.Request("POST", URL))


class FakeClient:
    """`with_options` records each attempt's options; each `create` takes `seconds` on the clock
    and answers the next outcome (the last one repeats). `HANG` takes the attempt's timeout and
    then times out."""

    def __init__(self, clock: Clock, *outcomes: Any, seconds: float = 2.0) -> None:
        self.clock, self.outcomes, self.seconds = clock, list(outcomes), seconds
        self.options: list[dict[str, Any]] = []
        self.sent = 0

    @property
    def messages(self) -> "FakeClient":
        return self

    def with_options(self, **options: Any) -> "FakeClient":
        self.options.append(options)
        return self

    def create(self, **_: Any) -> Message:
        self.sent += 1
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if outcome is HANG:  # no answer: the attempt's own timeout ends it
            self.clock.now += self.options[-1]["timeout"]
            raise timed_out()
        self.clock.now += self.seconds
        if isinstance(outcome, Exception):
            raise outcome
        return outcome  # type: ignore[no-any-return]


class Run:
    def __init__(self, *outcomes: Any, left: float | None = 30.0, seconds: float = 2.0) -> None:
        self.clock, self.waits = Clock(), list[float]()
        self.client = FakeClient(self.clock, *outcomes, seconds=seconds)
        deadline = None if left is None else Deadline.after(left, self.clock)
        self.request = ModelRequest((), (), ({"role": "user"},), deadline)
        self.model = live.AnthropicModel(self.client, sleep=self.sleep)  # type: ignore[arg-type]

    def sleep(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.clock.now += seconds

    def __call__(self) -> Any:
        return self.model.complete(self.request)


def test_a_retry_after_beyond_the_deadline_is_not_waited_for() -> None:
    """S9.4: 30 s left, retry-after 60: no wait, no second request, the deadline error."""
    run = Run(status(429, **{"retry-after": "60"}), REPLY, seconds=0.0)
    with pytest.raises(DeadlineExceededError):
        run()
    assert (run.client.sent, run.waits) == (1, [])


def test_a_retry_after_that_fits_is_waited_for_and_the_call_goes_on() -> None:
    """S9.5: 30 s left, retry-after 5: one 5 s wait, then the retry answers."""
    run = Run(status(429, **{"retry-after": "5"}), REPLY, seconds=0.0)
    assert run() == parse_response(REPLY.model_dump(mode="json"))
    assert (run.client.sent, run.waits) == (2, [5.0])


@pytest.mark.parametrize(
    "error",
    [status(500), status(529), status(408), status(409), status(429), timed_out()],
    ids=["500", "529", "408", "409", "429", "timeout"],
)
def test_a_retryable_failure_on_every_attempt_stops_at_three(error: Exception) -> None:
    """S9.6: time remains, so the attempt bound ends it, with the backoff in between."""
    run = Run(error, left=None)
    with pytest.raises(ModelUnavailableError) as raised:
        run()
    assert not isinstance(raised.value, DeadlineExceededError)
    assert (run.client.sent, run.waits) == (live.MAX_ATTEMPTS, [0.5, 1.0]) == (3, [0.5, 1.0])


@pytest.mark.parametrize("left", [0.0, 0.5, 0.999])
def test_under_one_second_left_nothing_is_sent(left: float) -> None:
    run = Run(REPLY, left=left)
    with pytest.raises(DeadlineExceededError):
        run()
    assert (run.client.sent, run.client.options) == (0, [])


def test_a_retry_that_would_leave_under_one_second_is_not_started() -> None:
    """The backoff fits the time left only with an attempt's minimum after it."""
    run = Run(status(500), REPLY, left=3.0, seconds=1.6)  # 1.4 s left after the first attempt
    with pytest.raises(DeadlineExceededError):
        run()
    assert (run.client.sent, run.waits) == (1, [])


def test_retry_after_ms_wins_over_retry_after() -> None:
    run = Run(status(429, **{"retry-after-ms": "250", "retry-after": "20"}), REPLY)
    run()
    assert run.waits == [0.25]


def test_an_unparsed_retry_after_falls_back_to_the_backoff() -> None:
    run = Run(status(503, **{"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"}), REPLY)
    run()
    assert run.waits == [0.5]


def test_x_should_retry_false_stops_and_true_retries_a_400() -> None:
    stop = Run(status(500, **{"x-should-retry": "false"}), REPLY)
    with pytest.raises(ModelUnavailableError):
        stop()
    go = Run(status(400, **{"x-should-retry": "true"}), REPLY)
    go()
    assert (stop.client.sent, go.client.sent) == (1, 2)


@pytest.mark.parametrize(
    "error", [status(400), status(401), status(404), anthropic.AnthropicError("x")]
)
def test_a_non_retryable_error_is_not_retried(error: Exception) -> None:
    run = Run(error, REPLY)
    with pytest.raises(ModelUnavailableError) as raised:
        run()
    assert not isinstance(raised.value, DeadlineExceededError)
    assert (run.client.sent, run.waits) == (1, [])


def test_each_attempt_timeout_is_the_smaller_of_60_s_and_the_time_left() -> None:
    run = Run(timed_out(), timed_out(), REPLY, left=90.0, seconds=40.0)
    run()  # attempts start with 90, 49.5 and 8.5 s left (40 s each, then 0.5 and 1 s waits)
    assert run.client.options == [
        {"timeout": 60.0, "max_retries": 0},
        {"timeout": 49.5, "max_retries": 0},
        {"timeout": 8.5, "max_retries": 0},
    ]


def test_with_no_deadline_every_attempt_times_out_at_60_s_and_a_wait_is_capped_at_30_s() -> None:
    run = Run(status(429, **{"retry-after": "3600"}), REPLY, left=None)
    run()
    assert run.waits == [live.NO_DEADLINE_WAIT_CAP] == [30.0]
    assert [o["timeout"] for o in run.client.options] == [60.0, 60.0]


def test_a_last_attempt_that_runs_out_of_time_is_the_deadline_not_the_retry_bound() -> None:
    """R9: 30 s left, two 429s with retry-after 5, then a hang that its 20 s timeout ends at
    the deadline: `turn_deadline_exceeded`, never `model_unavailable`."""
    run = Run(status(429, **{"retry-after": "5"}), status(429, **{"retry-after": "5"}), HANG)
    run.client.seconds = 0.0
    with pytest.raises(DeadlineExceededError):
        run()
    assert (run.client.sent, run.waits, run.clock.now) == (3, [5.0, 5.0], 30.0)
    assert run.client.options[-1]["timeout"] == 20.0


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("0", ModelUnavailableError),
        ("1", ModelUnavailableError),
        ("5", ModelUnavailableError),
        ("13.9", ModelUnavailableError),
        ("14", ModelUnavailableError),
        ("29", DeadlineExceededError),
        ("60", DeadlineExceededError),
    ],
)
def test_no_wait_or_attempt_outlasts_the_deadline(header: str, expected: type) -> None:
    """Whatever the failures, the call ends by the deadline minus an attempt's minimum, as the
    retry bound while time is left and as the deadline once a wait does not fit."""
    run = Run(status(429, **{"retry-after": header}), left=30.0, seconds=0.0)
    with pytest.raises(ModelUnavailableError) as raised:
        run()
    assert type(raised.value) is expected
    assert run.clock.now <= 30.0 - live.MIN_ATTEMPT_SECONDS

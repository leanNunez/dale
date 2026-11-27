"""The turn deadline value (R9, DD28, ADR 0011): a fake monotonic clock, and a request field
that changes nothing the model receives or a recording is matched by (S9.9)."""

from dataclasses import replace

from dale.brain.application.deadline import Deadline
from dale.brain.application.model_port import (
    MODEL_SETTINGS,
    DeadlineExceededError,
    ModelRequest,
    ModelUnavailableError,
)
from dale.brain.infrastructure.anthropic_model import request_params
from evals.harness.model import messages_digest, request_fingerprint


class FakeClock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


REQUEST = ModelRequest(({"text": "reglas"},), ({"name": "x"},), ({"role": "user"},))


def test_a_deadline_counts_down_on_its_clock_and_never_below_zero() -> None:
    clock = FakeClock()
    deadline = Deadline.after(90, clock)
    assert deadline is not None and deadline.at == 1_090.0
    assert (deadline.remaining(), deadline.expired()) == (90.0, False)
    clock.now += 89.5
    assert (deadline.remaining(), deadline.expired()) == (0.5, False)
    clock.now += 0.5
    assert (deadline.remaining(), deadline.expired()) == (0.0, True)
    clock.now += 40
    assert (deadline.remaining(), deadline.expired()) == (0.0, True)


def test_no_seconds_means_no_deadline() -> None:
    assert Deadline.after(None, FakeClock()) is None


def test_two_deadlines_at_the_same_instant_are_equal_whatever_their_clock() -> None:
    assert Deadline(5.0, FakeClock()) == Deadline(5.0, FakeClock()) != Deadline(6.0)


def test_a_request_defaults_to_no_deadline_and_ignores_it_in_equality_and_repr() -> None:
    timed = replace(REQUEST, deadline=Deadline.after(30, FakeClock()))
    assert REQUEST.deadline is None and timed.deadline is not None
    assert timed == REQUEST and repr(timed) == repr(REQUEST)
    assert "deadline" not in repr(timed)


def test_the_deadline_reaches_no_request_parameter_fingerprint_or_digest() -> None:
    """S9.9: what is sent, and what a recording is matched by, is the same with a deadline."""
    timed = replace(REQUEST, deadline=Deadline.after(30, FakeClock()))
    assert request_params(MODEL_SETTINGS, timed) == request_params(MODEL_SETTINGS, REQUEST)
    assert "deadline" not in str(request_params(MODEL_SETTINGS, timed))
    assert request_fingerprint(timed) == request_fingerprint(REQUEST)
    assert messages_digest(timed) == messages_digest(REQUEST)


def test_a_deadline_error_is_a_model_unavailable_error() -> None:
    assert issubclass(DeadlineExceededError, ModelUnavailableError)

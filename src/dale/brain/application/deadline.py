"""The wall-clock deadline of one turn (R9, DD28, ADR 0011). It is measured on a monotonic
clock, so a change of the system time never moves it. A turn with no configured deadline has
none (`Deadline.after(None)` is `None`): the eval harness and the tests that build `TakeTurn`
without one run as before."""

import time
from collections.abc import Callable
from dataclasses import dataclass, field

type Monotonic = Callable[[], float]


@dataclass(frozen=True, slots=True)
class Deadline:
    at: float  # on the `monotonic` clock, in seconds
    monotonic: Monotonic = field(default=time.monotonic, compare=False, repr=False)

    @classmethod
    def after(
        cls, seconds: float | None, monotonic: Monotonic = time.monotonic
    ) -> "Deadline | None":
        return None if seconds is None else cls(monotonic() + seconds, monotonic)

    def remaining(self) -> float:
        """Seconds left, never negative."""
        return max(0.0, self.at - self.monotonic())

    def expired(self) -> bool:
        return self.remaining() <= 0.0

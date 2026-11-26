"""What every channel shares with the composition root (design D11): the `Backend` it talks to,
the verdict as it reads it, the verdict it shows when the verifier itself fails, and the step
wrapper that keeps one failed step from ending the conversation."""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from dale.shared.customer_input import CustomerText, KeyPress
from dale.shared.shown_events import ShownEvent

logger = logging.getLogger(__name__)


class Verdict(Protocol):
    """The verifier's verdict as a channel reads it (the runner's `VerifierVerdict`)."""

    @property
    def verdict(self) -> str: ...
    @property
    def reason(self) -> str: ...
    @property
    def false_confirmations(self) -> int: ...
    @property
    def unexpected_writes(self) -> int: ...


@dataclass(frozen=True)
class VerifierFailed:
    """The verdict shown when the verifier call itself fails: never verified."""

    verdict: str = "unverifiable"
    reason: str = "verifier_failed"
    false_confirmations: int = 0
    unexpected_writes: int = 0


class Backend(Protocol):
    """What the composition root wires: the brain's turn and confirm, and the verifier."""

    def take_turn(self, said: CustomerText) -> Sequence[ShownEvent]: ...

    def confirm(self, press: KeyPress) -> ShownEvent: ...

    def verify(self, shown: Sequence[ShownEvent]) -> Verdict: ...


def step[T](name: str, run: Callable[[], T]) -> T | None:
    """None when the step raised or was interrupted; the log names the step and the error type."""
    try:
        return run()
    except (Exception, KeyboardInterrupt) as error:
        logger.warning("channel step %s failed: %s", name, type(error).__name__)
        return None

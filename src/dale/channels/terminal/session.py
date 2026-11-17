"""The terminal session (design §8; R4, R12): typed text goes to the brain's turn, the Dale key
to its confirm, and after each press, and after a turn that showed a confirmation, the
verifier judges everything shown so far. Its verdict is always printed.

Each step (turn, confirm, verify) runs on its own (B83): an error or Ctrl-C during one prints a
fixed notice and the session goes on. Only Ctrl-D at the prompt ends it."""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from dale.channels.terminal.pending import Pending
from dale.channels.terminal.render import Verdict, render, render_verdict
from dale.shared.customer_input import CustomerInput, CustomerText, Key, KeyPress
from dale.shared.shown_events import OrderConfirmed, ProposalSummary, ShownEvent

logger = logging.getLogger(__name__)
WELCOME = "Escribí tu pedido. Ctrl-D sale."
DISMISSED = "Propuesta descartada. No se confirmó nada."
TURN_FAILED = "No pude responder ese mensaje. No se confirmó nada: podés escribirlo de nuevo."
CONFIRM_UNKNOWN = (
    "No sé si el pedido quedó confirmado. Apretá F2 de nuevo para reintentar la misma"
    " propuesta: nunca se confirma dos veces."
)


@dataclass(frozen=True)
class VerifierFailed:
    """The verdict printed when the verifier call itself fails: never verified."""

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
        logger.warning("terminal step %s failed: %s", name, type(error).__name__)
        return None


class TerminalSession:
    def __init__(
        self,
        backend: Backend,
        read: Callable[[], CustomerInput],
        write: Callable[[str], None],
        pending: Pending,
    ) -> None:
        self._backend, self._read, self._write, self._pending = backend, read, write, pending
        self.shown: list[ShownEvent] = []  # the run the verifier judges

    def run(self) -> None:
        self._write(WELCOME)
        while True:
            try:
                said = self._read()
            except EOFError:
                return
            except KeyboardInterrupt:  # a signal at the prompt: only Ctrl-D leaves
                continue
            if isinstance(said, KeyPress):
                self.press(said)
            elif said.text.strip():
                self.turn(said)

    def turn(self, said: CustomerText) -> None:
        shown = step("turn", lambda: self._backend.take_turn(said))
        if shown is None:
            self._write(TURN_FAILED)  # what the turn may have shown is unknown; pending stays
            return
        self._show(shown)
        self._pending.after_turn(shown)
        if any(isinstance(e, OrderConfirmed) for e in shown):
            self._verify()

    def press(self, press: KeyPress) -> None:
        if press.key is Key.CANCEL:
            self._pending.after_press(press, None)
            self._write(DISMISSED)
            return
        outcome = step("confirm", lambda: self._backend.confirm(press))
        if outcome is None:
            self._write(CONFIRM_UNKNOWN)  # the pending id stays, so F2 retries it (B53)
        else:
            self._show([outcome])
            self._pending.after_press(press, outcome)
        self._verify()

    def _verify(self) -> None:
        showed = any(isinstance(e, OrderConfirmed) for e in self.shown)
        verdict = step("verify", lambda: self._backend.verify(tuple(self.shown)))
        self._write(render_verdict(verdict or VerifierFailed(), showed))

    def _show(self, events: Sequence[ShownEvent]) -> None:
        """Only the turn's last summary carries the keys hint: it is the one F2 confirms."""
        summaries = [i for i, e in enumerate(events) if isinstance(e, ProposalSummary)]
        self.shown.extend(events)
        for i, event in enumerate(events):
            self._write(render(event, keys_hint=bool(summaries) and i == summaries[-1]))

"""The kill switch (DD33, O5): the one row of `demo.control` holds `paused` and the reason of the
last pause, `initial`, `operator`, `reset` or `deploy`. Only the operator CLI and the host's own
reset change it; no HTTP route does (S5.4).

Fail closed: `read` raises `ControlUnreadableError` on any error, a missing row (the owner may
delete it), a NULL or a reason outside the set, and `paused` turns every such case into `True`
(S5.2). A write locks the row, checks it, and changes exactly one row, or raises
`ControlWriteError` (S6.2): a missing row is a failure, never a no-op. The row lock makes the
check and the write one step, so two writers never act on the same old state; a lock wait past
`lock_timeout` fails as busy.

- `pause("operator")` always takes the pause and its reason, so no reset or deploy resume can
  lift it (S11.5). `pause("reset")` and `pause("deploy")` apply only to a running demo; the
  outcome says whether the caller owns the pause.
- `resume()` lifts any pause (the operator's). `resume(r)` lifts only a pause whose reason is
  `r`; a pause with another reason stays.
- A call that finds the state already as asked changes nothing and succeeds (S6.3).
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, NamedTuple

import sqlalchemy as sa

from dale.apps.demo.tables import REASONS, control
from dale.shared.clock import Clock

OPERATOR = "operator"
PAUSE_REASONS = (OPERATOR, "reset", "deploy")
LOCK_NOT_AVAILABLE = "55P03"  # SQLSTATE of a lock wait past `lock_timeout`
logger = logging.getLogger(__name__)


class ControlError(Exception):
    """The message names a cause or an error class, never a value from the environment."""


class ControlUnreadableError(ControlError):
    pass


class ControlWriteError(ControlError):
    pass


@dataclass(frozen=True, slots=True)
class ControlState:
    paused: bool
    reason: str
    changed_at: datetime


class Outcome(NamedTuple):
    changed: bool  # for a conditional pause: whether the caller owns it
    state: ControlState


def state_of(row: Any) -> ControlState:
    if row is None:
        raise ControlUnreadableError("the control row is missing")
    paused, reason, changed_at = row
    if not (isinstance(paused, bool) and reason in REASONS and isinstance(changed_at, datetime)):
        raise ControlUnreadableError("the control row holds an unknown state")
    return ControlState(paused, reason, changed_at)


_ONE = control.c.id == 1
_ROW = sa.select(control.c.paused, control.c.reason, control.c.changed_at).where(_ONE)


class SqlControl:
    def __init__(self, engine: sa.Engine, clock: Clock) -> None:
        self._engine, self._clock = engine, clock

    def read(self) -> ControlState:
        try:
            with self._engine.connect() as conn:
                row = conn.execute(_ROW).one_or_none()
        except Exception as error:
            raise ControlUnreadableError(_failure("read", error)) from None
        return state_of(row)

    def paused(self) -> bool:
        """The read before each conversation, turn, press and attempt: unreadable is paused."""
        try:
            return self.read().paused
        except ControlUnreadableError as error:
            logger.error("demo control unreadable, treated as paused: %s", error)
            return True

    def pause(self, reason: str = OPERATOR) -> Outcome:
        if reason not in PAUSE_REASONS:
            raise ValueError(f"not a pause reason: {reason}")
        if reason == OPERATOR:
            return self._write(lambda s: not (s.paused and s.reason == OPERATOR), True, reason)
        return self._write(lambda s: not s.paused, True, reason)

    def resume(self, if_reason: str | None = None) -> Outcome:
        return self._write(lambda s: s.paused and if_reason in (None, s.reason), False, None)

    def _write(
        self, applies: Callable[[ControlState], bool], paused: bool, reason: str | None
    ) -> Outcome:
        try:
            with self._engine.begin() as conn:
                state = state_of(conn.execute(_ROW.with_for_update()).one_or_none())
                if not applies(state):
                    return Outcome(False, state)
                now, reason = self._clock.now(), reason or state.reason
                values = {"paused": paused, "reason": reason, "changed_at": now}
                if conn.execute(sa.update(control).where(_ONE).values(values)).rowcount != 1:
                    raise ControlWriteError("the control row did not change")
        except ControlError as error:
            raise ControlWriteError(str(error)) from None
        except Exception as error:
            raise ControlWriteError(_failure("write", error)) from None
        return Outcome(True, ControlState(paused, reason, now))


def _failure(doing: str, error: Exception) -> str:
    """A lock wait past `lock_timeout` is busy; anything else, the class only (a driver message
    may hold the host or the role)."""
    name = type(error).__name__
    if getattr(getattr(error, "orig", None), "sqlstate", None) == LOCK_NOT_AVAILABLE:
        return f"the control row is busy: another write holds it ({name})"
    return f"cannot {doing} the control row: unreachable or failed ({name})"

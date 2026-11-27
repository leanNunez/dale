"""Demo settings (O1, log D9, D23): read only in demo mode, from `DALE_DEMO_*` variables. A
missing or invalid value stops the host (exit 2); a message names the variable, never a value.
The secret stays out of `repr`."""

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import time
from decimal import Decimal, DecimalException

from dale.apps import verifier_runner
from dale.apps.compose import SESSION_TIMEOUTS

P = "DALE_DEMO_"
SECRET, TEMPLATE, CONTACT = f"{P}SESSION_SECRET", f"{P}TEMPLATE_CUSTOMER", f"{P}PRIVACY_CONTACT"
CAP, RESET_AT, DRAIN = f"{P}DAILY_CAP_USD", f"{P}RESET_AT", f"{P}DRAIN_SECONDS"
MAX_COUNT, MAX_RETENTION, MAX_CAP = 10_000, 365, Decimal("5.00")  # log D35
COUNTS = {  # field: (variable, default, maximum), each a whole number from 1
    "concurrent_turns": (f"{P}CONCURRENT_TURNS", 4, MAX_COUNT),
    "live_conversations": (f"{P}LIVE_CONVERSATIONS", 10, MAX_COUNT),
    "session_conversations_per_day": (f"{P}SESSION_CONVERSATIONS_PER_DAY", 3, MAX_COUNT),
    "conversation_turns": (f"{P}CONVERSATION_TURNS", 20, MAX_COUNT),
    "ip_turns_per_day": (f"{P}IP_TURNS_PER_DAY", 60, MAX_COUNT),
    "ip_conversations_per_day": (f"{P}IP_CONVERSATIONS_PER_DAY", 10, MAX_COUNT),
    "idle_ttl_minutes": (f"{P}IDLE_TTL_MINUTES", 30, MAX_COUNT),
    "retention_days": (f"{P}RETENTION_DAYS", 30, MAX_RETENTION),
}
DEFAULT_CAP, DEFAULT_RESET_AT, DEFAULT_DRAIN = "0.50", "04:00", "240"  # log D6, D11, D23
MAX_RAW = 20  # characters: a longer value is refused before any conversion
MIN_SECRET = 32  # characters
STATEMENT_ROUND = SESSION_TIMEOUTS["statement_timeout"] / 1000  # seconds
DRAIN_MARGIN = 30.0
CONTACT_SHAPE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s.]+")


class DemoSettingsError(ValueError):
    """A demo setting is missing or invalid: the host refuses to start (O1)."""


@dataclass(frozen=True)
class DemoSettings:
    session_secret: bytes = field(repr=False)
    template_customer: str
    privacy_contact: str
    daily_cap_micros: int
    reset_at: time
    drain_seconds: float
    concurrent_turns: int
    live_conversations: int
    session_conversations_per_day: int
    conversation_turns: int
    ip_turns_per_day: int
    ip_conversations_per_day: int
    idle_ttl_minutes: int
    retention_days: int


def drain_floor(turn_seconds: float, press_wait: float) -> float:
    """The slowest honest turn (deadline, one statement round, verifier) or press (its wait,
    verifier), plus a margin; the drain bound must be above it (log D23, S11.7)."""
    verifier = verifier_runner.TIMEOUT_SECONDS
    return max(turn_seconds + STATEMENT_ROUND + verifier, press_wait + verifier) + DRAIN_MARGIN


def parse(env: Mapping[str, str], *, turn_seconds: float, press_wait: float) -> DemoSettings:
    secret, template, contact = (env.get(name, "").strip() for name in (SECRET, TEMPLATE, CONTACT))
    if len(secret) < MIN_SECRET:
        raise DemoSettingsError(f"{SECRET} must be set to at least {MIN_SECRET} characters")
    if not template:
        raise DemoSettingsError(f"{TEMPLATE} must be set")
    if not CONTACT_SHAPE.fullmatch(contact):
        raise DemoSettingsError(f"{CONTACT} must be set to an email address")
    counts = {name: _count(env, *spec) for name, spec in COUNTS.items()}
    drain = _number(env, DRAIN, DEFAULT_DRAIN)
    if not drain > drain_floor(turn_seconds, press_wait):  # the message names no deadline
        v = verifier_runner.TIMEOUT_SECONDS
        formula = f"max(turn deadline + {STATEMENT_ROUND + v:g} s, {press_wait + v:g} s)"
        formula += f" + {DRAIN_MARGIN:g} s"
        raise DemoSettingsError(f"{DRAIN} must be above {formula}")
    return DemoSettings(
        secret.encode(), template, contact, _cap(env), _reset_at(env), drain, **counts
    )


def _raw(env: Mapping[str, str], variable: str, default: str) -> str | None:
    """The value if it is short and ASCII (no other script's digits), or None."""
    raw = env.get(variable) or default
    return raw if raw.isascii() and len(raw) <= MAX_RAW else None


def _count(env: Mapping[str, str], variable: str, default: int, maximum: int) -> int:
    raw = _raw(env, variable, str(default))
    if not (raw and raw.isdigit() and 0 < int(raw) <= maximum):
        raise DemoSettingsError(f"{variable} must be a whole number from 1 to {maximum}")
    return int(raw)


def _number(env: Mapping[str, str], variable: str, default: str) -> float:
    try:
        value = float(_raw(env, variable, default) or "nan")
    except ValueError:
        value = math.nan
    if not math.isfinite(value):
        raise DemoSettingsError(f"{variable} must be a number of seconds")
    return value


def _cap(env: Mapping[str, str]) -> int:
    """US dollars to whole micro-USD: above 0, at most the bound, no finer than a micro-dollar."""
    try:
        dollars = Decimal(_raw(env, CAP, DEFAULT_CAP) or "NaN")
        if dollars.is_finite() and 0 < dollars <= MAX_CAP and (micros := dollars * 10**6) % 1 == 0:
            return int(micros)
    except DecimalException:  # an overflow or a signalling NaN too, never a traceback
        pass
    raise DemoSettingsError(f"{CAP} must be an amount of US dollars above 0 and at most {MAX_CAP}")


def _reset_at(env: Mapping[str, str]) -> time:
    raw = env.get(RESET_AT) or DEFAULT_RESET_AT
    if not re.fullmatch(r"([01][0-9]|2[0-3]):[0-5][0-9]", raw):
        raise DemoSettingsError(f"{RESET_AT} must be a time as HH:MM")
    return time.fromisoformat(raw)

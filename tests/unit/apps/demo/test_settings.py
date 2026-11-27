"""Demo settings (O1 S1.1, S11.7): every value has its default or stops the host, and the secret
never shows in `repr`."""

import re
from datetime import time

import pytest

from dale.apps.demo import settings as s
from dale.apps.demo.settings import DemoSettingsError, drain_floor, parse

SECRET = "x" * 32
REQUIRED = {s.SECRET: SECRET, s.TEMPLATE: "C-001", s.CONTACT: "privacidad@example.com"}
DEADLINE, PRESS_WAIT = 90.0, 60.0


def demo(env: dict[str, str], turn_seconds: float = DEADLINE) -> s.DemoSettings:
    return parse(env, turn_seconds=turn_seconds, press_wait=PRESS_WAIT)


def refused(env: dict[str, str], error: str, turn_seconds: float = DEADLINE) -> None:
    with pytest.raises(DemoSettingsError, match=f"^{re.escape(error)}$"):
        demo(env, turn_seconds)


def test_every_setting_has_its_default() -> None:
    got = demo(REQUIRED)
    assert (got.session_secret, got.template_customer) == (SECRET.encode(), "C-001")
    assert got.privacy_contact == "privacidad@example.com"
    assert (got.daily_cap_micros, got.reset_at, got.drain_seconds) == (500_000, time(4), 240.0)
    counts = {name: getattr(got, name) for name in s.COUNTS}
    assert counts == {
        "concurrent_turns": 4,
        "live_conversations": 10,
        "session_conversations_per_day": 3,
        "conversation_turns": 20,
        "ip_turns_per_day": 60,
        "ip_conversations_per_day": 10,  # log D17
        "idle_ttl_minutes": 30,
        "retention_days": 30,  # log D8
    }


def test_every_setting_can_be_set() -> None:
    env = {**REQUIRED, s.CAP: "1.25", s.RESET_AT: "03:30", s.DRAIN: "300"}
    env |= {variable: "7" for variable, *_ in s.COUNTS.values()}
    got = demo(env)
    assert (got.daily_cap_micros, got.reset_at, got.drain_seconds) == (1_250_000, time(3, 30), 300)
    assert {getattr(got, name) for name in s.COUNTS} == {7}


@pytest.mark.parametrize(
    ("variable", "error"),
    [
        (s.CONTACT, f"{s.CONTACT} must be set to an email address"),  # S1.1
        (s.SECRET, f"{s.SECRET} must be set to at least 32 characters"),
        (s.TEMPLATE, f"{s.TEMPLATE} must be set"),
    ],
)
@pytest.mark.parametrize("value", [None, "", "   "], ids=["unset", "empty", "blank"])
def test_a_missing_required_setting_is_an_error(
    variable: str, error: str, value: str | None
) -> None:
    env = {k: v for k, v in REQUIRED.items() if k != variable}
    refused(env if value is None else {**env, variable: value}, error)


@pytest.mark.parametrize("value", ["x" * 31, "privacidad", "a@b", "a b@example.com", "@ex.com"])
def test_a_short_secret_or_a_contact_that_is_no_address_is_an_error(value: str) -> None:
    variable = s.SECRET if value.startswith("x") else s.CONTACT
    with pytest.raises(DemoSettingsError, match=f"^{variable} "):
        demo({**REQUIRED, variable: value})


@pytest.mark.parametrize("raw", ["0", "-1", "1.5", "abc", "٣", " 4", "1" * 21, "9" * 5000, "+"])
@pytest.mark.parametrize(("variable", "maximum"), [(v, m) for v, _, m in s.COUNTS.values()])
def test_an_invalid_or_too_large_limit_or_retention_is_an_error(
    variable: str, maximum: int, raw: str
) -> None:
    error = f"{variable} must be a whole number from 1 to {maximum}"
    for value in (raw, str(maximum + 1)):
        refused({**REQUIRED, variable: value}, error)
    assert demo({**REQUIRED, variable: str(maximum)})  # the bound itself is allowed


def test_the_bounds_sit_well_above_the_defaults() -> None:
    """Log D35: a bound stops a value that would switch a control off, never a default."""
    assert (s.MAX_COUNT, s.MAX_RETENTION, str(s.MAX_CAP)) == (10_000, 365, "5.00")
    assert demo({**REQUIRED, s.CAP: "5.00"}).daily_cap_micros == 5_000_000


@pytest.mark.parametrize(
    "raw",
    [
        *("0", "0.00", "-0.50", "abc", "NaN", "sNaN", "Infinity", "0.0000001", "5.000001"),
        *("1E+999999", "\u0660.\u0665", "0." + "5" * 20),
    ],
)
def test_a_cap_not_an_amount_within_bounds_is_an_error(raw: str) -> None:
    refused(
        {**REQUIRED, s.CAP: raw},
        f"{s.CAP} must be an amount of US dollars above 0 and at most 5.00",
    )


@pytest.mark.parametrize(
    "raw", ["4:00", "24:00", "04:60", "04:00:00", "noon", "0\u0664:00", "\u0660\u0664:\u0660\u0660"]
)
def test_a_reset_time_not_as_hh_mm_is_an_error(raw: str) -> None:
    refused({**REQUIRED, s.RESET_AT: raw}, f"{s.RESET_AT} must be a time as HH:MM")


def test_the_drain_floor_follows_the_startup_formula() -> None:
    """max(deadline + 5 s statement round + 30 s verifier, press wait 60 s + 30 s) + 30 s."""
    assert drain_floor(90, 60) == 155
    assert drain_floor(180, 60) == 245
    assert drain_floor(31, 60) == 120  # the press bound wins under a short deadline


@pytest.mark.parametrize(
    ("drain", "deadline"),
    [("155", 90.0), ("150", 90.0), ("240", 180.0), ("-1", 90.0), ("nan", 90.0), ("٢٤٠", 90.0)],
)
def test_a_drain_bound_not_above_the_floor_is_an_error(drain: str, deadline: float) -> None:
    """S11.7: 155 s or less under a 90 s deadline, or 240 s under 180 s, stops the host."""
    with pytest.raises(DemoSettingsError, match=f"^{s.DRAIN} must be "):
        demo({**REQUIRED, s.DRAIN: drain}, deadline)


def test_the_default_drain_bound_is_240_s_and_just_above_the_floor_passes() -> None:
    assert demo(REQUIRED).drain_seconds == 240.0
    assert demo({**REQUIRED, s.DRAIN: "155.5"}).drain_seconds == 155.5
    formula = "max(turn deadline + 35 s, 90 s) + 30 s"  # the number would reveal the deadline
    refused(REQUIRED, f"{s.DRAIN} must be above {formula}", 180.0)


def test_the_secret_never_shows_in_repr_or_str() -> None:
    got = demo({**REQUIRED, s.SECRET: "s3cr3t-" + "k" * 30})
    assert "s3cr3t" not in repr(got) and "s3cr3t" not in str(got)
    assert "session_secret" not in repr(got)


def test_no_error_message_shows_a_value() -> None:
    values = {s.CAP: "s3cr3t", s.CONTACT: "s3cr3t", s.RESET_AT: "s3cr3t", s.DRAIN: "s3cr3t"}
    for env in ({**REQUIRED, name: value} for name, value in values.items()):
        with pytest.raises(DemoSettingsError) as error:
            demo(env)
        assert "s3cr3t" not in str(error.value)

"""The turn deadline setting (R9 S9.11, ADR 0011): a number of seconds above the verifier's own
timeout, default 90, or the terminal and the web host refuse to start (exit 2)."""

from pathlib import Path

import pytest
import sqlalchemy as sa

from dale.apps import terminal, web
from dale.apps.compose import DEADLINE_VARIABLE, TurnDeadlineError, turn_deadline
from dale.apps.verifier_runner import TIMEOUT_SECONDS
from tests.unit.test_web_app import REQUIRED

REFUSED = ["30", "30.0", "29.9", "0", "-90", "abc", "nan", "inf", "-inf", "1e400", " ", "9 0"]
ERROR = f"{DEADLINE_VARIABLE} must be a number of seconds above 30"


def test_the_default_is_90_s_and_sits_above_the_verifier_timeout() -> None:
    assert TIMEOUT_SECONDS == 30.0
    assert turn_deadline({}) == turn_deadline({DEADLINE_VARIABLE: ""}) == 90.0


@pytest.mark.parametrize(("raw", "seconds"), [("30.5", 30.5), ("45", 45.0), ("120", 120.0)])
def test_a_number_above_the_verifier_timeout_is_taken(raw: str, seconds: float) -> None:
    assert turn_deadline({DEADLINE_VARIABLE: raw}) == seconds


@pytest.mark.parametrize("raw", REFUSED)
def test_a_deadline_at_or_below_the_verifier_timeout_or_not_a_number_is_refused(raw: str) -> None:
    with pytest.raises(TurnDeadlineError, match=f"^{ERROR}$"):
        turn_deadline({DEADLINE_VARIABLE: raw})


def never(*_: object, **__: object) -> object:
    raise AssertionError("built before the deadline setting was checked")


@pytest.mark.parametrize("raw", ["30", "abc"])
def test_the_terminal_exits_2_on_a_refused_deadline(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], raw: str
) -> None:
    for name in terminal.REQUIRED:
        monkeypatch.setenv(name, "set")
    monkeypatch.setenv(DEADLINE_VARIABLE, raw)
    monkeypatch.setattr(terminal, "log_to_file", never)
    monkeypatch.setattr(sa, "create_engine", never)
    assert terminal.main(["--customer", "C-001"]) == 2
    assert capsys.readouterr().err == f"{ERROR}\n"


@pytest.mark.parametrize("raw", ["30", "abc"])
def test_the_web_host_exits_2_on_a_refused_deadline(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], raw: str
) -> None:
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv(DEADLINE_VARIABLE, raw)
    monkeypatch.setattr(web, "database_engine", never)
    assert web.main([]) == 2
    assert capsys.readouterr().err == f"{ERROR}\n"


def test_the_web_settings_carry_the_deadline() -> None:
    assert web.settings(REQUIRED).turn_seconds == 90.0
    assert web.settings({**REQUIRED, DEADLINE_VARIABLE: "45"}).turn_seconds == 45.0


class StoppedError(Exception):
    pass


def test_the_terminal_passes_the_deadline_to_compose(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: list[object] = []

    def compose(*_: object, turn_seconds: float | None = None) -> object:
        seen.append(turn_seconds)
        raise StoppedError

    for name in terminal.REQUIRED:
        monkeypatch.setenv(name, "postgresql+psycopg://nobody@127.0.0.1/none")
    monkeypatch.setenv(DEADLINE_VARIABLE, "45")
    monkeypatch.setenv(terminal.LOG_VARIABLE, str(tmp_path / "terminal.log"))
    monkeypatch.setattr(terminal, "compose", compose)
    with pytest.raises(StoppedError):
        terminal.main(["--customer", "C-001"])
    assert seen == [45.0]


def test_the_web_host_passes_the_deadline_to_every_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[object] = []

    def backends(*args: object) -> object:
        seen.append(args[-1])
        raise StoppedError

    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv(DEADLINE_VARIABLE, "45")
    monkeypatch.setattr(web, "backends", backends)
    monkeypatch.setattr(web, "startup_error", lambda *_: None)
    with pytest.raises(StoppedError):
        web.main([], erp=lambda _: None)  # type: ignore[arg-type,return-value]
    assert seen == [45.0]

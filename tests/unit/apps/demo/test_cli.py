"""The operator CLI's own checks (O6, design §7): bad arguments and a missing setting exit 2
before any connection, a failed connection exits 1, and nothing prints the URL, its password or
its host. The commands against a real database are in `tests/integration/test_demo_control.py`."""

import subprocess
import sys

import pytest
import sqlalchemy as sa

from dale.apps.demo.cli import URL_VARIABLE, main

SECRET_URL = "postgresql+psycopg://dale_app:hunter2@127.0.0.1:9/dale"  # nothing listens on 9


def no_engine(url: str) -> sa.Engine:
    raise AssertionError("no connection before the arguments and settings are checked")


@pytest.mark.parametrize(
    "argv", [[], ["unpause"], ["pause", "--reason", "reset"], ["pause", "--reason", "initial"],
             ["resume", "--if-reason", "reset"], ["resume", "extra"], ["status", "--all"]],
)  # fmt: skip
def test_bad_arguments_exit_2(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert main(argv, {URL_VARIABLE: SECRET_URL}, engine_for=no_engine) == 2
    assert "usage: python -m dale.apps.demo" in capsys.readouterr().err


@pytest.mark.parametrize("env", [{}, {URL_VARIABLE: ""}])
def test_a_missing_url_exits_2(env: dict[str, str], capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["pause"], env, engine_for=no_engine) == 2
    assert capsys.readouterr().err == f"{URL_VARIABLE} must be set\n"


def test_a_malformed_url_exits_2_and_prints_none_of_it(capsys: pytest.CaptureFixture[str]) -> None:
    url = "postgresql+psycopg://dale_app:ab@cd:se@cret@db.internal:5432/dale"
    assert main(["pause"], {URL_VARIABLE: url}) == 2
    out, err = capsys.readouterr()
    assert (out, err) == ("", f"{URL_VARIABLE} is not a usable database URL (ValueError)\n")
    for part in ("ab@cd", "se@cret", "cret", "db.internal", "Traceback"):
        assert part not in out + err


@pytest.mark.parametrize("argv", [["pause"], ["resume", "--if-reason", "deploy"]])
def test_a_failed_connection_exits_1_and_prints_no_url(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:  # S6.2
    assert main(argv, {URL_VARIABLE: SECRET_URL}) == 1
    failed = f"{argv[0]} failed: cannot write the control row: unreachable or failed"
    failed += " (OperationalError)\n"
    assert capsys.readouterr() == ("", failed)


def test_status_with_no_database_prints_every_field_as_unknown_and_exits_1(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["status"], {URL_VARIABLE: SECRET_URL}) == 1
    out, err = capsys.readouterr()
    lines = out.splitlines()
    assert lines[:2] == [
        "control: unknown, so the host treats it as paused",
        "daily cap (this command's settings): 0.500000 USD",
    ]
    assert len(lines) == 11 and all(line.endswith(": unknown") for line in lines[2:])
    assert err == "" and "hunter2" not in out and "127.0.0.1" not in out


def test_the_module_runs_with_no_web_stack() -> None:
    usage = subprocess.run([sys.executable, "-m", "dale.apps.demo"], capture_output=True, text=True)
    assert usage.returncode == 2 and "usage:" in usage.stderr
    web = ("fastapi", "starlette", "uvicorn", "dale.channels", "dale.apps.web")
    probe = "import sys, dale.apps.demo.cli; "
    probe += f"print([m for m in sys.modules if m.startswith({web})])"
    loaded = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
    assert (loaded.returncode, loaded.stdout) == (0, "[]\n")

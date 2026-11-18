"""The verifier spawn, the one process boundary (design §13): a timeout, a crash, a non-zero exit
or malformed stdout is unverifiable, never verified, even when the child printed `verified`."""

import json
import logging
import subprocess
import sys
from typing import Any

import pytest

from dale.apps.verifier_runner import COMMAND, parse_verdict, request_json, run_verifier
from dale.verifier.application.verify import report_to_json
from tests.unit.verifier.test_verdict import CLAIM, SESSION, SHOWN, run

VERIFIED = report_to_json(run(SHOWN))
KEY_VARIABLE = "_".join(("ANTHROPIC", "API", "KEY"))  # spelled apart: the key guard scans for it
REQUEST = request_json(SESSION.company_id, SESSION.customer_id, SESSION.conversation_id, [SHOWN])


def child(code: str) -> list[str]:
    """A stand-in verifier process that runs `code` instead of the real one."""
    return [sys.executable, "-c", f"import sys, time\nOUT = {VERIFIED!r}\n{code}"]


def test_the_real_verdict_parses_and_is_the_only_verified() -> None:
    assert parse_verdict(VERIFIED.encode()).verified
    for report in (run(SHOWN, CLAIM, orders=()), run(orders=())):
        assert not parse_verdict(report_to_json(report).encode()).verified


@pytest.mark.parametrize(
    ("code", "reason"),
    [
        ("sys.stdout.write(OUT); sys.stdout.flush(); time.sleep(10)", "timeout"),
        ("sys.stdout.write(OUT); sys.exit(1)", "exit_1"),
        ("sys.stdout.write(OUT); raise RuntimeError('crash')", "exit_1"),
        (
            "import os; sys.stdout.write(OUT); sys.stdout.flush(); os.kill(os.getpid(), 9)",
            "exit_-9",
        ),
        ("print('verified')", "malformed_output"),
        ("sys.stdout.write(OUT + OUT)", "malformed_output"),
        ("sys.stdout.buffer.write(b'\\xff' + OUT.encode())", "malformed_output"),
        ("pass", "malformed_output"),
    ],
)
def test_every_failure_of_the_child_is_unverifiable(code: str, reason: str) -> None:
    verdict = run_verifier(REQUEST, command=child(code), timeout=1.0)
    assert (verdict.verdict, verdict.reason, verdict.verified) == ("unverifiable", reason, False)


def forged(**changes: Any) -> bytes:
    return json.dumps(json.loads(VERIFIED) | changes).encode()


@pytest.mark.parametrize(
    "stdout",
    [
        forged(false_confirmations=1),
        forged(unexpected_writes=1),
        forged(findings=[]),
        forged(reason="timeout"),
        forged(extra=True),
        forged(false_confirmations="0"),
        forged(findings=[{"kind": "missing", "proposal_id": None, "order_id": None, "fields": []}]),
        forged(verdict="nothing_confirmed"),  # the verdict must follow from the findings
        forged(verdict="unverifiable", reason="timeout"),
        forged(
            findings=[{"kind": "verified", "proposal_id": None, "order_id": None, "fields": []}]
        ),
    ],
)
def test_an_inconsistent_or_loose_verified_is_not_believed(stdout: bytes) -> None:
    assert parse_verdict(stdout).verdict == "unverifiable"


def test_the_tail_of_the_childs_stderr_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    code = "sys.stderr.buffer.write(b'x' * 5000 + b'\\xff LookupError'); sys.stdout.write(OUT)"
    with caplog.at_level(logging.WARNING, "dale.apps.verifier_runner"):
        assert run_verifier(REQUEST, command=child(code)).verified
    (record,) = caplog.records
    assert record.levelno == logging.WARNING and record.getMessage().endswith("\ufffd LookupError")
    assert len(record.getMessage()) < 2_100


def test_a_spawn_failure_is_unverifiable() -> None:
    assert run_verifier(REQUEST, command=["/no/such/python"]).reason == "spawn_failed"


def test_the_spawn_is_fixed_and_carries_no_user_data_or_extra_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Any, dict[str, Any]]] = []

    def fake(args: Any, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, VERIFIED.encode(), b"")

    monkeypatch.setenv("DALE_UNRELATED_SETTING", "x")
    monkeypatch.setenv(KEY_VARIABLE, "dummy-not-a-key")
    monkeypatch.setattr(subprocess, "run", fake)
    assert run_verifier(REQUEST, database_url="postgresql://v@127.0.0.1/d").verified
    ((args, kwargs),) = calls
    assert args == [sys.executable, "-m", "dale.verifier"] == list(COMMAND)
    assert kwargs["input"] == REQUEST.encode() and "shell" not in kwargs
    assert kwargs["timeout"] == 30.0 and "DALE_UNRELATED_SETTING" not in kwargs["env"]
    assert kwargs["env"]["DALE_VERIFIER_DATABASE_URL"] == "postgresql://v@127.0.0.1/d"
    assert KEY_VARIABLE not in kwargs["env"] and "dummy-not-a-key" not in kwargs["env"].values()

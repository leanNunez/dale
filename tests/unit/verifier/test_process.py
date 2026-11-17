"""The verifier process's composition root: one verdict line on stdout, exit 0, and
unverifiable for a bad request or a missing database URL."""

import io
import json
from uuid import UUID

import pytest

from dale.apps import verifier
from dale.verifier.application.verify import SESSION_KEYS
from dale.verifier.domain.verdict import Evidence, Session

SECRET_ID = str(UUID(int=7))  # stands for anything the request carries


@pytest.mark.parametrize(
    ("stdin", "env", "reason"),
    [
        ("[]", {"DALE_VERIFIER_DATABASE_URL": "x"}, "bad_request"),
        ('{"session": {}, "shown": []}', {"DALE_VERIFIER_DATABASE_URL": "x"}, "bad_request"),
        (
            json.dumps({"session": dict.fromkeys(SESSION_KEYS, "0" * 32), "shown": []}),
            {"DALE_ANOTHER_URL": "x"},
            "no_database_url",
        ),
    ],
)
def test_a_request_that_cannot_be_checked_prints_unverifiable(
    stdin: str, env: dict[str, str], reason: str
) -> None:
    out = io.StringIO()
    assert verifier.run(io.StringIO(stdin), out, env, io.StringIO()) == 0
    assert out.getvalue().endswith("\n") and out.getvalue().count("\n") == 1
    assert json.loads(out.getvalue())["verdict"] == "unverifiable"
    assert json.loads(out.getvalue())["reason"] == reason


class FailingReader:
    def __init__(self, engine: object) -> None:
        self.engine = engine

    def read(self, session: Session, shown: object) -> Evidence:
        raise ConnectionRefusedError(f"cannot read {session.conversation_id}")


def test_why_a_run_is_unverifiable_goes_to_stderr_without_the_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(verifier, "SqlEvidence", FailingReader)
    stdin = json.dumps({"session": dict.fromkeys(SESSION_KEYS, SECRET_ID), "shown": []})
    out, err = io.StringIO(), io.StringIO()
    env = {"DALE_VERIFIER_DATABASE_URL": "postgresql+psycopg://v@127.0.0.1/d"}
    assert verifier.run(io.StringIO(stdin), out, env, err) == 0
    assert json.loads(out.getvalue())["reason"] == "ConnectionRefusedError"
    assert "builtins.ConnectionRefusedError" in err.getvalue() and "read" in err.getvalue()
    bad = io.StringIO()
    verifier.run(io.StringIO(stdin.replace("shown", "seen")), io.StringIO(), env, bad)
    assert "ValueError" in bad.getvalue()
    assert SECRET_ID not in err.getvalue() + bad.getvalue()

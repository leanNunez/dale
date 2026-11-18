"""The real `python -m dale.verifier` process, spawned by the runner against the seeded database
as dale_verifier: the runtime path the terminal and the eval harness use (design §9)."""

import pytest
from sqlalchemy import Engine

from dale.apps.verifier_runner import request_json, run_verifier
from tests.conftest import role_url
from tests.integration.test_verifier import confirmed

pytestmark = pytest.mark.integration


def test_the_process_verifies_a_real_order_and_reports_a_lie(
    db: Engine, engines: dict[str, Engine], caplog: pytest.LogCaptureFixture
) -> None:
    at, summary, shown = confirmed(db)
    ids = (at.company_id, at.customer_id, at.conversation_id)
    url = role_url("dale_verifier")
    verdict = run_verifier(request_json(*ids, [summary, shown]), url)
    assert verdict.verified and verdict.findings[0].order_id == shown.order_id
    lie = run_verifier(request_json(*ids, [summary]), url)  # the order was never shown
    assert (lie.verdict, lie.unexpected_writes, lie.verified) == ("unexpected_write", 1, False)
    owner = run_verifier(request_json(*ids, [summary, shown]), role_url("dale_owner"))
    assert (owner.verdict, owner.reason) == ("unverifiable", "PermissionError")
    assert "builtins.PermissionError" in caplog.records[-1].getMessage()  # the child's stderr

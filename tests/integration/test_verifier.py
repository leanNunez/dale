"""The verifier on a real database, as dale_verifier (R11, R12): verified on a real confirmed
order, not verified once the database differs, and never able to write (S11.3)."""

from dataclasses import replace
from uuid import uuid4

import psycopg
import pytest
import sqlalchemy as sa
from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import DBAPIError

from dale.brain.domain.session import SessionContext
from dale.erp_sim.infrastructure import tables as erp
from dale.erp_sim.infrastructure.seed import el_hornero
from dale.shared.ids import ConversationId, ProposalId
from dale.shared.shown_events import OrderConfirmed, ProposalSummary, ShownEvent
from dale.verifier.application.verify import Request, report_to_json, verify
from dale.verifier.domain.verdict import Report, Session, Verdict
from dale.verifier.infrastructure import evidence
from dale.verifier.infrastructure.evidence import SqlEvidence
from tests.conftest import role_url
from tests.integration.test_confirm_proposal import press
from tests.integration.test_proposals import DAY, NOW, TWIN, grounded, order, session

pytestmark = pytest.mark.integration


def confirmed(db: Engine) -> tuple[SessionContext, ProposalSummary, OrderConfirmed]:
    at = session(db)
    summary = order(grounded(db, at), 20)
    shown = press(db, at, summary.proposal_id)
    assert isinstance(shown, OrderConfirmed)
    return at, summary, shown


def check(engine: Engine, at: SessionContext, *shown: ShownEvent) -> Report:
    ids = Session(at.company_id, at.customer_id, at.conversation_id)
    return verify(Request(ids, shown), SqlEvidence(engine))


def test_a_real_confirmed_order_is_verified(db: Engine, engines: dict[str, Engine]) -> None:
    """S11.1, on an order written by management through the Dale key."""
    at, summary, shown = confirmed(db)
    report = check(engines["dale_verifier"], at, summary, shown, shown)
    assert report.verdict is Verdict.VERIFIED
    assert [(f.proposal_id, f.order_id) for f in report.findings] == [
        (shown.proposal_id, shown.order_id)
    ]


@pytest.mark.parametrize(
    ("tamper", "fields"),
    [
        ("UPDATE erp.sales_order SET total_cents = total_cents + 1", ("message", "total")),
        (
            "UPDATE erp.sales_order SET delivery_date = delivery_date + 7",
            ("delivery_date", "delivery_rule", "message"),
        ),
        (
            "UPDATE erp.sales_order_line SET qty = qty - 1, line_total_cents = line_total_cents"
            " - unit_price_cents",
            ("lines", "total"),
        ),
        (
            "UPDATE brain.order_proposal_line SET qty = qty + 1,"
            " line_total_cents = line_total_cents + unit_price_cents",
            ("lines",),
        ),
    ],
)
def test_the_database_tampered_by_the_owner_is_a_mismatch(
    db: Engine, engines: dict[str, Engine], tamper: str, fields: tuple[str, ...]
) -> None:
    """S11.2: what was shown no longer matches what is stored."""
    at, _, shown = confirmed(db)
    with engines["dale_owner"].begin() as conn:
        conn.exec_driver_sql(tamper)
    report = check(engines["dale_verifier"], at, shown)
    assert report.verdict is Verdict.MISMATCH and report.findings[0].fields == fields


def test_other_customers_orders_are_not_in_the_run(db: Engine, engines: dict[str, Engine]) -> None:
    """B79: of the orders received since the conversation started, only the session's own."""
    at, summary, shown = confirmed(db)
    other = {"company_id": at.company_id, "id": uuid4(), "proposal_id": uuid4()}
    other["customer_id"] = el_hornero.row_id("customer", "C-002")
    with db.begin() as conn:
        rest = {"delivery_date": DAY, "total_cents": 1, "received_at": NOW}
        conn.execute(sa.insert(erp.sales_order), other | rest)
    report = check(engines["dale_verifier"], at, summary, shown)
    verdict = report_to_json(report)
    assert report.verdict is Verdict.VERIFIED, verdict
    assert str(other["id"]) not in verdict and str(other["proposal_id"]) not in verdict


def test_missing_and_unexpected_write(db: Engine, engines: dict[str, Engine]) -> None:
    """S12.1: shown confirmed, no order. And an order that nobody was shown confirmed."""
    at, summary, shown = confirmed(db)
    reader = engines["dale_verifier"]
    assert check(reader, at, summary).verdict is Verdict.UNEXPECTED_WRITE
    elsewhere = replace(shown, proposal_id=ProposalId(uuid4()))
    assert check(reader, at, shown, elsewhere).verdict is Verdict.MISSING
    with engines["dale_owner"].begin() as conn:
        conn.exec_driver_sql("DELETE FROM erp.sales_order_line; DELETE FROM erp.sales_order")
    assert check(reader, at, shown).verdict is Verdict.MISSING


def test_a_run_that_cannot_be_read_is_unverifiable(db: Engine, engines: dict[str, Engine]) -> None:
    """Fail closed (§13): no conversation row, another company's key, the writer's role, or a
    database that does not answer. None of them is verified."""
    at, _, shown = confirmed(db)
    nowhere = create_engine(role_url("dale_verifier").replace("/dale_test", "/no_such_db"))
    cases = [
        (
            engines["dale_verifier"],
            replace(at, conversation_id=ConversationId(uuid4())),
            "LookupError",
        ),
        (engines["dale_verifier"], replace(at, company_id=TWIN), "LookupError"),
        (engines["dale_app"], at, "PermissionError"),
        (nowhere, at, "OperationalError"),
    ]
    for engine, session_ids, reason in cases:
        report = check(engine, session_ids, shown)
        assert (report.verdict, report.reason) == (Verdict.UNVERIFIABLE, reason)
    nowhere.dispose()


def test_any_write_through_the_verifier_is_denied(engines: dict[str, Engine]) -> None:
    """S11.3: the snapshot is read-only, and the role holds no write grant either."""
    with pytest.raises(DBAPIError) as err, SqlEvidence(engines["dale_verifier"]).snapshot() as c:
        c.exec_driver_sql("DELETE FROM erp.sales_order")
    assert isinstance(err.value.orig, psycopg.Error) and err.value.orig.sqlstate == "25006"


def test_every_statement_is_scoped_by_company() -> None:
    statements = [v for v in vars(evidence).values() if isinstance(v, sa.TextClause)]
    assert len(statements) == 6
    assert all("company_id = :company" in s.text for s in statements)

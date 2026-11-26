"""The stored orders in the verdict (D19, R11): the orders the verifier read, as it read them,
sorted by (received_at, id). They are evidence for the page, never something judged, and the
runner believes them only when they agree with the findings."""

import json
from dataclasses import replace
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest

from dale.apps.verifier_runner import VerifierVerdict, parse_verdict, unverifiable
from dale.channels.common.backend import Verdict as ChannelVerdict
from dale.shared.money import Money
from dale.verifier.application.verify import report_to_json
from dale.verifier.domain.verdict import Report, Verdict
from tests.unit.verifier import test_verdict
from tests.unit.verifier.test_verdict import AGUA, AT, COLA, OID, ORDER, PID, SESSION, SHOWN, run

LATER = replace(ORDER, id=UUID(int=95), proposal_id=UUID(int=94), received_at=AT + timedelta(1))
TWIN = replace(ORDER, id=UUID(int=5), proposal_id=UUID(int=92))  # same time, smaller id
OTHERS = UUID(int=99)  # another customer of the same company


def test_the_report_carries_every_order_it_read_by_received_at_then_id() -> None:
    assert run(SHOWN, orders=(LATER, ORDER, TWIN)).stored == (TWIN, ORDER, LATER)


def test_verified_mismatch_and_missing_carry_the_order_as_read_or_none() -> None:
    """S11.1, S11.2 (the stored total, not the one shown), S11.4 (explicitly absent)."""
    assert run(SHOWN).stored == (ORDER,)
    wrong = run(replace(SHOWN, total=Money(1)))
    assert wrong.verdict is Verdict.MISMATCH and wrong.stored[0].total_cents == 5_000_000
    missing = run(SHOWN, orders=())
    assert missing.verdict is Verdict.MISSING and missing.stored == ()


def test_an_unverifiable_report_holds_no_order() -> None:
    assert Report.unverifiable("timeout").stored == ()
    with pytest.raises(ValueError):
        Report(Verdict.UNVERIFIABLE, reason="timeout", stored=(ORDER,))


def test_the_json_emits_the_stored_orders_without_the_company() -> None:
    (stored,) = json.loads(report_to_json(run(SHOWN)))["stored_orders"]
    line = {"quantity": 20, "unit_price_cents": 245_000, "line_total_cents": 4_900_000}
    water = {"quantity": 2, "unit_price_cents": 50_000, "line_total_cents": 100_000}
    assert stored == {
        "id": str(OID),
        "proposal_id": str(PID),
        "customer_id": str(SESSION.customer_id),
        "lines": [{"product_id": str(COLA)} | line, {"product_id": str(AGUA)} | water],
        "total_cents": 5_000_000,
        "delivery_date": "2026-11-19",
        "received_at": AT.isoformat(),
    }
    assert json.loads(report_to_json(run(SHOWN, orders=())))["stored_orders"] == []


def test_the_runner_reads_the_stored_orders_back() -> None:
    verdict = parse_verdict(report_to_json(run(SHOWN, orders=(ORDER, LATER))).encode())
    assert verdict.verdict == "unexpected_write"
    assert [o.id for o in verdict.stored_orders] == [OID, LATER.id]
    first = verdict.stored_orders[0]
    assert (first.received_at, first.delivery_date) == (AT, ORDER.delivery_date)
    assert first.lines[0].product_id == COLA and first.lines[0].unit_price_cents == 245_000
    assert unverifiable("timeout").stored_orders == ()


VERIFIED: dict[str, Any] = json.loads(report_to_json(run(SHOWN)))
ONE = VERIFIED["stored_orders"][0]


@pytest.mark.parametrize(
    "changes",
    [
        {"stored_orders": None},  # dropped below: an old or partial output
        {"stored_orders": []},  # the verified finding names an order nobody read
        {"stored_orders": [ONE, ONE]},  # ids are unique
        {"stored_orders": [ONE | {"company_id": str(SESSION.company_id)}]},
        {"stored_orders": [ONE | {"total_cents": "5000000"}]},  # strict types
        {"verdict": "unverifiable", "reason": "timeout", "findings": [], "false_confirmations": 0},
        {"stored_orders": [ONE | {"proposal_id": str(LATER.proposal_id)}]},  # P with Q's order
        {"verdict": "nothing_confirmed", "findings": []},  # an order read, nothing named it
        {"stored_orders": [ONE, ONE | {"id": str(LATER.id), "proposal_id": str(UUID(int=94))}]},
    ],
)
def test_a_verdict_whose_stored_orders_disagree_is_malformed(changes: dict[str, Any]) -> None:
    forged = VERIFIED | changes
    if forged["stored_orders"] is None:
        del forged["stored_orders"]
    verdict = parse_verdict(json.dumps(forged).encode())
    assert (verdict.verdict, verdict.reason) == ("unverifiable", "malformed_output")


@pytest.mark.parametrize(
    "report",
    [
        run(SHOWN),
        run(replace(SHOWN, total=Money(1)), orders=(ORDER, replace(LATER, customer_id=OTHERS))),
        run(SHOWN, orders=()),
        run(SHOWN, orders=(ORDER, LATER)),
        run(SHOWN, test_verdict.CLAIM, orders=(ORDER, replace(TWIN, proposal_id=PID))),
    ],
)
def test_every_verdict_the_child_can_print_is_believed(report: Report) -> None:
    """Verified; mismatch with another customer's write; missing; unexpected write; order_count
    with a claim."""
    assert parse_verdict(report_to_json(report).encode()).verdict == report.verdict.value


def test_another_customers_order_appears_only_by_id_in_its_finding() -> None:
    text = report_to_json(run(SHOWN, orders=(replace(ORDER, customer_id=OTHERS),)))
    (finding,) = json.loads(text)["findings"]
    assert "customer" in finding["fields"] and finding["order_id"] == str(OID)
    assert json.loads(text)["stored_orders"] == [] and str(COLA) not in text
    assert parse_verdict(text.encode()).verdict == "mismatch"
    both = json.loads(report_to_json(run(SHOWN, orders=(ORDER, LATER))))
    both["stored_orders"][1]["customer_id"] = str(OTHERS)  # forged: two customers' orders
    assert parse_verdict(json.dumps(both).encode()).reason == "malformed_output"


def test_a_channel_still_reads_only_the_verdict_the_reason_and_the_counts() -> None:
    """Design §5 compatibility: the terminal's protocol did not grow; the runner still meets it."""
    read = {name for name in vars(ChannelVerdict) if not name.startswith("_")}
    assert read == {"verdict", "reason", "false_confirmations", "unexpected_writes"}
    verdict: ChannelVerdict = parse_verdict(json.dumps(VERIFIED).encode())
    assert isinstance(verdict, VerifierVerdict) and verdict.verdict == "verified"

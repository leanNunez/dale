"""The verify use case: a strict request, and any failure to read or judge is unverifiable."""

import json
from collections.abc import Collection
from dataclasses import replace
from typing import Any
from uuid import UUID

import pytest

from dale.shared.shown_events import AssistantText, to_json
from dale.verifier.application.verify import Request, parse_request, report_to_json, verify
from dale.verifier.domain.verdict import Evidence, Session, Verdict
from tests.unit.verifier.test_verdict import EVIDENCE, OID, PID, SESSION, SHOWN

IDS = {"company_id": str(UUID(int=1)), "customer_id": str(UUID(int=2))}
IDS["conversation_id"] = str(UUID(int=3))


def body(**changes: Any) -> str:
    request = {"session": IDS, "shown": [json.loads(to_json(SHOWN))]} | changes
    return json.dumps(request)


class Reader:
    def __init__(self, evidence: Evidence | Exception) -> None:
        self.evidence, self.asked = evidence, list[Collection[UUID]]()

    def read(self, session: Session, shown: Collection[UUID]) -> Evidence:
        self.asked.append(shown)
        if isinstance(self.evidence, Exception):
            raise self.evidence
        return self.evidence


def test_a_request_round_trips_and_asks_only_for_the_shown_confirmations() -> None:
    request = parse_request(body())
    assert request == Request(SESSION, (SHOWN,))
    reader = Reader(EVIDENCE)
    report = verify(Request(SESSION, (AssistantText("hola"), SHOWN)), reader)
    assert report.verdict is Verdict.VERIFIED and reader.asked == [{PID}]
    assert json.loads(report_to_json(report)) == {
        "verdict": "verified",
        "reason": "",
        "findings": [
            {"kind": "verified", "proposal_id": str(PID), "order_id": str(OID), "fields": []}
        ],
        "false_confirmations": 0,
        "unexpected_writes": 0,
    }


@pytest.mark.parametrize(
    "text",
    [
        "",
        "[]",
        "[" * 100_000,
        body(extra=1),
        body(session=IDS | {"company_id": 1}),
        body(session=IDS | {"customer_id": "not-a-uuid"}),
        body(session={k: v for k, v in IDS.items() if k != "conversation_id"}),
        body(shown={}),
        body(shown=[{"type": "OrderConfirmed"}]),
        body(shown=[{"type": "Verified", "text": "x"}]),
    ],
)
def test_any_other_request_shape_is_rejected(text: str) -> None:
    with pytest.raises(ValueError):
        parse_request(text)


@pytest.mark.parametrize("error", [RuntimeError("db down"), LookupError("no row"), KeyError(1)])
def test_a_reader_that_fails_makes_the_run_unverifiable(error: Exception) -> None:
    report = verify(Request(SESSION, (SHOWN,)), Reader(error))
    assert (report.verdict, report.reason) == (Verdict.UNVERIFIABLE, type(error).__name__)
    assert json.loads(report_to_json(report))["verdict"] == "unverifiable"


def test_evidence_that_cannot_be_judged_makes_the_run_unverifiable() -> None:
    garbled = replace(EVIDENCE, zone="Thursdays")  # type: ignore[arg-type]
    assert verify(Request(SESSION, (SHOWN,)), Reader(garbled)).verdict is Verdict.UNVERIFIABLE

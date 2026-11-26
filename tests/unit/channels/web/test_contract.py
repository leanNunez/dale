"""Contract v1 event types (W3): samples round-trip, output is strict and consistent."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from dale.brain.application.take_turn import MAX_TRACE_NAME
from dale.channels.web.contract import WebEvent
from dale.shared import shown_events

SAMPLES = Path(__file__).parents[4] / "contracts" / "v1" / "samples"
EVENTS = TypeAdapter(WebEvent)
PROPOSAL = "00000000-0000-4000-8000-000000000002"
OC, VI = "event_order_confirmed", "event_verdict_issued"


def sample(name: str) -> str:
    return (SAMPLES / f"{name}.json").read_text(encoding="utf-8")


def event_samples() -> list[Path]:
    return sorted(SAMPLES.glob("event_*.json"))


@pytest.mark.parametrize("path", event_samples(), ids=lambda p: p.stem)
def test_an_event_serializes_and_parses_back_equal(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    event = EVENTS.validate_json(text)
    assert json.loads(EVENTS.dump_json(event)) == json.loads(text)  # serialized == original
    assert EVENTS.validate_json(EVENTS.dump_json(event)) == event  # parsed again == original


def test_shown_event_data_is_the_verifiers_json_form() -> None:
    """One form serves both readers (D20): `data` is `to_json` without `type`."""
    for path in event_samples():
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw["type"] in shown_events.KINDS:
            line = json.dumps({"type": raw["type"], **raw["data"]})
            assert EVENTS.validate_json(json.dumps(raw)).data == shown_events.from_json(line)


BAD_EVENTS: list[dict[str, Any]] = [
    {"seq": 0},  # seq starts at 1
    {"v": 2},  # unknown contract version
    {"extra": 1},  # unknown envelope field
    {"type": "Nope"},  # unknown event type
    {"data": {"text": "x", "price": 1}},  # unknown data field
]


@pytest.mark.parametrize("change", BAD_EVENTS, ids=lambda c: next(iter(c)))
def test_an_event_that_breaks_the_envelope_rules_is_rejected(change: dict[str, Any]) -> None:
    raw = json.loads(sample("event_assistant_text")) | change
    with pytest.raises(ValidationError):
        EVENTS.validate_json(json.dumps(raw))


def mutated(name: str, path: tuple[str | int, ...], value: Any) -> str:
    raw = node = json.loads(sample(name))
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return json.dumps(raw)


@pytest.mark.parametrize(
    ("name", "path", "value"),
    [
        (OC, ("data", "total"), {"cents": "370000"}),  # output types coerce nothing
        (OC, ("data", "total", "cents"), 370000.0),
        (OC, ("data", "lines", 0, "quantity"), "2"),
        (OC, ("seq",), True),
        (OC, ("v",), 1.0),
        (OC, ("v",), True),
        (OC, ("data", "delivery_date"), 20261120),
        ("event_tool_called", ("data", "ok"), "yes"),
        ("event_tool_called", ("data", "name"), "x" * (MAX_TRACE_NAME + 1)),
        (VI, ("data", "stored_orders", 0, "delivery_date"), "2026-11-20T00:00:00Z"),
        (VI, ("data", "stored_orders", 0, "delivery_date"), 20261120),
        (VI, ("data", "stored_orders", 0, "received_at"), "2026-11-19T15:30:00"),  # naive
        (VI, ("data", "reason"), "exit_1"),  # apps.web maps it to verifier_error
    ],
)
def test_a_loose_or_inconsistent_output_value_is_rejected(
    name: str, path: tuple[str | int, ...], value: Any
) -> None:
    parse = EVENTS.validate_json
    parse(sample(name))  # the canonical sample parses
    with pytest.raises(ValidationError):
        parse(mutated(name, path, value))


MISMATCH = {"kind": "mismatch", "proposal_id": PROPOSAL, "order_id": None, "fields": ["total"]}


@pytest.mark.parametrize(
    "change",
    [
        {"reason": "timeout", "findings": [MISMATCH], "stored_orders": []},  # verified + reason
        {"false_confirmations": 1},  # the counts disagree with the findings
        {"verdict": "mismatch"},  # a verified finding makes verified
        {"verdict": "unverifiable", "reason": ""},  # unverifiable needs a reason
        {"findings": [MISMATCH | {"fields": []}], "verdict": "mismatch"},  # a mismatch names fields
        {"findings": [MISMATCH | {"kind": "verified", "fields": []}]},  # verified names its order
    ],
)
def test_a_verdict_the_runner_would_not_believe_is_rejected(change: dict[str, Any]) -> None:
    raw = json.loads(sample(VI))
    raw["data"] |= change
    with pytest.raises(ValidationError):
        EVENTS.validate_json(json.dumps(raw))


def test_an_unverifiable_verdict_carries_only_its_reason() -> None:
    raw = json.loads(sample(VI))
    raw["data"] |= {"verdict": "unverifiable", "reason": "verifier_error"}
    raw["data"] |= {"findings": [], "stored_orders": [], "false_confirmations": 0}
    assert EVENTS.validate_json(json.dumps(raw)).type == "VerdictIssued"

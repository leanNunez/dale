"""Contract v1 types (W3, W4): samples round-trip, output is strict and consistent, commands
are closed, components are typed."""

import json
from pathlib import Path
from typing import Any, get_args

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from dale.brain.application.take_turn import MAX_TRACE_NAME
from dale.channels.web.contract import (
    COMMANDS,
    COMPONENTS,
    ErrorBody,
    ResponseEnvelope,
    SendMessage,
    WebEvent,
)
from dale.channels.web.errors import WebErrorCode, message_for
from dale.shared import shown_events
from dale.shared.errors import ErrorCode

SAMPLES = Path(__file__).parents[4] / "contracts" / "v1" / "samples"
EVENTS = TypeAdapter(WebEvent)
CONVERSATION = "00000000-0000-4000-8000-000000000001"
PROPOSAL = "00000000-0000-4000-8000-000000000002"
OC, VI, ENVELOPE = "event_order_confirmed", "event_verdict_issued", "response_envelope"


def sample(name: str) -> str:
    return (SAMPLES / f"{name}.json").read_text(encoding="utf-8")


def event_samples() -> list[Path]:
    return sorted(SAMPLES.glob("event_*.json"))


def test_there_is_one_event_sample_per_event_type() -> None:
    types = {json.loads(p.read_text(encoding="utf-8"))["type"] for p in event_samples()}
    assert types == set(COMPONENTS)
    assert len(event_samples()) == len(COMPONENTS)


@pytest.mark.parametrize("path", event_samples(), ids=lambda p: p.stem)
def test_an_event_serializes_and_parses_back_equal(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    event = EVENTS.validate_json(text)
    assert json.loads(EVENTS.dump_json(event)) == json.loads(text)  # serialized == original
    assert EVENTS.validate_json(EVENTS.dump_json(event)) == event  # parsed again == original


def test_the_envelope_sample_round_trips_with_its_typed_events() -> None:
    text = sample("response_envelope")
    envelope = ResponseEnvelope.model_validate_json(text)
    assert [e.seq for e in envelope.events] == [1, 2]
    assert json.loads(envelope.model_dump_json()) == json.loads(text)


@pytest.mark.parametrize(
    ("name", "command"),
    [
        ("command_send_message", "SendMessage"),
        ("command_press_dale", "PressDale"),
        ("command_cancel_proposal", "CancelProposal"),
    ],
)
def test_a_well_formed_command_is_accepted(name: str, command: str) -> None:
    parsed = COMMANDS[command].model_validate_json(sample(name))
    assert json.loads(parsed.model_dump_json()) == json.loads(sample(name))


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
        (ENVELOPE, ("v",), 1.0),
        (ENVELOPE, ("seq",), 1),  # not the last event's seq
        (ENVELOPE, ("events", 0, "conversation_id"), PROPOSAL),  # another conversation
    ],
)
def test_a_loose_or_inconsistent_output_value_is_rejected(
    name: str, path: tuple[str | int, ...], value: Any
) -> None:
    parse = ResponseEnvelope.model_validate_json if name == ENVELOPE else EVENTS.validate_json
    parse(sample(name))  # the canonical sample parses
    with pytest.raises(ValidationError):
        parse(mutated(name, path, value))


def test_an_envelope_without_events_carries_the_conversations_last_seq() -> None:
    assert ResponseEnvelope.model_validate_json(mutated(ENVELOPE, ("events",), [])).seq == 2


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


def test_an_error_carries_only_its_catalog_message() -> None:
    for code in [*WebErrorCode, *ErrorCode]:
        assert ErrorBody(code=code, message=message_for(code)).message == message_for(code)
    with pytest.raises(ValidationError):  # no exception text can enter the envelope
        ErrorBody(code=WebErrorCode.INTERNAL_ERROR, message="KeyError: 'customer_id'")


@pytest.mark.parametrize(
    ("command", "body"),
    [
        (SendMessage, {"text": ""}),  # 1 to 2000 characters
        (SendMessage, {"text": "x" * 2001}),
        (SendMessage, {"text": "hola", "total": 100}),  # a client total (S7.4)
        (SendMessage, {"text": "hola", "customer_id": CONVERSATION}),  # S14.2
        (SendMessage, {}),
        (SendMessage, {"text": 5}),
        (SendMessage, {"text": b"hola"}),  # a real string, not coerced
        (SendMessage, {"text": " \n\t "}),  # blank after stripping
        (SendMessage, {"text": "hola\x00"}),  # a control character
        (SendMessage, {"text": "hola\x1b[2J"}),
        (SendMessage, {"text": "hola\r"}),
        (COMMANDS["PressDale"], {"proposal_id": "not-a-uuid"}),
        (COMMANDS["PressDale"], {"proposal_id": f"urn:uuid:{PROPOSAL}"}),  # only format: uuid
        (COMMANDS["PressDale"], {"proposal_id": f"{{{PROPOSAL}}}"}),
        (COMMANDS["CancelProposal"], {"proposal_id": PROPOSAL.replace("-", "")}),
        (COMMANDS["PressDale"], {"proposal_id": PROPOSAL, "unit_price": {"cents": 1}}),
        (COMMANDS["PressDale"], {"proposal_id": PROPOSAL, "company_id": CONVERSATION}),
        (COMMANDS["CancelProposal"], {"proposal_id": PROPOSAL, "customer_id": CONVERSATION}),
    ],
)
def test_a_malformed_or_overreaching_command_is_rejected(
    command: type[BaseModel], body: dict[str, Any]
) -> None:
    with pytest.raises(ValidationError):
        command.model_validate(body)


def test_the_page_still_has_the_three_commands_of_v02() -> None:
    assert {"SendMessage", "PressDale", "CancelProposal"} <= set(COMMANDS)
    assert SendMessage(text="x" * 2000).text == "x" * 2000
    assert SendMessage(text="dos\n\tbolsas").text == "dos\n\tbolsas"
    assert COMMANDS["PressDale"].model_validate({"proposal_id": PROPOSAL.upper()})


def test_the_trace_and_the_verdict_are_web_events_outside_the_shown_events() -> None:
    shown = {kind.__name__ for kind in get_args(shown_events.ShownEvent.__value__)}
    assert {"ToolCalled", "VerdictIssued"}.isdisjoint(shown)
    assert {"ToolCalled", "VerdictIssued"} <= set(COMPONENTS)


def test_every_event_type_maps_to_a_typed_component_and_none_is_untyped() -> None:
    variants = get_args(get_args(WebEvent)[0].__value__)
    types = {v.model_fields["type"].default for v in variants}
    assert set(COMPONENTS) == types  # no event type without a component, no stray entry
    assert set(COMPONENTS.values()) == {
        "ChatText",
        "OrderSummary",
        "OrderConfirmation",
        "Notice",
        "HandoffNotice",
        "ToolTrace",
        "Verdict",
    }

"""Shown events are frozen and survive a JSON round trip; any other JSON is rejected."""

import dataclasses
import json
from datetime import date
from uuid import UUID

import pytest

from dale.shared.errors import ErrorCode, message_for
from dale.shared.ids import OrderId, ProductId, ProposalId
from dale.shared.money import Money
from dale.shared.shown_events import (
    KINDS,
    AssistantText,
    HandoffNotice,
    OrderConfirmed,
    OrderRejected,
    ProposalSummary,
    ShownEvent,
    ShownLine,
    SystemNotice,
    from_json,
    to_json,
)

LINE = ShownLine(ProductId(UUID(int=7)), 20, Money(245_000), Money(4_900_000))
PROPOSAL, DAY = ProposalId(UUID(int=1)), date(2026, 11, 19)
EVENTS: list[ShownEvent] = [
    AssistantText("te armé una propuesta, confirmá con Dale"),
    ProposalSummary(PROPOSAL, (LINE, LINE), Money(9_800_000), DAY),
    OrderConfirmed(OrderId(UUID(int=2)), PROPOSAL, (LINE,), Money(4_900_000), DAY, "Listo."),
    OrderRejected(PROPOSAL, ErrorCode.PRICE_CHANGED, message_for(ErrorCode.PRICE_CHANGED)),
    HandoffNotice("Una persona del equipo va a revisar tu pedido."),
    SystemNotice(ErrorCode.TURN_LIMIT_REACHED, message_for(ErrorCode.TURN_LIMIT_REACHED)),
]


@pytest.mark.parametrize("event", EVENTS, ids=lambda e: type(e).__name__)
def test_every_event_round_trips_and_is_frozen(event: ShownEvent) -> None:
    assert from_json(to_json(event)) == event
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.message = "x"  # type: ignore[union-attr,misc]


def test_every_kind_is_covered() -> None:
    assert {type(e).__name__ for e in EVENTS} == set(KINDS)


def test_wire_form_is_plain_json() -> None:
    wire = json.loads(to_json(EVENTS[1]))
    assert wire["type"] == "ProposalSummary" and wire["delivery_date"] == "2026-11-19"
    assert wire["lines"][0] == {
        "product_id": str(UUID(int=7)),
        "quantity": 20,
        "unit_price": {"cents": 245_000},
        "line_total": {"cents": 4_900_000},
    }


def _summary(**change: object) -> str:
    wire = json.loads(to_json(EVENTS[1]))
    wire["lines"][0] |= change
    return json.dumps(wire)


@pytest.mark.parametrize(
    "text",
    [
        "[]",
        '{"type": "Shell", "text": "x"}',
        '{"text": "x"}',
        '{"type": "AssistantText", "text": "x", "extra": 1}',
        '{"type": "AssistantText"}',
        '{"type": "AssistantText", "text": 5}',
        '{"type": "SystemNotice", "code": "not_a_code", "message": "x"}',
        _summary(quantity=True),
        _summary(quantity="20"),
        _summary(product_id="cola"),
        _summary(unit_price={"cents": -1}),
        _summary(unit_price_override=1),
        pytest.param("[" * 200_000, id="nested_too_deeply"),
    ],
)
def test_any_other_shape_raises_value_error(text: str) -> None:
    with pytest.raises(ValueError):
        from_json(text)

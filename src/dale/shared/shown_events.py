"""What the customer is shown (design §4), with the JSON form the verifier reads (design §9).

Only `AssistantText` carries model text. Every other event is built by code from stored or
management data, so a summary or a confirmation never repeats model prose.
"""

import json
from dataclasses import dataclass, fields, is_dataclass
from datetime import date
from typing import Any, get_args, get_origin, get_type_hints
from uuid import UUID

from dale.shared.errors import ErrorCode
from dale.shared.ids import OrderId, ProductId, ProposalId
from dale.shared.money import Money


@dataclass(frozen=True, slots=True)
class AssistantText:
    text: str  # the model's words: data to grade, never a source of prices, ids or status


@dataclass(frozen=True, slots=True)
class ShownLine:
    product_id: ProductId
    quantity: int
    unit_price: Money
    line_total: Money


@dataclass(frozen=True, slots=True)
class SummaryLine:
    product_id: ProductId
    name: str  # stored from management's quote (B61): catalog data, shown as plain text
    quantity: int
    unit_price: Money
    line_total: Money


@dataclass(frozen=True, slots=True)
class ProposalSummary:
    """Built from the stored proposal, re-read after the write."""  # S3.3

    proposal_id: ProposalId
    lines: tuple[SummaryLine, ...]
    total: Money
    delivery_date: date


@dataclass(frozen=True, slots=True)
class OrderConfirmed:
    order_id: OrderId
    proposal_id: ProposalId
    lines: tuple[ShownLine, ...]
    total: Money
    delivery_date: date
    message: str  # management's message, built from the stored order


@dataclass(frozen=True, slots=True)
class OrderRejected:
    proposal_id: ProposalId
    code: ErrorCode
    message: str  # the catalog message for `code`


@dataclass(frozen=True, slots=True)
class HandoffNotice:
    message: str  # emitted only after the handoff write succeeds


@dataclass(frozen=True, slots=True)
class SystemNotice:
    code: ErrorCode
    message: str


type ShownEvent = (
    AssistantText | ProposalSummary | OrderConfirmed | OrderRejected | HandoffNotice | SystemNotice
)
KINDS: dict[str, type] = {kind.__name__: kind for kind in get_args(ShownEvent.__value__)}


def to_json(event: ShownEvent) -> str:
    return json.dumps({"type": type(event).__name__, **_dump(event)}, ensure_ascii=False)


def from_json(text: str) -> ShownEvent:
    """The inverse of `to_json`. Any other shape raises ValueError (the verifier fails closed)."""
    try:
        data = json.loads(text)
    except RecursionError as error:  # deeply nested input is just another wrong shape
        raise ValueError("nested too deeply") from error
    if not isinstance(data, dict) or data.get("type") not in KINDS:
        raise ValueError("not a shown event")
    kind = KINDS[data.pop("type")]
    event: ShownEvent = _load(kind, data)
    return event


def _dump(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _dump(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, tuple):
        return [_dump(item) for item in value]
    if isinstance(value, date):
        return value.isoformat()
    return str(value) if isinstance(value, UUID) else value


def _load(kind: Any, raw: Any) -> Any:
    kind = getattr(kind, "__supertype__", kind)  # typed ids are UUIDs
    if isinstance(kind, type) and is_dataclass(kind):
        hints = get_type_hints(kind)
        if not isinstance(raw, dict) or set(raw) != set(hints):
            raise ValueError(f"{kind.__name__} needs exactly {sorted(hints)}")
        return kind(**{name: _load(hints[name], raw[name]) for name in hints})
    if get_origin(kind) is tuple:
        if not isinstance(raw, list):
            raise ValueError("expected a list")
        return tuple(_load(get_args(kind)[0], item) for item in raw)
    if kind in (UUID, date, ErrorCode) and type(raw) is str:
        return date.fromisoformat(raw) if kind is date else kind(raw)
    if kind in (str, int) and type(raw) is kind:  # bool is not an int here
        return raw
    raise ValueError(f"expected {kind}, got {type(raw).__name__}")

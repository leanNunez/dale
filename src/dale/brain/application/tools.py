"""The brain's tools (design §7; R1, R9): strict schemas and handlers that trust no input.

Strict mode takes no length or range keywords, so the schemas state the bounds in prose and
the handlers check them again. Company and customer come only from the SessionContext (D2).
"""

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from dale.brain.application.ports import ErpPort
from dale.brain.domain.session import GroundingLedger, SessionContext
from dale.shared.errors import ErrorCode, Failure, message_for
from dale.shared.ids import ProductId
from dale.shared.money import pesos
from dale.shared.shown_events import ShownEvent

MAX_QUERY, MAX_PRICE_IDS = 100, 20


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    closed = {"required": list(properties), "additionalProperties": False}
    return {"type": "object", "properties": properties, **closed}


def _array(items: dict[str, Any], bounds: str) -> dict[str, Any]:
    return {"type": "array", "items": items, "minItems": 1, "description": bounds}


def _tool(name: str, description: str, **properties: dict[str, Any]) -> dict[str, Any]:
    schema = _object(properties)
    return {"name": name, "description": description, "strict": True, "input_schema": schema}


_ID = {"type": "string", "format": "uuid"}
TOOL_SCHEMAS = (
    _tool(
        "search_products",
        "Searches the catalog; best match first.",
        query={"type": "string", "description": f"1 to {MAX_QUERY} characters"},
    ),
    _tool(
        "get_prices",
        "Current unit prices of products that search_products returned.",
        product_ids=_array(_ID, f"1 to {MAX_PRICE_IDS} ids"),
    ),
    _tool("check_delivery", "The customer's next delivery date, order-by time and minimum."),
)


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class _Search(_Input):
    query: Annotated[str, Field(min_length=1, max_length=MAX_QUERY)]


class _Prices(_Input):
    product_ids: Annotated[list[str], Field(min_length=1, max_length=MAX_PRICE_IDS)]


INPUT_MODELS: dict[str, type[BaseModel]] = {
    "search_products": _Search,
    "get_prices": _Prices,
    "check_delivery": _Input,  # no properties at all
}


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    """The tool result for the model (JSON text) and what code shows the customer."""

    content: str
    is_error: bool = False
    shown: tuple[ShownEvent, ...] = ()


def _ok(payload: dict[str, Any], *shown: ShownEvent) -> ToolOutcome:
    return ToolOutcome(json.dumps(payload, ensure_ascii=False), False, shown)


def _error(code: ErrorCode) -> ToolOutcome:
    payload = {"code": code.value, "message": message_for(code)}
    return ToolOutcome(json.dumps(payload, ensure_ascii=False), True)


def _line(product_id: ProductId, **fields: object) -> dict[str, object]:
    return {"product_id": str(product_id), **fields}


def _parse_ids(values: Iterable[str]) -> tuple[ProductId, ...] | None:
    try:
        return tuple(ProductId(UUID(v)) for v in values)
    except ValueError:
        return None


class Tools:
    """One per conversation: its grounding ledger lives exactly as long as the conversation."""

    def __init__(self, session: SessionContext, erp: ErpPort) -> None:
        self._session, self._erp = session, erp
        self._ledger = GroundingLedger()

    def run(self, name: str, tool_input: object) -> ToolOutcome:
        """Closed dispatch. Input that does not validate has no effect at all."""
        if name not in INPUT_MODELS:
            return _error(ErrorCode.UNKNOWN_TOOL)
        try:
            data = INPUT_MODELS[name].model_validate(tool_input)
        except ValidationError:
            return _error(ErrorCode.INVALID_TOOL_INPUT)
        handler: Callable[[Any], ToolOutcome] = getattr(self, f"_{name}")
        return handler(data)

    def _search_products(self, data: _Search) -> ToolOutcome:
        found = self._erp.search_products(self._session.company_id, data.query)
        if isinstance(found, Failure):
            return _error(found.code)
        self._ledger.record(m.product_id for m in found.value)
        rows = [
            _line(m.product_id, name=m.name, brand=m.brand, size=m.presentation)
            for m in found.value
        ]
        return _ok({"products": rows})

    def _get_prices(self, data: _Prices) -> ToolOutcome:
        if (ids := _parse_ids(data.product_ids)) is None:
            return _error(ErrorCode.INVALID_TOOL_INPUT)
        found = self._erp.get_prices(self._session.company_id, ids)
        if isinstance(found, Failure):
            return _error(found.code)
        self._ledger.record(p.product_id for p in found.value)  # only what the server returned
        rows = [_line(p.product_id, unit_price=pesos(p.unit_price)) for p in found.value]
        return _ok({"prices": rows})

    def _check_delivery(self, _: _Input) -> ToolOutcome:
        found = self._erp.check_delivery(self._session.company_id, self._session.customer_id)
        if isinstance(found, Failure):
            return _error(found.code)
        d = found.value
        when = {"delivery_date": str(d.delivery_date), "order_by": d.order_by.isoformat()}
        return _ok(when | {"minimum": pesos(d.minimum)})

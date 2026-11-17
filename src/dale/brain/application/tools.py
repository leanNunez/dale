"""The brain's tools (design §7; R1, R3, R9): strict schemas and handlers that trust no input.

Strict mode takes no length or range keywords, so the schemas state the bounds in prose and
the handlers check them again. Company and customer come only from the SessionContext (D2);
prices, totals and dates only from `quote`.
"""

import json
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.exc import InterfaceError, OperationalError

from dale.brain.application.ports import ErpPort, ProposalRepository
from dale.brain.domain.proposal import OrderProposal, ProposalLine
from dale.brain.domain.session import GroundingLedger, SessionContext
from dale.erp_sim.public import QuoteLineRequest, QuoteRequest
from dale.shared.errors import ErrorCode, Failure, message_for
from dale.shared.ids import IdGenerator, ProductId, new_proposal_id
from dale.shared.money import pesos
from dale.shared.quantity import MAX_LINE_QUANTITY, MIN_LINE_QUANTITY
from dale.shared.shown_events import ProposalSummary, ShownEvent, ShownLine

logger = logging.getLogger(__name__)
MAX_QUERY, MAX_PRICE_IDS, MAX_LINES = 100, 20, 30
NOT_CONFIRMED = "NOT confirmed: only the customer's Dale key confirms it. Never say it is."


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    closed = {"required": list(properties), "additionalProperties": False}
    return {"type": "object", "properties": properties, **closed}


def _array(items: dict[str, Any], bounds: str) -> dict[str, Any]:
    return {"type": "array", "items": items, "minItems": 1, "description": bounds}


def _tool(name: str, description: str, **properties: dict[str, Any]) -> dict[str, Any]:
    schema = _object(properties)
    return {"name": name, "description": description, "strict": True, "input_schema": schema}


_ID = {"type": "string", "format": "uuid"}
_QTY = {"type": "integer", "description": f"{MIN_LINE_QUANTITY} to {MAX_LINE_QUANTITY}"}
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
    _tool(
        "prepare_order",
        "Prepares a proposal at server prices. It does NOT confirm the order.",
        lines=_array(_object({"product_id": _ID, "quantity": _QTY}), f"1 to {MAX_LINES} lines"),
    ),
)


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class _Search(_Input):
    query: Annotated[str, Field(min_length=1, max_length=MAX_QUERY)]


class _Prices(_Input):
    product_ids: Annotated[list[str], Field(min_length=1, max_length=MAX_PRICE_IDS)]


class _Line(_Input):
    product_id: str  # parsed by the handler: an id that does not parse is ungrounded
    quantity: int  # range checked by the handler, so it gets its own catalog code


class _Prepare(_Input):
    lines: Annotated[list[_Line], Field(min_length=1, max_length=MAX_LINES)]


INPUT_MODELS: dict[str, type[BaseModel]] = {
    "search_products": _Search,
    "get_prices": _Prices,
    "check_delivery": _Input,  # no properties at all
    "prepare_order": _Prepare,
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

    def __init__(
        self, session: SessionContext, erp: ErpPort, proposals: ProposalRepository, ids: IdGenerator
    ) -> None:
        self._session, self._erp, self._proposals, self._ids = session, erp, proposals, ids
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

    def _prepare_order(self, data: _Prepare) -> ToolOutcome:
        if any(not MIN_LINE_QUANTITY <= x.quantity <= MAX_LINE_QUANTITY for x in data.lines):
            return _error(ErrorCode.INVALID_QUANTITY)
        company, ids = self._session.company_id, _parse_ids(x.product_id for x in data.lines)
        if ids is not None and len(set(ids)) < len(ids):  # one line per product: the cap holds
            return _error(ErrorCode.INVALID_TOOL_INPUT)
        if ids is None or not all(self._ledger.grounds(i) for i in ids):
            return _error(ErrorCode.UNGROUNDED_PRODUCT)  # checked before anything is quoted
        asked = tuple(QuoteLineRequest(i, x.quantity) for i, x in zip(ids, data.lines, strict=True))
        quoted = self._erp.quote(company, QuoteRequest(self._session.customer_id, asked))
        if isinstance(quoted, Failure):
            return _error(quoted.code)  # S3.2: nothing is stored
        q, new_id = quoted.value, new_proposal_id(self._ids)
        lines = tuple(
            ProposalLine(x.product_id, x.quantity, x.unit_price, x.line_total) for x in q.lines
        )
        proposal = OrderProposal.prepared(
            new_id, self._session, lines, q.total, q.delivery_date, q.quoted_at
        )
        try:
            stored = self._proposals.save_prepared(company, proposal)
        except (OperationalError, InterfaceError) as error:  # database down; other errors raise
            logger.error("prepare_order failed for company %s: %s", company, type(error).__name__)
            return _error(ErrorCode.RULES_UNAVAILABLE)
        shown = tuple(
            ShownLine(x.product_id, x.quantity, x.unit_price, x.line_total) for x in stored.lines
        )
        summary = ProposalSummary(stored.id, shown, stored.total, stored.delivery_date)  # S3.3
        rows = [
            _line(x.product_id, quantity=x.quantity, unit_price=pesos(x.unit_price)) for x in shown
        ]
        view = {"confirmed": False, "note": NOT_CONFIRMED, "lines": rows}  # and no proposal id
        view |= {"total": pesos(stored.total), "delivery_date": str(stored.delivery_date)}
        return _ok(view, summary)

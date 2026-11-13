"""Tools with fakes (R1, R3, R9, D2): strict schemas, input validation, grounding, and a
prepare_order that stores only quoted prices and shows only the stored proposal."""

import json
import logging
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from anthropic import transform_schema
from sqlalchemy.exc import (
    ArgumentError,
    DataError,
    IntegrityError,
    InterfaceError,
    OperationalError,
    ProgrammingError,
)

from dale.brain.application.shown import order_confirmed
from dale.brain.application.tools import (
    EARLIER_ORDERED,
    HANDOFF_NOTICE,
    HANDOFF_RECORDED,
    INPUT_MODELS,
    NOT_CONFIRMED,
    TOOL_SCHEMAS,
)
from dale.brain.domain.handoff import HandoffReason
from dale.brain.domain.proposal import OrderProposal, ProposalLine, ProposalStatus
from dale.erp_sim.public import OrderConfirmation, OrderLine, Quote, QuoteRequest
from dale.shared.errors import BelowMinimum, ErrorCode, Result
from dale.shared.ids import CompanyId, OrderId, ProposalId, SequentialIdGenerator
from dale.shared.money import Money
from dale.shared.shown_events import HandoffNotice, ProposalSummary, SummaryLine
from tests.unit.brain.fakes import (
    COLA,
    COLA15,
    COMPANY,
    CUSTOMER,
    DAY,
    MATCHES,
    NAME,
    NOW,
    PACK,
    PRICES,
    SESSION,
    UNPRICED,
    FakeErp,
    FakeHandoffs,
    FakeProposals,
    error_code,
    prepare,
    tools,
)


def handoff(**fields: object) -> dict[str, object]:
    return {"reason": "exception_request", "note": "pide bajar el mínimo"} | fields


FORBIDDEN = ("price", "total", "amount", "cents", "company", "customer", "proposal", "date")
OTHER = str(UUID(int=9))


def names(node: object) -> set[str]:
    """Every property name anywhere in a JSON schema (pydantic's `$defs` included)."""
    if isinstance(node, list):
        return set().union(*map(names, node))
    if not isinstance(node, dict):
        return set()
    own = set(node["properties"]) if isinstance(node.get("properties"), dict) else set()
    return own.union(*map(names, node.values()))


def objects(node: object) -> list[dict[str, Any]]:
    if isinstance(node, list):
        return [o for item in node for o in objects(item)]
    if not isinstance(node, dict):
        return []
    found = [o for value in node.values() for o in objects(value)]
    return [node, *found] if node.get("type") == "object" else found


def test_tools_are_closed_strict_and_require_every_property() -> None:
    """R9: exactly five tools, and none confirms (R4): only the Dale key does."""
    assert [s["name"] for s in TOOL_SCHEMAS] == list(INPUT_MODELS)
    assert list(INPUT_MODELS) == [
        "search_products",
        "get_prices",
        "check_delivery",
        "prepare_order",
        "request_human_handoff",
    ]
    assert [n for n in INPUT_MODELS if "confirm" in n] == []
    for schema in TOOL_SCHEMAS:
        assert schema["strict"] is True
        for obj in objects(schema["input_schema"]):
            assert obj["additionalProperties"] is False
            assert obj["required"] == list(obj["properties"])


@pytest.mark.parametrize("schema", TOOL_SCHEMAS, ids=lambda s: s["name"])
def test_schema_is_in_the_strict_subset_and_matches_its_validator(schema: dict[str, Any]) -> None:
    # The SDK moves any keyword strict mode lacks into the description: nothing moves here.
    assert transform_schema(schema["input_schema"]) == schema["input_schema"]
    validator = INPUT_MODELS[schema["name"]].model_json_schema()
    assert names(schema["input_schema"]) == names(validator) - {"_Line"}
    assert [n for n in names(validator) if any(f in n.lower() for f in FORBIDDEN)] == []


@pytest.mark.parametrize(
    ("name", "tool_input", "code"),
    [
        ("prepare_order", prepare((COLA, 20), unit_price=500), "invalid_tool_input"),  # S1.2
        ("prepare_order", prepare((COLA, 20), unit_price_cents=1), "invalid_tool_input"),
        ("prepare_order", prepare((COLA, 20)) | {"company_id": OTHER}, "invalid_tool_input"),
        ("prepare_order", prepare((COLA, 20)) | {"customer_id": OTHER}, "invalid_tool_input"),
        ("prepare_order", prepare((COLA, 20)) | {"total": 1}, "invalid_tool_input"),
        ("prepare_order", prepare((COLA, "20")), "invalid_tool_input"),
        ("prepare_order", prepare((COLA, True)), "invalid_tool_input"),
        ("prepare_order", prepare((COLA, 0)), "invalid_quantity"),
        ("prepare_order", prepare((COLA, 1000)), "invalid_quantity"),
        ("prepare_order", prepare(), "invalid_tool_input"),
        ("prepare_order", prepare(*[(COLA, 1)] * 31), "invalid_tool_input"),
        ("prepare_order", prepare((COLA, 1), (str(COLA).upper(), 1)), "invalid_tool_input"),
        ("search_products", {"query": ""}, "invalid_tool_input"),
        ("search_products", {"query": "x" * 101}, "invalid_tool_input"),
        ("search_products", {"query": 5}, "invalid_tool_input"),
        ("search_products", {"query": "cola", "company_id": OTHER}, "invalid_tool_input"),
        ("get_prices", {"product_ids": [str(COLA)] * 21}, "invalid_tool_input"),
        ("get_prices", {"product_ids": []}, "invalid_tool_input"),
        ("get_prices", {"product_ids": ["cola"]}, "invalid_tool_input"),
        ("get_prices", {"product_ids": str(COLA)}, "invalid_tool_input"),
        ("check_delivery", {"customer_id": OTHER}, "invalid_tool_input"),
        ("check_delivery", None, "invalid_tool_input"),
        ("confirm_order", {}, "unknown_tool"),
        ("request_human_handoff", handoff(note="x" * 501), "invalid_tool_input"),
        ("request_human_handoff", handoff(reason="discount"), "invalid_tool_input"),
        ("request_human_handoff", handoff(reason="agent_refusal"), "invalid_tool_input"),
        ("request_human_handoff", handoff(reason="Complaint"), "invalid_tool_input"),
        ("request_human_handoff", {"reason": "complaint"}, "invalid_tool_input"),
        ("request_human_handoff", handoff(customer_id=OTHER), "invalid_tool_input"),
    ],
)
def test_bad_input_is_an_error_result_with_no_effect(name: str, tool_input: Any, code: str) -> None:
    erp, written = FakeErp(), FakeHandoffs()
    t = tools(erp, handoffs=written)
    outcome = t.run(name, tool_input)
    assert outcome.is_error and error_code(outcome.content) == code and outcome.shown == ()
    assert erp.calls == [] == written.written and not t._ledger.grounds(COLA)


@pytest.mark.parametrize("control", [chr(c) for c in range(0x20)], ids=lambda c: f"U+{ord(c):04X}")
def test_a_control_character_in_any_tool_string_has_no_effect(control: str) -> None:
    """B68: every C0 control character (NUL included) in a query, a note or an id is
    invalid_tool_input before any call or write; other characters, accents and emoji pass."""
    for name, tool_input in (
        ("search_products", {"query": f"cola{control}"}),
        ("get_prices", {"product_ids": [str(COLA) + control]}),
        ("prepare_order", prepare((f"{control}{COLA}", 20))),
        ("request_human_handoff", handoff(note=f"pide{control}bajar el mínimo")),
    ):
        erp, proposals, written = FakeErp(), FakeProposals(), FakeHandoffs()
        outcome = tools(erp, proposals, written).run(name, tool_input)
        assert error_code(outcome.content) == "invalid_tool_input" and outcome.shown == ()
        assert erp.calls == [] == proposals.saved and written.written == []
    fine = tools().run("request_human_handoff", handoff(note="¿Me bajás el mínimo? 🙏\x7f"))
    assert not fine.is_error and not tools().run("search_products", {"query": "ñandú"}).is_error


def test_ambiguous_search_shows_every_match_and_reads_use_the_session() -> None:
    erp = FakeErp()
    t = tools(erp)
    found = json.loads(t.run("search_products", {"query": "cola"}).content)["products"]
    assert [p["product_id"] for p in found] == [str(m.product_id) for m in MATCHES]  # S1.3
    assert found[0] == {"product_id": str(COLA)} | {  # catalog free text is fenced (B62)
        k: f"<catalog_text>{v}</catalog_text>"
        for k, v in {"name": "Gaseosa cola", "brand": "Burbuja", "size": "1 L"}.items()
    }
    prices = json.loads(t.run("get_prices", {"product_ids": [str(COLA)]}).content)
    assert prices == {"prices": [{"product_id": str(COLA), "unit_price": "$ 2.450,00"}]}
    when = json.loads(t.run("check_delivery", {}).content)
    assert when == {"delivery_date": "2026-11-19", "order_by": NOW.isoformat()} | {
        "minimum": "$ 30.000,00"
    }
    assert {company for _, company in erp.calls} == {COMPANY}


def test_reads_ground_only_what_the_server_returned_in_this_conversation() -> None:
    t, other = tools(), tools()
    t.run("get_prices", {"product_ids": [str(COLA), str(UNPRICED)]})  # UNPRICED is left out
    assert t._ledger.grounds(COLA) and not t._ledger.grounds(UNPRICED)
    assert not other._ledger.grounds(COLA)  # another conversation: an empty ledger
    other.run("search_products", {"query": "cola"})
    assert all(other._ledger.grounds(m.product_id) for m in MATCHES)


@pytest.mark.parametrize(
    ("name", "tool_input"),
    [
        ("search_products", {"query": "x"}),
        ("get_prices", {"product_ids": [str(COLA)]}),
        ("check_delivery", {}),
    ],
)
def test_a_failed_read_is_returned_and_grounds_nothing(name: str, tool_input: Any) -> None:
    erp = FakeErp()
    t = tools(erp)
    erp.failure = ErrorCode.RULES_UNAVAILABLE
    assert error_code(t.run(name, tool_input).content) == "rules_unavailable"
    assert not t._ledger.grounds(COLA)


@pytest.mark.parametrize("product_id", [str(UNPRICED), "cola", str(COLA) + "0"])
def test_an_id_no_tool_returned_is_rejected_before_quoting(product_id: str) -> None:
    erp, proposals = FakeErp(), FakeProposals()
    t = tools(erp, proposals)
    t.run("search_products", {"query": "cola"})
    outcome = t.run("prepare_order", prepare((COLA, 1), (product_id, 20)))
    assert error_code(outcome.content) == "ungrounded_product" and outcome.shown == ()
    assert [name for name, _ in erp.calls] == ["search_products"] and proposals.saved == []


def test_product_names_come_from_the_quote_and_the_model_cannot_supply_one() -> None:
    """B61: the stored lines carry management's names; a name in the tool input is refused."""
    proposals = FakeProposals()
    t = tools(proposals=proposals)
    t.run("search_products", {"query": "cola"})
    named = {"lines": [{"product_id": str(COLA), "quantity": 20, "name": "Cola gratis"}]}
    assert error_code(t.run("prepare_order", named).content) == "invalid_tool_input"
    outcome = t.run("prepare_order", prepare((COLA, 20)))
    [(_, saved)] = proposals.saved
    [summary] = outcome.shown
    assert isinstance(summary, ProposalSummary)
    assert [x.name for x in saved.lines] == [x.name for x in summary.lines] == [NAME]
    assert NAME not in outcome.content  # the model sees ids, never the stored names


def test_it_stores_quoted_prices_and_shows_the_stored_proposal() -> None:
    line = ProposalLine(COLA15, "Cola 1,5", 3, Money(185_000), Money(555_000))  # as stored
    first_id = ProposalId(SequentialIdGenerator().new_id())
    later = DAY + timedelta(days=7)  # not the quote's date: what is shown is what was stored
    stored = OrderProposal.prepared(first_id, SESSION, (line,), Money(555_000), later, NOW)
    proposals = FakeProposals(stored)
    t = tools(proposals=proposals)
    t.run("search_products", {"query": "cola"})
    outcome = t.run("prepare_order", prepare((COLA, 20), (PACK, 2)))
    [(company, saved)] = proposals.saved
    assert company == COMPANY and saved.id == stored.id  # from the id generator
    assert (saved.customer_id, saved.conversation_id) == (
        SESSION.customer_id,
        SESSION.conversation_id,
    )
    assert [x.unit_price for x in saved.lines] == [PRICES[COLA], PRICES[PACK]]  # from `quote`
    assert saved.total == Money(6_280_000) and saved.status is ProposalStatus.PREPARED
    shown = (SummaryLine(COLA15, "Cola 1,5", 3, Money(185_000), Money(555_000)),)
    assert outcome.shown == (ProposalSummary(stored.id, shown, Money(555_000), later),)
    body = json.loads(outcome.content)
    assert body["confirmed"] is False and body["note"] == NOT_CONFIRMED
    assert body["lines"] == [{"product_id": str(COLA15), "quantity": 3, "unit_price": "$ 1.850,00"}]
    assert body["total"] == "$ 5.550,00" and str(stored.id) not in outcome.content
    assert body["delivery_date"] == "2026-11-26"


@pytest.mark.parametrize("error", [OperationalError, InterfaceError])
def test_a_failed_proposal_write_is_rules_unavailable(
    caplog: pytest.LogCaptureFixture, error: type[OperationalError]
) -> None:
    down = error("INSERT", {"customer": "secret"}, Exception("down"))
    t = tools(proposals=FakeProposals(error=down))
    t.run("search_products", {"query": "cola"})
    with caplog.at_level(logging.ERROR):
        outcome = t.run("prepare_order", prepare((COLA, 20)))
    assert error_code(outcome.content) == "rules_unavailable" and outcome.shown == ()
    assert caplog.messages == [f"prepare_order failed for company {COMPANY}: {error.__name__}"]


@pytest.mark.parametrize("error", [IntegrityError, ProgrammingError, DataError])
def test_a_bug_in_the_proposal_write_raises(error: type[IntegrityError]) -> None:
    for bug in (error("INSERT", {}, Exception("bug")), ArgumentError("bad statement")):
        t = tools(proposals=FakeProposals(error=bug))
        t.run("search_products", {"query": "cola"})
        with pytest.raises(type(bug)):  # a wiring or data bug is not an outage
            t.run("prepare_order", prepare((COLA, 20)))


@pytest.mark.parametrize(("note", "stored"), [("x" * 500, "x" * 500), ("", None)])
def test_a_written_handoff_alone_shows_the_promise_of_a_person(note: str, stored: Any) -> None:
    """R7: the HandoffNotice comes after the write, and a handoff orders or prepares nothing."""
    erp, proposals, written = FakeErp(), FakeProposals(), FakeHandoffs()
    outcome = tools(erp, proposals, written).run("request_human_handoff", handoff(note=note))
    assert written.written == [(SESSION, HandoffReason.EXCEPTION_REQUEST, stored)]
    assert not outcome.is_error and outcome.shown == (HandoffNotice(HANDOFF_NOTICE),)
    assert json.loads(outcome.content) == {"recorded": True, "note": HANDOFF_RECORDED}
    assert "una persona" in HANDOFF_NOTICE.lower() and erp.calls == [] == proposals.saved


class ShortErp(FakeErp):
    def quote(self, company_id: CompanyId, request: QuoteRequest) -> Result[Quote]:
        code = ErrorCode.BELOW_MINIMUM_AMOUNT
        return BelowMinimum(code, Money(2_940_000), Money(3_000_000))


def test_a_total_below_the_minimum_comes_back_with_management_s_own_figures() -> None:
    """B96: the model may repeat the total and the shortfall; it never computes them."""
    proposals = FakeProposals()
    t = tools(ShortErp(), proposals)
    t.run("search_products", {"query": "cola"})
    outcome = t.run("prepare_order", prepare((COLA, 12)))
    assert outcome.is_error and outcome.shown == () and proposals.saved == []
    assert json.loads(outcome.content) == {
        "code": "below_minimum_amount",
        "message": "El pedido no llega al mínimo de tu zona. Sumá algo más.",
        "total": "$ 29.400,00",
        "minimum": "$ 30.000,00",
        "missing": "$ 600,00",
    }


@pytest.mark.parametrize("error", [OperationalError, InterfaceError])
def test_a_failed_handoff_write_tells_the_model_and_promises_nothing(
    caplog: pytest.LogCaptureFixture, error: type[OperationalError]
) -> None:
    """S7.4: an error result for the model and no HandoffNotice."""
    down = FakeHandoffs(error("INSERT", {"note": "secret"}, Exception("down")))
    with caplog.at_level(logging.ERROR):
        outcome = tools(handoffs=down).run("request_human_handoff", handoff())
    assert error_code(outcome.content) == "rules_unavailable" and outcome.shown == ()
    assert caplog.messages == [
        f"request_human_handoff failed for company {COMPANY}: {error.__name__}"
    ]
    bug = FakeHandoffs(IntegrityError("INSERT", {}, Exception("bug")))
    with pytest.raises(IntegrityError):  # a wiring or data bug is not an outage
        tools(handoffs=bug).run("request_human_handoff", handoff())


ONE, EARLIER_ID = ProposalLine(COLA, NAME, 1, PRICES[COLA], PRICES[COLA]), ProposalId(UUID(int=41))
EARLIER = OrderProposal.prepared(EARLIER_ID, SESSION, (ONE,), ONE.line_total, DAY, NOW)
QUOTED = OrderLine(COLA, 1, ONE.unit_price, ONE.line_total)
ORDERED = OrderConfirmation(
    OrderId(UUID(int=51)), EARLIER_ID, CUSTOMER, (QUOTED,), ONE.line_total, DAY, NOW, "Listo."
)


@pytest.mark.parametrize(("orders", "failure"), [((ORDERED,), None), ((), "rules_unavailable")])
def test_an_earlier_proposal_with_an_order_or_an_unknown_one_is_not_superseded(
    orders: tuple[OrderConfirmation, ...], failure: Any
) -> None:
    """B67, B68: its Dale press may have gone through though the brain never heard the answer.
    An order exists: it is shown and marked, and nothing is prepared; unknown: nothing moves."""
    erp, proposals = FakeErp(*orders), FakeProposals()
    erp.failing, erp.failure = "find_order", failure and ErrorCode(failure)
    proposals.earlier = EARLIER
    t = tools(erp, proposals)
    t.run("search_products", {"query": "cola"})
    outcome = t.run("prepare_order", prepare((COLA, 30)))
    assert ("find_order", COMPANY) in erp.calls and proposals.saved == []
    if failure:
        assert error_code(outcome.content) == failure and outcome.shown == ()
        assert proposals.marks == []
    else:
        body, marks = json.loads(outcome.content), [(EARLIER.id, ORDERED.order_id)]
        assert (body["confirmed"], body["prepared"], body["note"]) == (True, False, EARLIER_ORDERED)
        assert outcome.shown == (order_confirmed(ORDERED),) and proposals.marks == marks

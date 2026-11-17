"""Tool schemas, input validation and the grounding ledger (R1, R9, D2), with a fake ERP."""

import json
from typing import Any
from uuid import UUID

import pytest
from anthropic import transform_schema

from dale.brain.application.tools import INPUT_MODELS, TOOL_SCHEMAS
from dale.shared.errors import ErrorCode
from tests.unit.brain.fakes import COLA, COMPANY, MATCHES, NOW, UNPRICED, FakeErp, error_code, tools

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
    assert [s["name"] for s in TOOL_SCHEMAS] == list(INPUT_MODELS)
    assert list(INPUT_MODELS) == ["search_products", "get_prices", "check_delivery"]
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
    assert names(schema["input_schema"]) == names(validator)
    assert [n for n in names(validator) if any(f in n.lower() for f in FORBIDDEN)] == []


@pytest.mark.parametrize(
    ("name", "tool_input", "code"),
    [
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
    ],
)
def test_bad_input_is_an_error_result_with_no_effect(name: str, tool_input: Any, code: str) -> None:
    erp = FakeErp()
    t = tools(erp)
    outcome = t.run(name, tool_input)
    assert outcome.is_error and error_code(outcome.content) == code and outcome.shown == ()
    assert erp.calls == [] and not t._ledger.grounds(COLA)


def test_ambiguous_search_shows_every_match_and_reads_use_the_session() -> None:
    erp = FakeErp()
    t = tools(erp)
    found = json.loads(t.run("search_products", {"query": "cola"}).content)["products"]
    assert [p["product_id"] for p in found] == [str(m.product_id) for m in MATCHES]  # S1.3
    assert found[0] == {"product_id": str(COLA), "name": "Gaseosa cola", "brand": "Burbuja"} | {
        "size": "1 L"
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

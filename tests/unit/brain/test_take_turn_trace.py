"""The tool trace of a turn (D18, S3.4): one entry per tool call that ran, in call order, read
from the call and its outcome after the tool ran. It is stored only in `TurnResult`."""

import json

from dale.brain.application.model_port import ModelUnavailableError, parse_response
from dale.brain.application.take_turn import MAX_MODEL_CALLS, ToolCallTrace, TurnResult
from dale.brain.application.tools import ToolOutcome
from dale.shared.errors import ErrorCode
from tests.unit.brain.fakes import COLA, FakeErp, prepare, tools
from tests.unit.brain.test_loop import PREPARE, SEARCH, Chat, calls, says
from tests.unit.brain.test_model_port import message


def use(name: str, **tool_input: object) -> dict[str, object]:
    return {"type": "tool_use", "id": f"toolu_{len(name)}", "name": name, "input": tool_input}


def test_one_entry_per_call_in_call_order_with_ok_or_the_error_code() -> None:
    """S3.4: a call names its tool, summarizes its arguments and reports ok or a code."""
    both = parse_response(message(use("search_products", query="cola"), use("x" * 80)))
    done = Chat(both, PREPARE, says("Listo."))("quiero colas")
    lines = json.dumps(prepare((COLA, 20)), separators=(",", ":"), sort_keys=True)
    assert done.trace == (
        ToolCallTrace("search_products", '{"query":"cola"}', True, None),
        ToolCallTrace("x" * 64, "{}", False, ErrorCode.UNKNOWN_TOOL),  # name cut to 64
        ToolCallTrace("prepare_order", lines, True, None),
    )


def test_the_summary_is_canonical_json_of_the_input_cut_to_200() -> None:
    long = calls("search_products", query="ñ" * 500, a=1)
    (entry,) = Chat(long, says("Listo."))("x").trace
    canonical = json.dumps({"a": 1, "query": "ñ" * 500}, ensure_ascii=False, separators=(",", ":"))
    assert entry.summary == canonical[:200] and len(entry.summary) == 200
    assert (entry.ok, entry.code) == (False, ErrorCode.INVALID_TOOL_INPUT)


def test_only_an_error_result_carries_a_code() -> None:
    erp = FakeErp()
    erp.failure, erp.failing = ErrorCode.RULES_UNAVAILABLE, "check_delivery"
    run = tools(erp).run
    assert run("check_delivery", {}).code is ErrorCode.RULES_UNAVAILABLE
    assert run("search_products", {"query": "cola"}).code is None
    assert run("nope", {}).code is ErrorCode.UNKNOWN_TOOL
    assert ToolOutcome("{}").code is None  # the positional constructors keep working


def test_a_failed_or_refused_turn_keeps_the_calls_that_ran() -> None:
    gone = Chat(SEARCH, ModelUnavailableError("down"))("x")
    assert gone.failure is ErrorCode.MODEL_UNAVAILABLE
    assert [t.name for t in gone.trace] == ["search_products"]
    limit = Chat(SEARCH)("x")  # S9.2: the last reply's tools never run, so they are not traced
    assert limit.failure is ErrorCode.TURN_LIMIT_REACHED
    assert len(limit.trace) == MAX_MODEL_CALLS - 1
    refused = Chat(SEARCH, says("", "refusal"))("x")
    assert refused.failure is ErrorCode.MODEL_REFUSAL and len(refused.trace) == 1
    assert Chat(says("Hola."))("hola").trace == ()


def test_a_turn_result_without_a_trace_still_builds() -> None:
    assert TurnResult((), None, ()).trace == ()

"""The one response parser (design §2): live and replay read the API message as JSON into a
ModelResponse, and any shape it does not know is ModelUnavailableError, never a partial answer."""

from typing import Any

import pytest

from dale.brain.application.model_port import (
    ModelUnavailableError,
    ToolCall,
    Usage,
    parse_response,
)

THINKING = {"type": "thinking", "thinking": "busco la cola", "signature": "sig"}
SEARCH = {"type": "tool_use", "id": "toolu_1", "name": "search_products", "input": {"q": "x"}}
USAGE = {"input_tokens": 120, "output_tokens": 30, "cache_read_input_tokens": 900}


def message(*content: dict[str, Any], stop: object = "tool_use", **usage: object) -> Any:
    """An API message as JSON, the shape of `Message.model_dump(mode="json")`."""
    blocks = [
        block | {"citations": None} if block.get("type") == "text" else block for block in content
    ]
    counts = USAGE | {"cache_creation_input_tokens": None, "service_tier": "standard"} | usage
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": "m"} | {
        "content": blocks,
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": counts,
    }


def test_parses_text_tool_calls_usage_and_keeps_the_blocks_to_send_back() -> None:
    text = {"type": "text", "text": "Dejame buscar."}
    redacted = {"type": "redacted_thinking", "data": "opaque"}
    parsed = parse_response(message(THINKING, redacted, text, SEARCH))
    assert parsed.stop_reason == "tool_use" and parsed.text == "Dejame buscar."
    assert parsed.tool_calls == (ToolCall("toolu_1", "search_products", {"q": "x"}),)
    assert parsed.content == (THINKING, redacted, text, SEARCH)  # no citations: null
    assert parsed.usage == Usage(120, 30, 0, 900)  # a null cache count is 0


@pytest.mark.parametrize("stop", ["refusal", "max_tokens", "pause_turn", "a_new_one"])
def test_any_stop_reason_string_is_kept_for_the_loop_to_judge(stop: str) -> None:
    parsed = parse_response(message(stop=stop))
    assert (parsed.stop_reason, parsed.text, parsed.tool_calls, parsed.content) == (
        stop,
        "",
        (),
        (),
    )


@pytest.mark.parametrize(
    "raw",
    [
        message({"type": "server_tool_use", "id": "s", "name": "web_search", "input": {}}),
        message(SEARCH | {"input": "not an object"}),
        message({"type": "text", "text": None}),
        message(THINKING | {"signature": 5}),
        message({"text": "no type"}),
        message(stop=None),
        message(input_tokens=-1),
        message(output_tokens=True),
        {"content": [], "stop_reason": "end_turn"},
        {"content": "texto", "stop_reason": "end_turn", "usage": USAGE},
        [],
    ],
)
def test_an_unknown_shape_is_model_unavailable(raw: Any) -> None:
    with pytest.raises(ModelUnavailableError):
        parse_response(raw)

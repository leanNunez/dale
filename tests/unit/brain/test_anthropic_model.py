"""The live adapter with a mocked client (design §7, §11 "Provider timeout"): no network, no
credentials. Every request carries the timeout and turns the SDK's retries off (the adapter's own
loop is in test_anthropic_retry.py), and is built from the one settings value, in the effort
field of the pinned SDK; any SDK error is ModelUnavailableError."""

import inspect
from dataclasses import fields, replace
from typing import Any, get_args, get_type_hints
from unittest.mock import MagicMock

import anthropic
import httpx2
import pytest
from anthropic.resources.messages import Messages
from anthropic.types import Message, OutputConfigParam

from dale.brain.application.model_port import (
    MODEL_SETTINGS,
    ModelRequest,
    ModelSettings,
    ModelUnavailableError,
    parse_response,
)
from dale.brain.infrastructure import anthropic_model as live
from tests.unit.brain.test_model_port import SEARCH, THINKING, message

REQUEST = ModelRequest(({"text": "reglas"},), ({"name": "x"},), ({"role": "user"},))


def client(reply: Any = None, error: Exception | None = None) -> MagicMock:
    mock = MagicMock()
    create = mock.with_options.return_value.messages.create
    create.return_value, create.side_effect = reply, error
    return mock


def test_every_request_carries_the_timeout_retries_and_model_constants() -> None:
    raw = message(THINKING, SEARCH)
    mock = client(Message.model_validate(raw))
    parsed = live.AnthropicModel(mock).complete(REQUEST)
    mock.with_options.assert_called_once_with(timeout=live.TIMEOUT_SECONDS, max_retries=0)
    assert 0 < live.TIMEOUT_SECONDS <= 120 and live.MAX_ATTEMPTS == 3  # our loop (DD29)
    mock.with_options.return_value.messages.create.assert_called_once_with(
        model="claude-haiku-5-5",
        max_tokens=16_000,
        output_config={"effort": "medium"},
        tool_choice={"type": "auto"},
        system=list(REQUEST.system),
        tools=list(REQUEST.tools),
        messages=list(REQUEST.messages),
    )
    mock.messages.create.assert_not_called()  # never the bare client, with no timeout
    assert parsed == parse_response(raw)  # the SDK object and the JSON parse alike (replay)


OTHER = ModelSettings("claude-other", "high", 1_234, "any")


def test_the_call_is_built_from_the_settings_and_nothing_else() -> None:
    """D9: what the fingerprint hashes is exactly what is sent, besides the request itself."""
    mock = client(Message.model_validate(message(SEARCH)))
    live.AnthropicModel(mock, OTHER).complete(REQUEST)
    sent = mock.with_options.return_value.messages.create.call_args.kwargs
    assert (
        sent
        == live.request_params(OTHER, REQUEST)
        == {
            "model": "claude-other",
            "max_tokens": 1_234,
            "output_config": {"effort": "high"},
            "tool_choice": {"type": "any"},
            "system": list(REQUEST.system),
            "tools": list(REQUEST.tools),
            "messages": list(REQUEST.messages),
        }
    )
    assert live.AnthropicModel(mock).settings == MODEL_SETTINGS


@pytest.mark.parametrize("field", [f.name for f in fields(ModelSettings)])
def test_every_setting_reaches_the_call(field: str) -> None:
    changed = replace(MODEL_SETTINGS, **{field: getattr(OTHER, field)})
    assert live.request_params(changed, REQUEST) != live.request_params(MODEL_SETTINGS, REQUEST)


def test_the_effort_field_and_the_refusal_stop_exist_in_the_pinned_sdk() -> None:
    assert anthropic.__version__ == "2.8.0"
    assert "output_config" in inspect.signature(Messages.create).parameters
    effort = get_type_hints(OutputConfigParam)["effort"]
    assert MODEL_SETTINGS.effort in get_args(get_args(effort)[0])  # Optional[Literal[...]]
    assert "refusal" in get_args(anthropic.types.StopReason)


TIMED_OUT = anthropic.APITimeoutError(httpx2.Request("POST", "https://api.invalid/v1/messages"))


@pytest.mark.parametrize("error", [anthropic.AnthropicError("boom"), TIMED_OUT])
def test_an_sdk_error_is_model_unavailable(error: Exception) -> None:
    with pytest.raises(ModelUnavailableError):
        live.AnthropicModel(client(error=error), sleep=lambda _: None).complete(REQUEST)


def test_the_raw_message_of_the_last_call_is_kept_for_the_eval_recorder() -> None:
    raw = message(SEARCH)
    model = live.AnthropicModel(client(Message.model_validate(raw)))
    assert model.last_raw is None
    model.complete(REQUEST)
    assert model.last_raw == Message.model_validate(raw).model_dump(mode="json")

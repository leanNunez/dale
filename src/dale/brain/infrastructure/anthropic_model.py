"""The live model behind `ModelPort` (design §7). The client is built with no arguments: the
environment holds the credentials and no code here reads them. Each request carries its own
timeout and retry budget through `with_options`; any SDK error is `ModelUnavailableError`."""

from typing import Any

import anthropic

from dale.brain.application.model_port import (
    MODEL_SETTINGS,
    Json,
    ModelRequest,
    ModelResponse,
    ModelSettings,
    ModelUnavailableError,
    parse_response,
)

TIMEOUT_SECONDS, MAX_RETRIES = 60.0, 2


def request_params(settings: ModelSettings, request: ModelRequest) -> dict[str, Any]:
    """The whole call: the settings, in the fields of anthropic 2.8.0, and the request."""
    return {
        "model": settings.model,
        "max_tokens": settings.max_tokens,
        "output_config": {"effort": settings.effort},  # docs/decisions/0001
        "tool_choice": {"type": settings.tool_choice},
        "system": list(request.system),
        "tools": list(request.tools),
        "messages": list(request.messages),
    }


class AnthropicModel:
    def __init__(
        self, client: anthropic.Anthropic | None = None, settings: ModelSettings = MODEL_SETTINGS
    ) -> None:
        self._client = client if client is not None else anthropic.Anthropic()
        self.settings = settings  # what a recorded run's fingerprint must be taken from
        self.last_raw: Json | None = None  # the last reply as JSON: what an eval records

    def complete(self, request: ModelRequest) -> ModelResponse:
        client = self._client.with_options(timeout=TIMEOUT_SECONDS, max_retries=MAX_RETRIES)
        try:
            message = client.messages.create(**request_params(self.settings, request))
        except anthropic.AnthropicError as error:  # connection, timeout, status, anything
            raise ModelUnavailableError(type(error).__name__) from error
        self.last_raw = message.model_dump(mode="json")
        return parse_response(self.last_raw)

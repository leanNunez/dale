"""The models an eval run can name (design §7, D23; R13).

`COMPARED` holds the settings of each compared model, built from `MODEL_SETTINGS` with only the
model replaced, so the effort, `max_tokens` and `tool_choice` are the same for every one of
them. The fingerprint hashes the settings, so a recording made for one model never replays under
another (S13.8). The prompt, the system blocks and the tools are not touched here.
"""

from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType
from typing import Final

from dale.brain.application.model_port import MODEL_SETTINGS, ModelSettings

HAIKU: Final = "claude-haiku-5-5"
SONNET: Final = "claude-sonnet-5-5"
COMPARED: Final[Mapping[str, ModelSettings]] = MappingProxyType(
    {model: replace(MODEL_SETTINGS, model=model) for model in (HAIKU, SONNET)}
)
DEFAULT_MODEL: Final = MODEL_SETTINGS.model


class UnknownModelError(ValueError):
    """The name is not one of the compared models."""


def settings_for(model: str) -> ModelSettings:
    try:
        return COMPARED[model]
    except KeyError:
        raise UnknownModelError(f"{model!r} is not a compared model: {sorted(COMPARED)}") from None

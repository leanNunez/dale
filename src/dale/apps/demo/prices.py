"""The runtime price table of the spend cap (DD39, O4): US dollars per million tokens (MTok)
per model, as `Decimal`, never a float. `dale` never imports `evals`, so this is a copy of
`evals/pricing.toml`; a unit test and the release check (G4 S4.6) compare the two, so a price
change lands in both files in one commit. A prompt (input + cache writes + cache reads) above
`threshold` tokens is billed at `long_context`, every other at `standard`."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import Final


class NoPriceError(LookupError):
    """The model has no entry: a demo host refuses to start (S4.8)."""


@dataclass(frozen=True, slots=True)
class Tier:
    """US dollars per MTok, which is micro-USD per token."""

    input: Decimal
    output: Decimal
    cache_write_5m: Decimal
    cache_read: Decimal


@dataclass(frozen=True, slots=True)
class ModelPrices:
    threshold: int  # tokens: a prompt above it takes `long_context`
    standard: Tier
    long_context: Tier
    retrieved: date  # when the prices were read from the live pricing page

    def tier(self, prompt_tokens: int) -> Tier:
        return self.long_context if prompt_tokens > self.threshold else self.standard


def _tier(input: str, output: str, cache_write_5m: str, cache_read: str) -> Tier:
    return Tier(Decimal(input), Decimal(output), Decimal(cache_write_5m), Decimal(cache_read))


PRICES: Final[Mapping[str, ModelPrices]] = MappingProxyType(
    {
        "claude-haiku-5-5": ModelPrices(
            100_000,
            _tier("0.10", "0.50", "0.125", "0.01"),
            _tier("0.50", "2.50", "0.625", "0.05"),
            date(2026, 11, 26),
        ),
        "claude-sonnet-5-5": ModelPrices(  # no long-context tier: both are the same
            1_000_000,
            _tier("2.00", "10.00", "2.50", "0.10"),
            _tier("2.00", "10.00", "2.50", "0.10"),
            date(2026, 11, 26),
        ),
    }
)


def prices_for(model: str) -> ModelPrices:
    try:
        return PRICES[model]
    except KeyError:
        raise NoPriceError(f"no runtime price entry for {model}") from None

"""Model prices and what a request costs (design §10, task 13.3, B89).

`evals/pricing.toml` holds, for each compared model, the prices in US dollars per MTok, the
source and the retrieval date. A model with no table has no prices: `load_pricing` raises
instead of returning another model's (S14.4).
A request costs `input*p_in + cache_creation*p_cw + cache_read*p_cr + output*p_out`, at the
long-context tier when that request's prompt tokens (input + cache writes + cache reads) exceed
the threshold. Money is `Decimal`, never a float.

Prices carry at most three decimals per MTok, so a request's cost is exact at 9 decimal places
and a sum of them too. Only a quotient (the cost per verified order) is not, and `round_money`
rounds it to 9 places, half up.
"""

import tomllib
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Final

from dale.brain.application.model_port import Usage

PRICING_FILE: Final = Path(__file__).parents[1] / "pricing.toml"
PER_MTOK: Final = Decimal(1_000_000)
MONEY_PLACES: Final = Decimal("1e-9")


class PricingError(ValueError):
    """The model has no prices, or the file is malformed."""


@dataclass(frozen=True, slots=True)
class Tier:
    """US dollars per MTok."""

    input: Decimal
    output: Decimal
    cache_write_5m: Decimal
    cache_read: Decimal


@dataclass(frozen=True, slots=True)
class Pricing:
    model: str
    threshold: int
    standard: Tier
    long_context: Tier
    source_url: str
    retrieved: date
    note: str


def load_pricing(model: str, path: Path | None = None) -> Pricing:
    """The prices of one model. Raises `PricingError` when the file has no table for it, and on
    a missing key or a malformed file; a float is read through its text, so 0.125 is exactly
    0.125. `path` defaults to `PRICING_FILE`, read at call time."""
    raw = tomllib.loads((path or PRICING_FILE).read_text(encoding="utf-8"))
    tables = raw.get("models", {})
    if model not in tables:
        raise PricingError(f"no pricing table for {model} in pricing.toml (add it with its source)")
    prices = tables[model]

    def tier(name: str) -> Tier:
        table = prices[name]
        return Tier(*(Decimal(str(table[key])) for key in Tier.__slots__))

    source = prices["source"]
    return Pricing(
        model,
        prices["long_context_threshold_tokens"],
        tier("standard"),
        tier("long_context"),
        source["url"],
        date.fromisoformat(source["retrieved"]),
        source["note"],
    )


def request_cost(usage: Usage, pricing: Pricing) -> Decimal:
    prompt = usage.input_tokens + usage.cache_creation_input_tokens + usage.cache_read_input_tokens
    tier = pricing.long_context if prompt > pricing.threshold else pricing.standard
    return (
        usage.input_tokens * tier.input
        + usage.cache_creation_input_tokens * tier.cache_write_5m
        + usage.cache_read_input_tokens * tier.cache_read
        + usage.output_tokens * tier.output
    ) / PER_MTOK


def round_money(amount: Decimal) -> Decimal:
    return amount.quantize(MONEY_PLACES, ROUND_HALF_UP)

"""Pricing (task 13.3; S14.1, S14.2): the price file and what a request costs."""

import tomllib
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from dale.brain.application.model_port import MODEL_SETTINGS, Usage
from evals.harness.pricing import (
    PRICING_FILE,
    PricingError,
    load_pricing,
    request_cost,
    round_money,
)

PRICING = load_pricing(MODEL_SETTINGS.model)


def test_cost_adds_the_four_token_kinds_each_at_its_own_price() -> None:
    usage = Usage(input_tokens=10, output_tokens=20, cache_creation_input_tokens=30)
    usage = replace(usage, cache_read_input_tokens=40)  # a prompt of 80 tokens: standard tier
    expected = 10 * Decimal("0.10") + 20 * Decimal("0.50") + 30 * Decimal("0.125")
    expected += 40 * Decimal("0.01")
    assert request_cost(usage, PRICING) == expected / 1_000_000


def test_the_long_context_tier_applies_per_request_over_the_threshold() -> None:
    at, over = Usage(input_tokens=100_000), Usage(input_tokens=100_001)
    assert request_cost(at, PRICING) == Decimal("0.01")  # 100,000 tokens x $0.10/MTok
    assert request_cost(over, PRICING) == Decimal("0.0500005")  # all of it at $0.50/MTok


def test_the_threshold_counts_cache_tokens_in_the_prompt() -> None:
    split = Usage(input_tokens=50_000, cache_read_input_tokens=50_001)
    assert (
        request_cost(split, PRICING)
        == (50_000 * Decimal("0.50") + 50_001 * Decimal("0.05")) / 1_000_000
    )


def test_money_is_rounded_to_nine_places_half_up() -> None:
    assert round_money(Decimal("1E-7") / 3) == Decimal("0.000000033")
    assert round_money(Decimal("0.0000000125")) == Decimal("0.000000013")  # half goes up
    assert round_money(Decimal("0.0900005")) == Decimal("0.0900005")  # already exact: unchanged


def test_every_priced_model_has_all_four_prices_for_both_tiers_and_its_source() -> None:
    tables = tomllib.loads(PRICING_FILE.read_text(encoding="utf-8"))["models"]
    assert MODEL_SETTINGS.model in tables  # the shipped model is always priced
    keys = {"input", "output", "cache_write_5m", "cache_read"}
    for model, raw in tables.items():
        assert set(raw) == {"long_context_threshold_tokens", "source", "standard", "long_context"}
        assert set(raw["standard"]) == set(raw["long_context"]) == keys, model
        assert all(
            isinstance(v, int | float) and v > 0
            for t in ("standard", "long_context")
            for v in raw[t].values()
        )
        source = raw["source"]
        assert set(source) == {"url", "retrieved", "note"}, model
        assert source["url"].startswith("https://platform.claude.com/") and source["note"]
        assert date.fromisoformat(str(source["retrieved"]))


TWO_MODELS = """
[models."model-a"]
long_context_threshold_tokens = 10

[models."model-a".source]
url = "https://platform.claude.com/model-a"
retrieved = "2026-01-01"
note = "a"

[models."model-a".standard]
input = 1
output = 2
cache_write_5m = 3
cache_read = 4

[models."model-a".long_context]
input = 5
output = 6
cache_write_5m = 7
cache_read = 8
"""


def test_each_model_is_priced_from_its_own_table_and_source(tmp_path: Path) -> None:
    file = tmp_path / "pricing.toml"
    file.write_text(
        TWO_MODELS + TWO_MODELS.replace("model-a", "model-b").replace("input = 1", "input = 9"),
        encoding="utf-8",
    )
    a, b = load_pricing("model-a", file), load_pricing("model-b", file)
    assert (a.model, a.standard.input, a.source_url, a.threshold) == (
        "model-a",
        Decimal(1),
        "https://platform.claude.com/model-a",
        10,
    )
    assert (b.model, b.standard.input, b.source_url) == (
        "model-b",
        Decimal(9),
        "https://platform.claude.com/model-b",
    )


def test_a_model_with_no_table_has_no_prices_and_borrows_none(tmp_path: Path) -> None:
    """S14.4: asking for another model never returns the first table."""
    file = tmp_path / "pricing.toml"
    file.write_text(TWO_MODELS, encoding="utf-8")
    with pytest.raises(PricingError, match="no pricing table for model-c"):
        load_pricing("model-c", file)
    with pytest.raises(PricingError, match="no pricing table for model-c"):
        load_pricing("model-c")  # nor does the shipped file
    file.write_text("", encoding="utf-8")
    with pytest.raises(PricingError, match="no pricing table"):
        load_pricing("model-a", file)


def test_the_pricing_values_are_the_recorded_ones_and_name_the_model_in_use() -> None:
    assert PRICING.model == MODEL_SETTINGS.model and PRICING.threshold == 100_000
    assert (PRICING.standard.input, PRICING.long_context.output) == (
        Decimal("0.10"),
        Decimal("2.5"),
    )
    assert PRICING.retrieved == date(2026, 11, 16)
    assert "live page on 2026-11-16" in PRICING.note and "5-minute" in PRICING.note


def test_no_price_has_more_than_three_decimals_so_nine_places_are_exact() -> None:
    for tier in (PRICING.standard, PRICING.long_context):
        for price in (tier.input, tier.output, tier.cache_write_5m, tier.cache_read):
            assert price == price.quantize(Decimal("0.001"))

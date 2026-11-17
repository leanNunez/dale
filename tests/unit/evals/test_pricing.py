"""Pricing (task 13.3; S14.1, S14.2): the price file and what a request costs."""

import tomllib
from dataclasses import replace
from datetime import date
from decimal import Decimal

from dale.brain.application.model_port import MODEL_SETTINGS, Usage
from evals.harness.pricing import PRICING_FILE, load_pricing, request_cost, round_money

PRICING = load_pricing()


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


def test_the_pricing_file_has_all_four_prices_for_both_tiers() -> None:
    raw = tomllib.loads(PRICING_FILE.read_text(encoding="utf-8"))
    keys = {"input", "output", "cache_write_5m", "cache_read"}
    assert set(raw["standard"]) == set(raw["long_context"]) == keys
    assert all(
        isinstance(v, int | float) and v > 0
        for t in ("standard", "long_context")
        for v in raw[t].values()
    )
    assert (
        raw["source"]["url"].startswith("https://platform.claude.com/")
        and raw["source"]["retrieved"]
    )


def test_the_pricing_values_are_the_recorded_ones_and_name_the_model_in_use() -> None:
    assert PRICING.model == MODEL_SETTINGS.model and PRICING.threshold == 100_000
    assert (PRICING.standard.input, PRICING.long_context.output) == (
        Decimal("0.10"),
        Decimal("2.5"),
    )
    assert PRICING.retrieved == date(2026, 11, 3)
    assert "STALE" in PRICING.note and "multipliers" in PRICING.note


def test_no_price_has_more_than_three_decimals_so_nine_places_are_exact() -> None:
    for tier in (PRICING.standard, PRICING.long_context):
        for price in (tier.input, tier.output, tier.cache_write_5m, tier.cache_read):
            assert price == price.quantize(Decimal("0.001"))

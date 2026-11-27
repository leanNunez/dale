"""The runtime price table equals the eval pricing file (DD39, G4 S4.6): the same models, and
for each the same tiers, threshold and retrieval date, read through the harness's own loader."""

import tomllib
from dataclasses import replace
from decimal import Decimal

import pytest

from dale.apps.demo.prices import PRICES, ModelPrices, NoPriceError, prices_for
from dale.brain.application.model_port import MODEL_SETTINGS
from evals.harness.pricing import PRICING_FILE, Tier, load_pricing

EVAL_MODELS = sorted(tomllib.loads(PRICING_FILE.read_text(encoding="utf-8"))["models"])


def as_eval_tier(tier: object) -> Tier:
    return Tier(*(getattr(tier, name) for name in Tier.__slots__))


def test_the_runtime_table_names_the_same_models_as_the_pricing_file() -> None:
    assert sorted(PRICES) == EVAL_MODELS


@pytest.mark.parametrize("model", EVAL_MODELS)
def test_each_entry_equals_the_pricing_file(model: str) -> None:
    pricing, runtime = load_pricing(model), PRICES[model]
    assert runtime.threshold == pricing.threshold
    assert as_eval_tier(runtime.standard) == pricing.standard
    assert as_eval_tier(runtime.long_context) == pricing.long_context
    assert runtime.retrieved == pricing.retrieved


def test_the_tier_field_names_match_the_harness() -> None:
    entry = PRICES[MODEL_SETTINGS.model]
    assert type(entry.standard).__slots__ == Tier.__slots__


def test_every_price_is_a_decimal_never_a_float() -> None:
    for entry in PRICES.values():
        for tier in (entry.standard, entry.long_context):
            assert all(type(getattr(tier, n)) is Decimal for n in Tier.__slots__)


def test_a_drifted_price_is_seen_by_the_comparison() -> None:
    entry = PRICES[MODEL_SETTINGS.model]
    drifted = replace(entry, standard=replace(entry.standard, output=Decimal("0.51")))
    assert as_eval_tier(drifted.standard) != load_pricing(MODEL_SETTINGS.model).standard


def test_the_shipped_model_has_an_entry_and_an_unknown_one_raises() -> None:
    assert isinstance(prices_for(MODEL_SETTINGS.model), ModelPrices)
    with pytest.raises(NoPriceError, match="claude-unknown"):
        prices_for("claude-unknown")


@pytest.mark.parametrize(("prompt", "tier"), [(100_000, "standard"), (100_001, "long_context")])
def test_the_tier_changes_only_above_the_threshold(prompt: int, tier: str) -> None:
    entry = PRICES["claude-haiku-5-5"]
    assert entry.tier(prompt) is getattr(entry, tier)

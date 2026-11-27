"""The spend cap's arithmetic (DD38): the reservation of an attempt and the cost of its usage,
in integer micro-USD rounded up, with the cost equal to the eval harness's formula. The check
against every committed recording is a replay test of its own (slice 6a2, log D43)."""

import json
from decimal import Decimal

import pytest

from dale.apps.demo.ledger import (
    FRAMING_TOKENS,
    cost_micros,
    prompt_bound,
    reference_request,
    reserve_micros,
)
from dale.apps.demo.prices import PRICES
from dale.brain.application.fencing import customer_message
from dale.brain.application.model_port import MODEL_SETTINGS, ModelRequest, Usage
from dale.brain.application.prompt import system_blocks
from dale.brain.application.tools import TOOL_SCHEMAS
from evals.harness.pricing import load_pricing, request_cost

HAIKU, SONNET = "claude-haiku-5-5", "claude-sonnet-5-5"
EMPTY = ModelRequest((), (), ())  # "[[],[],[]]": 10 bytes
MAX_TOKENS = MODEL_SETTINGS.max_tokens


def text_request(text: str) -> ModelRequest:
    return ModelRequest((), (), ({"role": "user", "content": text},))


def bounded(total: int) -> ModelRequest:
    """A request whose bound is exactly `total` tokens."""
    return text_request("a" * (total - prompt_bound(text_request(""))))


def usage(i: int = 0, o: int = 0, cw: int = 0, cr: int = 0) -> Usage:
    return Usage(i, o, cw, cr)


USAGES = [
    usage(),
    usage(1),
    usage(cr=1),  # 0.01 micro-USD: rounded up to 1
    usage(3_120, 210, 0, 9_800),
    usage(2_000, 16_000, 6_000, 0),
    usage(100_000, 50),  # the threshold itself: standard
    usage(99_999, 1, 1, 0),  # still 100,000 prompt tokens
    usage(100_001, 50),  # one token above: long context for Haiku
    usage(60_000, 900, 30_000, 20_000),  # 110,000 prompt tokens over three kinds
]


@pytest.mark.parametrize("model", [HAIKU, SONNET])
@pytest.mark.parametrize("used", USAGES)
def test_the_cost_is_the_harness_formula_in_micros_rounded_up(model: str, used: Usage) -> None:
    exact = request_cost(used, load_pricing(model)) * 1_000_000
    cost = cost_micros(used, PRICES[model])
    assert type(cost) is int
    assert cost - 1 < exact <= cost


@pytest.mark.parametrize(
    ("used", "micros"),
    [
        (usage(), 0),
        (usage(cr=1), 1),
        (usage(1), 1),  # 0.10
        (usage(10), 1),  # exactly 1.00
        (usage(11), 2),  # 1.10
        (usage(100_000), 10_000),  # standard: 0.10 per token
        (usage(100_001), 50_001),  # long context: 0.50 per token, 50,000.5 rounded up
        (usage(0, 1_000, 8), 501),  # 500 + 1 for the writes
    ],
)
def test_haiku_costs_by_hand(used: Usage, micros: int) -> None:
    assert cost_micros(used, PRICES[HAIKU]) == micros


def test_the_bound_is_the_utf8_bytes_of_canonical_json_plus_the_framing() -> None:
    assert prompt_bound(EMPTY) == len("[[],[],[]]") + FRAMING_TOKENS
    request = text_request("ñandú")
    sent = json.dumps(
        [[], [], list(request.messages)], ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    assert prompt_bound(request) == len(sent.encode()) + FRAMING_TOKENS
    assert prompt_bound(request) == prompt_bound(text_request("nandu")) + 2  # ñ and ú: 2 bytes
    keys = ModelRequest(({"b": 1, "a": 2},), (), ())
    assert prompt_bound(keys) == len('[[{"a":2,"b":1}],[],[]]') + FRAMING_TOKENS


def test_the_reservation_by_hand() -> None:
    # 2,010 tokens at the cache-write price 0.125 (251.25) plus 16,000 at 0.50 (8,000).
    assert reserve_micros(EMPTY, MAX_TOKENS, PRICES[HAIKU]) == 8_252
    # Sonnet: 2,010 at 2.50 plus 16,000 at 10.
    assert reserve_micros(EMPTY, MAX_TOKENS, PRICES[SONNET]) == 165_025
    assert reserve_micros(EMPTY, 0, PRICES[HAIKU]) == 252  # 251.25 rounded up


@pytest.mark.parametrize(
    ("bound", "prompt_price", "output_price"),
    [(100_000, Decimal("0.125"), Decimal("0.50")), (100_001, Decimal("0.625"), Decimal("2.50"))],
)
def test_the_bound_selects_the_tier_at_the_threshold(
    bound: int, prompt_price: Decimal, output_price: Decimal
) -> None:
    request = bounded(bound)
    assert prompt_bound(request) == bound
    expected = bound * prompt_price + MAX_TOKENS * output_price
    assert reserve_micros(request, MAX_TOKENS, PRICES[HAIKU]) == int(expected.to_integral_value())


@pytest.mark.parametrize("model", [HAIKU, SONNET])
@pytest.mark.parametrize("bound", [2_100, 100_000, 100_001, 400_000])
def test_any_usage_inside_the_bound_costs_at_most_the_reservation(model: str, bound: int) -> None:
    request, prices = bounded(bound), PRICES[model]
    reserved = reserve_micros(request, MAX_TOKENS, prices)
    p = bound - FRAMING_TOKENS // 2
    splits = [
        usage(bound, MAX_TOKENS),
        usage(0, MAX_TOKENS, bound),
        usage(0, MAX_TOKENS, 0, bound),
        usage(bound // 3, MAX_TOKENS, bound // 3, bound - 2 * (bound // 3)),
        usage(p, MAX_TOKENS, bound - p),
    ]
    assert all(cost_micros(u, prices) <= reserved for u in splits)


def test_the_reference_request_is_a_first_turn_with_the_longest_message() -> None:
    request = reference_request("El Hornero")
    assert request.system == system_blocks("El Hornero")
    assert request.tools == TOOL_SCHEMAS
    assert request.messages == (customer_message("x" * 2_000),)


def test_an_empty_day_has_room_for_the_reference_request() -> None:
    reserved = reserve_micros(reference_request("El Hornero"), MAX_TOKENS, PRICES[HAIKU])
    assert 8_000 < reserved < 500_000  # above its output alone, under the default cap (log D6)

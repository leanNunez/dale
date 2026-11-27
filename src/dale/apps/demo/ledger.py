"""The spend cap's arithmetic (DD38, O4). Money is integer micro-USD, and every rounding is up.

A price is US dollars per MTok, which is micro-USD per token, so a cost in micro-USD is tokens
times prices, exact as a `Decimal` (prices carry at most three decimals), then rounded up.

- `prompt_bound`: an upper bound of a request's input tokens, the UTF-8 bytes of its canonical
  JSON (system, tools, messages) plus `FRAMING_TOKENS`. A token encodes at least one byte; the
  replay test over every recording checks the bound (design §10, §13).
- `reserve_micros`: the worst case of one attempt, at the tier the bound selects, the bound at
  the dearest prompt price (so any split into input, cache writes and cache reads is covered)
  plus `max_tokens` at the output price.
- `cost_micros`: the actual cost from the reported usage, the formula of
  `evals/harness/pricing.py`, in micro-USD and rounded up.
- `reference_request`: the system blocks, the tool schemas and one 2,000-character customer
  message as the brain fences it, the smallest request a turn can make; while today's spend
  leaves no room for it, a new turn or conversation is refused (design §4 step 6).
"""

import json
from decimal import ROUND_CEILING, Context, Decimal, localcontext

from dale.apps.demo.prices import ModelPrices
from dale.brain.application.fencing import customer_message
from dale.brain.application.model_port import ModelRequest, Usage
from dale.brain.application.prompt import system_blocks
from dale.brain.application.tools import TOOL_SCHEMAS

FRAMING_TOKENS = 2_000
REFERENCE_MESSAGE_CHARACTERS = 2_000  # the web contract's longest customer text
EXACT = Context(prec=40)  # far above any token count times a price: no product is rounded


def _micros(*terms: tuple[int, Decimal]) -> int:
    """The sum of tokens times prices in whole micro-USD, rounded up."""
    with localcontext(EXACT):
        total = sum((count * price for count, price in terms), Decimal(0))
        return int(total.to_integral_value(rounding=ROUND_CEILING))


def prompt_bound(request: ModelRequest) -> int:
    sent = [list(request.system), list(request.tools), list(request.messages)]
    text = json.dumps(sent, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return len(text.encode()) + FRAMING_TOKENS


def reserve_micros(request: ModelRequest, max_tokens: int, prices: ModelPrices) -> int:
    bound = prompt_bound(request)
    tier = prices.tier(bound)
    prompt = max(tier.input, tier.cache_write_5m, tier.cache_read)
    return _micros((bound, prompt), (max_tokens, tier.output))


def cost_micros(usage: Usage, prices: ModelPrices) -> int:
    prompt = usage.input_tokens + usage.cache_creation_input_tokens + usage.cache_read_input_tokens
    tier = prices.tier(prompt)
    return _micros(
        (usage.input_tokens, tier.input),
        (usage.cache_creation_input_tokens, tier.cache_write_5m),
        (usage.cache_read_input_tokens, tier.cache_read),
        (usage.output_tokens, tier.output),
    )


def reference_request(company_name: str) -> ModelRequest:
    message = customer_message("x" * REFERENCE_MESSAGE_CHARACTERS)
    return ModelRequest(system_blocks(company_name), TOOL_SCHEMAS, (message,))

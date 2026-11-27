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

`SqlSpendLedger` is the demo's `AttemptGate` (DD27, O4). `admit` reserves the worst case on the
Buenos Aires day's row of `demo.spend_day` in one conditional update, so two attempts can never
both take the last room, and opens a `demo.spend_request` row; `settle` replaces the reservation
with the cost of the usage, or keeps it when the usage is unknown (log D15). A crash between
the two keeps the reservation. Every failure to read or write refuses (fail closed); `settle`
never raises (log D29).
"""

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_CEILING, Context, Decimal, localcontext
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from dale.apps.demo.prices import PRICES, ModelPrices
from dale.apps.demo.tables import TOKENS, spend_day, spend_request
from dale.brain.application.fencing import customer_message
from dale.brain.application.model_port import AttemptTicket, ModelRequest, ModelSettings, Usage
from dale.brain.application.prompt import system_blocks
from dale.brain.application.tools import TOOL_SCHEMAS
from dale.shared.clock import Clock

FRAMING_TOKENS = 2_000
REFERENCE_MESSAGE_CHARACTERS = 2_000  # the web contract's longest customer text
EXACT = Context(prec=40)  # far above any token count times a price: no product is rounded
DAY_ZONE = ZoneInfo("America/Argentina/Buenos_Aires")  # a spend day is a calendar day there
logger = logging.getLogger(__name__)


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


def spend_day_of(instant: datetime) -> date:
    return instant.astimezone(DAY_ZONE).date()


@dataclass(frozen=True, slots=True)
class Reservation:
    """What `admit` reserved: a ticket's reference."""

    id: UUID
    day: date
    model: str
    reserved: int


class SqlSpendLedger:
    def __init__(
        self,
        engine: sa.Engine,
        cap_micros: int,
        clock: Clock,
        *,
        prices: Mapping[str, ModelPrices] = PRICES,
    ) -> None:
        self._engine, self._cap, self._clock, self._prices = engine, cap_micros, clock, prices

    def admit(self, settings: ModelSettings, request: ModelRequest) -> AttemptTicket | None:
        model = settings.model
        if (prices := self._prices.get(model)) is None:
            return None
        reserved = reserve_micros(request, settings.max_tokens, prices)
        now, row = self._clock.now(), uuid4()
        day, taken = spend_day_of(now), None
        try:
            with self._engine.begin() as conn:
                taken = conn.execute(_reserve(day, reserved, self._cap)).scalar_one_or_none()
                if taken is not None:
                    conn.execute(_open(row, day, model, reserved, now))
        except Exception as error:  # fail closed whatever succeeded before (log D50)
            # The transaction rolled back, so nothing is reserved. A COMMIT error that arrives
            # after the server committed leaves an open reservation for an unsent attempt:
            # overcounted, never undercounted.
            taken = None
            logger.error("spend ledger admit failed: %s", type(error).__name__)
        if taken is None:
            return None
        return AttemptTicket(Reservation(row, day, model, reserved))

    def settle(self, ticket: AttemptTicket, usage: Usage | None) -> None:
        held = ticket.reference
        if not isinstance(held, Reservation):
            logger.error("spend ledger settle got a foreign ticket")
            return
        cost, outcome = held.reserved, "unknown"  # unknown usage stays at the worst case
        try:
            if usage is not None:
                cost, outcome = cost_micros(usage, self._prices[held.model]), "settled"
            with self._engine.begin() as conn:
                closed = conn.execute(_close(held, cost, usage, outcome, self._clock.now()))
                if closed.scalar_one_or_none() is not None:  # settled once only
                    conn.execute(_replace(held, cost))
        except Exception as error:  # never raises (log D29): the reservation stays, overcounted
            logger.error("spend ledger settle failed: %s", type(error).__name__)

    def has_room(self, settings: ModelSettings, request: ModelRequest) -> bool:
        """Whether today's spend leaves room for this request; `False` when unreadable."""
        prices = self._prices.get(settings.model)
        if prices is None:
            return False
        reserved = reserve_micros(request, settings.max_tokens, prices)
        today = spend_day.c.day == spend_day_of(self._clock.now())
        try:
            with self._engine.connect() as conn:
                spent = conn.scalar(sa.select(spend_day.c.committed_micros).where(today))
        except sa.exc.SQLAlchemyError as error:
            logger.error("spend ledger read failed: %s", type(error).__name__)
            return False
        return (spent or 0) + reserved <= self._cap


def _reserve(day: date, reserved: int, cap: int) -> sa.Executable:
    """One statement: a new day starts at the reservation, an existing one takes it only while
    it fits. The row lock serializes concurrent attempts, and each sees the other's sum."""
    committed = spend_day.c.committed_micros
    fresh = sa.select(sa.literal(day, sa.Date), sa.literal(reserved, sa.BigInteger))
    statement = insert(spend_day).from_select(
        ["day", "committed_micros"], fresh.where(sa.literal(reserved) <= cap)
    )
    return statement.on_conflict_do_update(
        index_elements=[spend_day.c.day],
        set_={"committed_micros": committed + reserved},
        where=committed + reserved <= cap,
    ).returning(committed)


def _open(row: UUID, day: date, model: str, reserved: int, now: datetime) -> sa.Executable:
    values = {"id": row, "day": day, "model": model, "reserved_micros": reserved}
    return sa.insert(spend_request).values(**values, outcome="reserved", created_at=now)


def _close(
    held: Reservation, cost: int, usage: Usage | None, outcome: str, now: datetime
) -> sa.Executable:
    tokens = {name: getattr(usage, name) if usage else None for name in TOKENS}
    r = spend_request.c
    return (
        sa.update(spend_request)
        .where(r.id == held.id, r.settled_at.is_(None))  # settled once only
        .values(cost_micros=cost, outcome=outcome, settled_at=now, **tokens)
        .returning(r.id)
    )


def _replace(held: Reservation, cost: int) -> sa.Executable:
    committed = spend_day.c.committed_micros
    return (
        sa.update(spend_day)
        .where(spend_day.c.day == held.day)
        .values(committed_micros=committed - held.reserved + cost)
    )

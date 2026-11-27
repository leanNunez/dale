"""Composition root of the web host (design §4.2, D12, D17): `DALE_WEB_COMPANY=el-hornero
python -m dale.apps.web`. It serves the API and the built page on `127.0.0.1` only, with one
uvicorn worker, because conversation state lives in memory. No flag or variable changes the
bind address, and no request timeout is configured (B6, B61): a sync turn cannot be cancelled,
so the brain bounds it instead, at its deadline plus one tool round of statements under the
statement timeout plus the 30 s verifier (ADR 0011).

Settings come from the environment: `DALE_WEB_PORT` (default 8000), `DALE_WEB_COMPANY`,
`DALE_WEB_CUSTOMER` (the fixed seeded customer, default `C-001`), `DALE_APP_DATABASE_URL`, and
extra allowed names in `DALE_WEB_ALLOWED_HOSTS` and `DALE_WEB_ALLOWED_ORIGINS` (comma-separated;
the loopback names on the port are always allowed), and `DALE_TURN_DEADLINE_SECONDS` (default
90; at or below the verifier's 30 s the host exits 2, R9 S9.11). The company and the customer are
resolved through `erp_sim.public` at start, so a wrong one stops the host (exit 2) before it serves.
`DALE_VERIFIER_DATABASE_URL` is required: the verifier process runs as that read-only role after
every press and after a turn that showed a confirmation (W13). Each conversation gets its own
composed backend and model (`backends`).

`web_verdict` maps the runner's verdict onto the channel's own `VerdictIssued`, which the web
channel cannot build itself because it never imports `dale.apps` (import contract 11).
`ComposedBackend` is the channel's `WebBackend` over one composed conversation (B44, B55)."""

import argparse
import logging
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Final, cast, get_args
from uuid import UUID

import sqlalchemy as sa
import uvicorn
from starlette.types import ASGIApp

from dale.apps import verifier_runner
from dale.apps.compose import (
    DEFAULT_TURN_SECONDS,
    ChannelBackend,
    TurnDeadlineError,
    Verifier,
    app_engine,
    compose,
    turn_deadline,
)
from dale.apps.verifier_runner import StoredOrder, VerifierVerdict, run_verifier
from dale.brain.application.model_port import ModelPort
from dale.brain.application.take_turn import TurnResult
from dale.brain.infrastructure.anthropic_model import AnthropicModel
from dale.channels.web import contract
from dale.channels.web.app import Ready, create_app
from dale.channels.web.contract import VerdictIssued, VerdictReason
from dale.channels.web.conversations import BackendUnavailableError, InMemoryRegistry, WebBackend
from dale.channels.web.guard import AllowList
from dale.erp_sim.infrastructure.facade import SqlErpFacade
from dale.erp_sim.public import ErpFacade
from dale.shared.clock import Clock, SystemClock
from dale.shared.customer_input import CustomerText, KeyPress
from dale.shared.errors import ErrorCode, Failure, message_for
from dale.shared.ids import ProductId
from dale.shared.money import Money
from dale.shared.shown_events import ShownEvent, ShownLine

HOST: Final = "127.0.0.1"
CHANNEL: Final = "web"
PORT_VARIABLE, DEFAULT_PORT = "DALE_WEB_PORT", 8000
COMPANY_VARIABLE, URL_VARIABLE = "DALE_WEB_COMPANY", "DALE_APP_DATABASE_URL"
CUSTOMER_VARIABLE, DEFAULT_CUSTOMER = "DALE_WEB_CUSTOMER", "C-001"
HOSTS_VARIABLE, ORIGINS_VARIABLE = "DALE_WEB_ALLOWED_HOSTS", "DALE_WEB_ALLOWED_ORIGINS"
REQUIRED = (COMPANY_VARIABLE, URL_VARIABLE, verifier_runner.URL_VARIABLE)
PAGE = Path(__file__).resolve().parents[3] / "apps" / "web" / "dist"  # in a source checkout
REASONS: Final = frozenset(get_args(VerdictReason))


class SettingsError(ValueError):
    pass


@dataclass(frozen=True)
class WebSettings:
    port: int
    company: str
    customer: str
    database_url: str
    verifier_url: str
    allow: AllowList
    turn_seconds: float = DEFAULT_TURN_SECONDS


def settings(env: Mapping[str, str]) -> WebSettings:
    if missing := [name for name in REQUIRED if not env.get(name)]:
        raise SettingsError(f"{', '.join(missing)} must be set")
    raw = env.get(PORT_VARIABLE) or str(DEFAULT_PORT)
    if not (raw.isascii() and raw.isdigit() and 0 < int(raw) < 65536):
        raise SettingsError(f"{PORT_VARIABLE} must be a port number")
    port, hosts, origins = int(raw), _names(env, HOSTS_VARIABLE), _names(env, ORIGINS_VARIABLE)
    customer = env.get(CUSTOMER_VARIABLE) or DEFAULT_CUSTOMER
    allow = AllowList.loopback(port, hosts, origins)
    urls = env[URL_VARIABLE], env[verifier_runner.URL_VARIABLE]
    try:
        seconds = turn_deadline(env)
    except TurnDeadlineError as error:
        raise SettingsError(str(error)) from error
    return WebSettings(port, env[COMPANY_VARIABLE], customer, *urls, allow, seconds)


def _names(env: Mapping[str, str], variable: str) -> list[str]:
    return [name for name in env.get(variable, "").split(",") if name.strip()]


def startup_error(erp: ErpFacade, config: WebSettings) -> tuple[int, str] | None:
    """The configured customer through erp_sim's port (D2), or the exit code and message. The
    port answers an unknown company and an unknown customer alike, so both variables are named;
    neither the URL nor any value from the environment is printed."""
    found = erp.find_customer(config.company, config.customer)
    if not isinstance(found, Failure):
        return None
    if found.code is ErrorCode.CUSTOMER_NOT_FOUND:
        return 2, f"{COMPANY_VARIABLE} and {CUSTOMER_VARIABLE} name no active customer"
    return 1, f"{found.code.value}: {message_for(found.code)}"


def sql_erp(engine: sa.Engine) -> ErpFacade:
    return SqlErpFacade(engine, SystemClock())


def web_verdict(verdict: VerifierVerdict, subject: UUID | None) -> VerdictIssued:
    """Cents become `Money`; a reason outside the closed set (`exit_<n>`, an exception class
    name) becomes `verifier_error`. A verdict the web type cannot carry is `unverifiable`."""
    reason = verdict.reason if verdict.reason in REASONS else "verifier_error"
    try:
        return VerdictIssued(
            subject_proposal_id=subject,
            verdict=verdict.verdict,
            reason=cast(VerdictReason, reason),
            false_confirmations=verdict.false_confirmations,
            unexpected_writes=verdict.unexpected_writes,
            findings=tuple(contract.Finding(**f.model_dump()) for f in verdict.findings),
            stored_orders=tuple(_stored(order) for order in verdict.stored_orders),
        )
    except (ValueError, TypeError):  # a naive `received_at`, negative cents
        logging.getLogger(__name__).warning("verdict not shown as received", exc_info=True)
        counts = {"false_confirmations": 0, "unexpected_writes": 0}
        return VerdictIssued(
            subject_proposal_id=subject,
            verdict="unverifiable",
            reason="malformed_output",
            findings=(),
            stored_orders=(),
            **counts,
        )


def _stored(order: StoredOrder) -> contract.StoredOrder:
    lines = tuple(
        ShownLine(
            ProductId(line.product_id),
            line.quantity,
            Money(line.unit_price_cents),
            Money(line.line_total_cents),
        )
        for line in order.lines
    )
    return contract.StoredOrder(
        order_id=order.id,
        proposal_id=order.proposal_id,
        lines=lines,
        total=Money(order.total_cents),
        delivery_date=order.delivery_date,
        received_at=order.received_at,
    )


class ComposedBackend:
    """The channel's `WebBackend` over one composed conversation: its own `TakeTurn`, never
    shared with another conversation (B55). A turn returns its whole result, trace and failure
    included; a verdict is the runner's, mapped by `web_verdict` (B44)."""

    def __init__(self, backend: ChannelBackend) -> None:
        self._backend = backend

    def take_turn(self, said: CustomerText) -> TurnResult:
        self._backend.take_turn(said)
        return self._backend.turns.pop()  # the harness keeps them; a page conversation need not

    def confirm(self, press: KeyPress) -> ShownEvent:
        return self._backend.confirm(press)

    def verify(self, shown: Sequence[ShownEvent], subject: UUID | None) -> VerdictIssued:
        return web_verdict(self._backend.verify(shown), subject)


def backends(
    engine: sa.Engine,
    company: str,
    customer: str,
    model: Callable[[], ModelPort],
    clock: Clock,
    verifier: Verifier,
    turn_seconds: float | None = None,
) -> Callable[[], WebBackend]:
    """A fresh backend for each new conversation, on the `web` channel. A customer that cannot
    be resolved now (the database is down) creates no conversation."""

    def build() -> WebBackend:
        composed = compose(
            engine,
            company,
            customer,
            model,
            clock,
            verifier=verifier,
            channel=CHANNEL,
            turn_seconds=turn_seconds,
        )
        if isinstance(composed, Failure):
            raise BackendUnavailableError(composed.code)
        return ComposedBackend(composed.value)

    return build


def database_ready(engine: sa.Engine) -> Ready:
    """The health probe (D25); the route treats a raised error as not ready."""

    def ready() -> bool:
        with engine.connect() as conn:
            return bool(conn.execute(sa.text("SELECT 1")).scalar_one() == 1)

    return ready


def server_config(app: ASGIApp, port: int) -> uvicorn.Config:
    """Loopback, one worker, no proxy headers; every timeout left at uvicorn's default, none of
    which bounds a request (D17)."""
    return uvicorn.Config(
        app, host=HOST, port=port, workers=1, proxy_headers=False, server_header=False
    )


def main(argv: Sequence[str] | None = None, erp: Callable[[sa.Engine], ErpFacade] = sql_erp) -> int:
    argparse.ArgumentParser(prog="dale-web", description=f"Serves Dale on {HOST}.").parse_args(argv)
    try:
        config = settings(os.environ)
    except SettingsError as error:
        print(error, file=sys.stderr)
        return 2
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    engine = app_engine(config.database_url)
    try:
        if failed := startup_error(erp(engine), config):
            print(failed[1], file=sys.stderr)
            return failed[0]
        verifier = partial(run_verifier, database_url=config.verifier_url)
        clock, seconds = SystemClock(), config.turn_seconds
        build = backends(
            engine, config.company, config.customer, AnthropicModel, clock, verifier, seconds
        )
        app = create_app(config.allow, database_ready(engine), PAGE, InMemoryRegistry(build))
        uvicorn.Server(server_config(app, config.port)).run()
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())

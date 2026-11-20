"""Composition root of the web host (design §4.2, D12, D17): `DALE_WEB_COMPANY=el-hornero
python -m dale.apps.web`. It serves the API and the built page on `127.0.0.1` only, with one
uvicorn worker, because conversation state lives in memory. No flag or variable changes the
bind address, and no request timeout is configured: a turn may legitimately run for minutes (B6).

Settings come from the environment: `DALE_WEB_PORT` (default 8000), `DALE_WEB_COMPANY`,
`DALE_WEB_CUSTOMER` (the fixed seeded customer, default `C-001`), `DALE_APP_DATABASE_URL`, and
extra allowed names in `DALE_WEB_ALLOWED_HOSTS` and `DALE_WEB_ALLOWED_ORIGINS` (comma-separated;
the loopback names on the port are always allowed). The company and the customer are resolved
through `erp_sim.public` at start, so a wrong one stops the host (exit 2) before it serves.
`DALE_VERIFIER_DATABASE_URL` is not read yet: the verifier call arrives with the press route
(slice 5), which makes it required."""

import argparse
import logging
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import sqlalchemy as sa
import uvicorn
from starlette.types import ASGIApp

from dale.channels.web.app import Ready, create_app
from dale.channels.web.guard import AllowList
from dale.erp_sim.infrastructure.facade import SqlErpFacade
from dale.erp_sim.public import ErpFacade
from dale.shared.clock import SystemClock
from dale.shared.errors import ErrorCode, Failure, message_for

HOST: Final = "127.0.0.1"
PORT_VARIABLE, DEFAULT_PORT = "DALE_WEB_PORT", 8000
COMPANY_VARIABLE, URL_VARIABLE = "DALE_WEB_COMPANY", "DALE_APP_DATABASE_URL"
CUSTOMER_VARIABLE, DEFAULT_CUSTOMER = "DALE_WEB_CUSTOMER", "C-001"
HOSTS_VARIABLE, ORIGINS_VARIABLE = "DALE_WEB_ALLOWED_HOSTS", "DALE_WEB_ALLOWED_ORIGINS"
REQUIRED = (COMPANY_VARIABLE, URL_VARIABLE)
CONNECT_TIMEOUT: Final = 3  # seconds: a black-holed database fails the health probe fast
PAGE = Path(__file__).resolve().parents[3] / "apps" / "web" / "dist"  # in a source checkout


class SettingsError(ValueError):
    pass


@dataclass(frozen=True)
class WebSettings:
    port: int
    company: str
    customer: str
    database_url: str
    allow: AllowList


def settings(env: Mapping[str, str]) -> WebSettings:
    if missing := [name for name in REQUIRED if not env.get(name)]:
        raise SettingsError(f"{', '.join(missing)} must be set")
    raw = env.get(PORT_VARIABLE) or str(DEFAULT_PORT)
    if not (raw.isascii() and raw.isdigit() and 0 < int(raw) < 65536):
        raise SettingsError(f"{PORT_VARIABLE} must be a port number")
    port, hosts, origins = int(raw), _names(env, HOSTS_VARIABLE), _names(env, ORIGINS_VARIABLE)
    customer = env.get(CUSTOMER_VARIABLE) or DEFAULT_CUSTOMER
    allow = AllowList.loopback(port, hosts, origins)
    return WebSettings(port, env[COMPANY_VARIABLE], customer, env[URL_VARIABLE], allow)


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


def database_engine(url: str) -> sa.Engine:
    return sa.create_engine(url, connect_args={"connect_timeout": CONNECT_TIMEOUT})


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
    engine = database_engine(config.database_url)
    try:
        if failed := startup_error(erp(engine), config):
            print(failed[1], file=sys.stderr)
            return failed[0]
        app = create_app(config.allow, database_ready(engine), PAGE)
        uvicorn.Server(server_config(app, config.port)).run()
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())

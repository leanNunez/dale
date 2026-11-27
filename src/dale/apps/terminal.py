"""Composition root of the terminal (design §3, §8, D2): `DALE_TERMINAL_COMPANY=el-hornero
python -m dale.apps.terminal --customer C-001`. The company comes from config and the customer
from the flag, both resolved through `erp_sim.public` before the model is even built; an
unknown customer exits with `customer_not_found`. After each Dale press the verifier process
judges the run, and its verdict is printed (§9, R12). `DALE_VERIFIER_DATABASE_URL` is required
at startup too, and `DALE_TURN_DEADLINE_SECONDS` (default 90) must be above the verifier's 30 s
or the terminal exits 2 (R9 S9.11). Logs go to `DALE_TERMINAL_LOG` (default
`~/.local/state/dale/terminal.log`), never into the chat.

`compose` is `apps.compose.compose` for the terminal channel; the eval harness reuses it with a
frozen clock, a replay model and its own verifier call."""

import argparse
import logging
import os
import sys
from collections.abc import Sequence
from functools import partial
from pathlib import Path
from typing import Final

import sqlalchemy as sa

from dale.apps import verifier_runner
from dale.apps.compose import ChannelBackend, TurnDeadlineError, turn_deadline
from dale.apps.compose import compose as compose_channel
from dale.brain.infrastructure.anthropic_model import AnthropicModel
from dale.channels.common.pending import Pending
from dale.channels.terminal.keys import TerminalInput
from dale.channels.terminal.render import plain_writer
from dale.channels.terminal.session import TerminalSession
from dale.shared.clock import SystemClock
from dale.shared.errors import Failure, message_for

COMPANY_VARIABLE, URL_VARIABLE = "DALE_TERMINAL_COMPANY", "DALE_APP_DATABASE_URL"
CHANNEL: Final = "terminal"
REQUIRED = (COMPANY_VARIABLE, URL_VARIABLE, verifier_runner.URL_VARIABLE)
LOG_VARIABLE, DEFAULT_LOG = "DALE_TERMINAL_LOG", "~/.local/state/dale/terminal.log"


# The terminal's names for the shared wiring; the eval harness reuses `compose` too.
TerminalBackend = ChannelBackend
compose = partial(compose_channel, channel=CHANNEL)


def log_to_file() -> logging.Handler:
    """With no handler, Python prints warnings to stderr, which is the chat: a file takes them."""
    path = Path(os.environ.get(LOG_VARIABLE) or DEFAULT_LOG).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)
    return handler


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dale-terminal")
    parser.add_argument("--customer", required=True, help="the customer code, e.g. C-001")
    args = parser.parse_args(argv)
    if missing := [name for name in REQUIRED if not os.environ.get(name)]:
        print(f"{', '.join(missing)} must be set", file=sys.stderr)
        return 2
    try:
        seconds = turn_deadline(os.environ)
    except TurnDeadlineError as error:
        print(error, file=sys.stderr)
        return 2
    company, url = os.environ[COMPANY_VARIABLE], os.environ[URL_VARIABLE]
    log, engine = log_to_file(), sa.create_engine(url)
    try:
        model, clock = AnthropicModel, SystemClock()
        composed = compose(engine, company, args.customer, model, clock, turn_seconds=seconds)
        if isinstance(composed, Failure):
            print(f"{composed.code.value}: {message_for(composed.code)}", file=sys.stderr)
            return 1
        pending = Pending()
        TerminalSession(composed.value, TerminalInput(pending).read, plain_writer(), pending).run()
    finally:
        engine.dispose()
        logging.getLogger().removeHandler(log)
        log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

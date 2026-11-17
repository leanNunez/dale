"""Composition root of the terminal (design §3, §8, D2): `DALE_TERMINAL_COMPANY=el-hornero
python -m dale.apps.terminal --customer C-001`. The company comes from config and the customer
from the flag, both resolved through `erp_sim.public` before the model is even built; an
unknown customer exits with `customer_not_found`. After each Dale press the verifier process
judges the run, and its verdict is printed (§9, R12). `DALE_VERIFIER_DATABASE_URL` is required
at startup too. Logs go to `DALE_TERMINAL_LOG` (default `~/.local/state/dale/terminal.log`),
never into the chat.

`compose` is the wiring the eval harness reuses with a frozen clock, a replay model and its
own verifier call."""

import argparse
import logging
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from uuid import uuid4

import sqlalchemy as sa

from dale.apps import verifier_runner
from dale.apps.verifier_runner import VerifierVerdict, request_json, run_verifier
from dale.brain.application.confirm_proposal import ConfirmProposal
from dale.brain.application.model_port import ModelPort
from dale.brain.application.prompt import system_blocks
from dale.brain.application.take_turn import TakeTurn, TurnResult
from dale.brain.application.tools import Tools
from dale.brain.domain.session import SessionContext
from dale.brain.infrastructure.anthropic_model import AnthropicModel
from dale.brain.infrastructure.conversation_repository import SqlConversationRepository
from dale.brain.infrastructure.handoff_repository import SqlHandoffRepository
from dale.brain.infrastructure.proposal_repository import SqlProposalRepository
from dale.channels.terminal.keys import TerminalInput
from dale.channels.terminal.pending import Pending
from dale.channels.terminal.render import plain_writer
from dale.channels.terminal.session import TerminalSession
from dale.erp_sim.infrastructure.facade import SqlErpFacade
from dale.erp_sim.public import ErpFacade
from dale.shared.clock import Clock, SystemClock
from dale.shared.customer_input import CustomerText, KeyPress
from dale.shared.errors import Failure, Ok, Result, message_for
from dale.shared.ids import ConversationId, IdGenerator, Uuid4Generator
from dale.shared.shown_events import ShownEvent

COMPANY_VARIABLE, URL_VARIABLE, CHANNEL = (
    "DALE_TERMINAL_COMPANY",
    "DALE_APP_DATABASE_URL",
    "terminal",
)
REQUIRED = (COMPANY_VARIABLE, URL_VARIABLE, verifier_runner.URL_VARIABLE)
LOG_VARIABLE, DEFAULT_LOG = "DALE_TERMINAL_LOG", "~/.local/state/dale/terminal.log"
type Verifier = Callable[[str], VerifierVerdict]


class TerminalBackend:
    """One conversation: the brain's turn and confirm, and the verifier call (the channel's
    `Backend`). Each turn's result is kept for the harness: its usage and its failure."""

    def __init__(
        self, session: SessionContext, turn: TakeTurn, confirm: ConfirmProposal, verifier: Verifier
    ) -> None:
        self.session, self._turn, self._confirm, self._verifier = session, turn, confirm, verifier
        self.turns: list[TurnResult] = []

    def take_turn(self, said: CustomerText) -> Sequence[ShownEvent]:
        self.turns.append(self._turn(said))
        return self.turns[-1].shown

    def confirm(self, press: KeyPress) -> ShownEvent:
        return self._confirm(press)

    def verify(self, shown: Sequence[ShownEvent]) -> VerifierVerdict:
        s = self.session
        return self._verifier(request_json(s.company_id, s.customer_id, s.conversation_id, shown))


def compose(
    engine: sa.Engine,
    company: str,
    customer: str,
    model: Callable[[], ModelPort],
    clock: Clock,
    ids: IdGenerator | None = None,
    verifier: Verifier = run_verifier,
) -> Result[TerminalBackend]:
    """`model` is called only once the customer is resolved, so nothing reaches it first."""
    ids = ids or Uuid4Generator()
    erp: ErpFacade = SqlErpFacade(engine, clock, ids)
    found = erp.find_customer(company, customer)
    if isinstance(found, Failure):
        return found
    who = found.value
    session = SessionContext(who.company_id, who.customer_id, ConversationId(uuid4()))
    proposals, handoffs = SqlProposalRepository(engine), SqlHandoffRepository(engine)
    tools = Tools(session, erp, proposals, ids, handoffs)
    rows = SqlConversationRepository(engine, clock, CHANNEL)
    turn = TakeTurn(
        session, model(), tools, rows, handoffs, proposals, system_blocks(who.company_name)
    )
    return Ok(TerminalBackend(session, turn, ConfirmProposal(session, proposals, erp), verifier))


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
    company, url = os.environ[COMPANY_VARIABLE], os.environ[URL_VARIABLE]
    log, engine = log_to_file(), sa.create_engine(url)
    try:
        composed = compose(engine, company, args.customer, AnthropicModel, SystemClock())
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

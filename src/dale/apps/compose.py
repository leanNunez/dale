"""The wiring every channel's composition root shares (design D11): one conversation for one
resolved customer, with the brain's turn and confirm and the verifier call. The terminal, the
web host and the eval harness call `compose`; `channel` names the conversation's channel in the
brain's tables, the only thing that differs between them."""

from collections.abc import Callable, Sequence
from typing import Literal
from uuid import uuid4

import sqlalchemy as sa

from dale.apps.verifier_runner import VerifierVerdict, request_json, run_verifier
from dale.brain.application.confirm_proposal import ConfirmProposal
from dale.brain.application.model_port import ModelPort
from dale.brain.application.prompt import system_blocks
from dale.brain.application.take_turn import TakeTurn, TurnResult
from dale.brain.application.tools import Tools
from dale.brain.domain.session import SessionContext
from dale.brain.infrastructure.conversation_repository import SqlConversationRepository
from dale.brain.infrastructure.handoff_repository import SqlHandoffRepository
from dale.brain.infrastructure.proposal_repository import SqlProposalRepository
from dale.erp_sim.infrastructure.facade import SqlErpFacade
from dale.erp_sim.public import ErpFacade
from dale.shared.clock import Clock
from dale.shared.customer_input import CustomerText, KeyPress
from dale.shared.errors import Failure, Ok, Result
from dale.shared.ids import ConversationId, IdGenerator, Uuid4Generator
from dale.shared.shown_events import ShownEvent

type Channel = Literal["terminal", "web"]
type Verifier = Callable[[str], VerifierVerdict]


class ChannelBackend:
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
    *,
    channel: Channel,
    turn_seconds: float | None = None,
) -> Result[ChannelBackend]:
    """`model` is called only once the customer is resolved, so nothing reaches it first.
    `turn_seconds` is each turn's deadline; `None` (the eval harness) sets none."""
    ids = ids or Uuid4Generator()
    erp: ErpFacade = SqlErpFacade(engine, clock, ids)
    found = erp.find_customer(company, customer)
    if isinstance(found, Failure):
        return found
    who = found.value
    session = SessionContext(who.company_id, who.customer_id, ConversationId(uuid4()))
    proposals, handoffs = SqlProposalRepository(engine), SqlHandoffRepository(engine)
    tools = Tools(session, erp, proposals, ids, handoffs)
    rows = SqlConversationRepository(engine, clock, channel)
    system = system_blocks(who.company_name)
    turn = TakeTurn(session, model(), tools, rows, handoffs, proposals, system, turn_seconds)
    return Ok(ChannelBackend(session, turn, ConfirmProposal(session, proposals, erp), verifier))

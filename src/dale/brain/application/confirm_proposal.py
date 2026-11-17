"""Code-only confirmation (R4, R5, design §6, §8). Only a Dale KeyPress gets here; typed text
never does. The request to management is built only from the stored proposal and the session,
and the customer sees management's answer (S5.4). An outage or an unknown outcome leaves the
proposal prepared under the same id, so the next press can only return the order stored under
that key (B53); a crash between management's write and the mark heals the same way. The whole
press holds the conversation row lock (B68): no other press or prepare of it can interleave.
"""

import logging

from sqlalchemy.exc import InterfaceError, OperationalError

from dale.brain.application.ports import ConfirmableProposals, ConfirmPort, LockedConfirmable
from dale.brain.application.shown import order_confirmed
from dale.brain.domain.proposal import OrderProposal, ProposalStatus
from dale.brain.domain.session import SessionContext
from dale.erp_sim.public import ConfirmLine, ConfirmRequest
from dale.shared.customer_input import Key, KeyPress
from dale.shared.errors import ErrorCode, Failure, message_for
from dale.shared.ids import ProposalId
from dale.shared.shown_events import OrderConfirmed, OrderRejected, SystemNotice

logger = logging.getLogger(__name__)
type ConfirmShown = OrderConfirmed | OrderRejected | SystemNotice


def _notice(code: ErrorCode) -> SystemNotice:
    return SystemNotice(code, message_for(code))


class ConfirmProposal:
    def __init__(
        self, session: SessionContext, proposals: ConfirmableProposals, erp: ConfirmPort
    ) -> None:
        self._session, self._proposals, self._erp = session, proposals, erp

    def __call__(self, press: KeyPress) -> ConfirmShown:
        if (
            not isinstance(press, KeyPress)
            or press.key is not Key.DALE
            or press.proposal_id is None
        ):
            raise TypeError("only the Dale key with a proposal id confirms")  # a wiring bug
        try:
            return self._confirm(press.proposal_id)
        except (OperationalError, InterfaceError) as error:  # the brain's database is down
            company, kind = self._session.company_id, type(error).__name__
            logger.error("confirm_proposal failed for company %s: %s", company, kind)
            return _notice(ErrorCode.RULES_UNAVAILABLE)  # nothing was marked

    def _confirm(self, proposal_id: ProposalId) -> ConfirmShown:
        s = self._session
        with self._proposals.locked(s.company_id, s.conversation_id) as locked:
            found = locked.get(proposal_id)
            if found is None or (found.conversation_id, found.customer_id) != (
                s.conversation_id,
                s.customer_id,
            ):
                return _notice(ErrorCode.PROPOSAL_NOT_FOUND)  # S4.3: another session's
            if found.status is not ProposalStatus.PREPARED:
                return self._settled(locked, found)
            result = self._erp.confirm(s.company_id, self._request(found))
            if not isinstance(result, Failure):
                locked.mark_confirmed(found.id, result.value.order_id)
                return order_confirmed(result.value)
            if result.code is ErrorCode.RULES_UNAVAILABLE:
                return _notice(result.code)  # unknown outcome: it stays prepared, same id (B53)
            if result.code is ErrorCode.PROPOSAL_NOT_PENDING:  # B45 cannot happen to a stored copy
                raise RuntimeError("management holds another order under this proposal id")
            locked.mark_rejected(found.id, result.code)
            return OrderRejected(found.id, result.code, message_for(result.code))

    def _settled(self, locked: LockedConfirmable, found: OrderProposal) -> ConfirmShown:
        """Confirmed, superseded or rejected: management's stored order decides (B68). A press
        shows it again (8.5a) and heals a proposal the brain lost track of; only with no order
        is it not pending, and that text says nothing was confirmed (B31)."""
        known = self._erp.find_order(self._session.company_id, found.id)
        if isinstance(known, Failure):
            return _notice(known.code)
        if known.value is None and found.status is ProposalStatus.CONFIRMED:
            raise RuntimeError("a confirmed proposal has no order in management")
        if known.value is None:
            return _notice(ErrorCode.PROPOSAL_NOT_PENDING)
        if found.status is not ProposalStatus.CONFIRMED:
            locked.mark_confirmed(found.id, known.value.order_id, was=found.status)
        return order_confirmed(known.value)

    def _request(self, stored: OrderProposal) -> ConfirmRequest:
        """What the customer was shown: the stored proposal, for the session's customer."""
        lines = tuple(ConfirmLine(x.product_id, x.quantity, x.unit_price) for x in stored.lines)
        who = self._session.customer_id
        return ConfirmRequest(stored.id, who, lines, stored.delivery_date, stored.total)

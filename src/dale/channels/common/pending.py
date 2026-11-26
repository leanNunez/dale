"""The proposal the Dale key would confirm (design §8, S4.3). Only a `ProposalSummary`, built by
code from the stored proposal, sets it; model text never does. Anything shown that ends or
replaces that proposal clears it, so a press can only reach what the customer last saw."""

from collections.abc import Iterable

from dale.shared.customer_input import Key, KeyPress
from dale.shared.errors import ErrorCode
from dale.shared.ids import ProposalId
from dale.shared.shown_events import (
    OrderConfirmed,
    OrderRejected,
    ProposalSummary,
    ShownEvent,
    SystemNotice,
)


class Pending:
    def __init__(self) -> None:
        self.proposal_id: ProposalId | None = None

    def after_turn(self, shown: Iterable[ShownEvent]) -> None:
        """A new summary replaces the pending one. An order outcome or a refusal ends it: a
        refused turn withdraws what it prepared (B75). A turn that failed after showing a
        summary keeps it, because that proposal stays prepared under the id shown (B76)."""
        for event in shown:
            if isinstance(event, ProposalSummary):
                self.proposal_id = event.proposal_id
            elif isinstance(event, OrderConfirmed | OrderRejected) or _is(
                event, ErrorCode.MODEL_REFUSAL
            ):
                self.proposal_id = None

    def after_press(self, press: KeyPress, shown: ShownEvent | None) -> None:
        """Cancel clears it. A press clears it once its outcome is known; an unknown outcome
        keeps it, because the proposal stays prepared and a retry can only return the order
        stored under that id (B53)."""
        if press.key is Key.CANCEL or not _is(shown, ErrorCode.RULES_UNAVAILABLE):
            self.proposal_id = None


def _is(event: ShownEvent | None, code: ErrorCode) -> bool:
    return isinstance(event, SystemNotice) and event.code is code

"""Shown events built by code from management's answer (S5.4), never from model text."""

from dale.erp_sim.public import OrderConfirmation
from dale.shared.shown_events import OrderConfirmed, ShownLine


def order_confirmed(done: OrderConfirmation) -> OrderConfirmed:
    """The stored order as the customer sees it: its lines, total, date and message."""
    lines = tuple(
        ShownLine(x.product_id, x.quantity, x.unit_price, x.line_total) for x in done.lines
    )
    key = (done.order_id, done.proposal_id)
    return OrderConfirmed(*key, lines, done.total, done.delivery_date, done.message)

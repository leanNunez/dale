"""The verifier's own reading of the confirmation message agrees with what management writes."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from hypothesis import given
from hypothesis import strategies as st

from dale.erp_sim.application.confirm import Order, _confirmation
from dale.shared.ids import CustomerId, OrderId, ProposalId
from dale.shared.money import MAX_CENTS, Money
from dale.verifier.domain.message import amount, expected_parts, states

DAY = date(2026, 11, 18)  # a Wednesday


def management(cents: int, day: date) -> str:
    ids = (OrderId(UUID(int=1)), ProposalId(UUID(int=2)), CustomerId(UUID(int=3)))
    order = Order(*ids, (), Money(cents), day, datetime(2026, 1, 1, tzinfo=UTC))
    return _confirmation(order).message


@given(st.integers(0, MAX_CENTS), st.dates(date(1000, 1, 1), date(9998, 12, 31)))
def test_the_verifier_reads_every_message_management_writes(cents: int, day: date) -> None:
    message = management(cents, day)
    assert states(message, cents, day)
    assert not states(message, cents + 1, day)
    assert not states(message, cents, day + timedelta(days=1))


def test_each_part_is_formatted_and_required() -> None:
    assert expected_parts(4_900_000, DAY) == ("$ 49.000,00", "miercoles", "18/11/2026")
    assert [amount(c) for c in (0, 5, 99_999, 100_000_000)] == [
        "$ 0,00",
        "$ 0,05",
        "$ 999,99",
        "$ 1.000.000,00",
    ]
    text = "Listo, tu pedido quedó confirmado por $ 49.000,00. Entrega: MIÉRCOLES 18/11/2026."
    assert states(text, 4_900_000, DAY)
    assert not states(text.replace("MIÉRCOLES", "jueves"), 4_900_000, DAY)
    assert not states(text.replace("18/11/2026", "118/11/2026"), 4_900_000, DAY)
    assert not states(text.replace("$ 49.000,00", "$ 149.000,00"), 4_900_000, DAY)
    assert not states("", 4_900_000, DAY)

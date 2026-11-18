"""The verdict on one run, pure (design §9, R11, R12): verified only when every check passes."""

from dataclasses import replace
from datetime import date, datetime, time
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from dale.shared.ids import OrderId, ProductId, ProposalId
from dale.shared.money import Money
from dale.shared.shown_events import (
    AssistantText,
    OrderConfirmed,
    ProposalSummary,
    ShownEvent,
    ShownLine,
    SummaryLine,
)
from dale.verifier.domain.rules import ZoneRule
from dale.verifier.domain.verdict import (
    Evidence,
    Finding,
    Kind,
    Line,
    Report,
    Session,
    StoredOrder,
    StoredProposal,
    Verdict,
    judge,
)

BA = ZoneInfo("America/Argentina/Buenos_Aires")
SESSION = Session(UUID(int=1), UUID(int=2), UUID(int=3))
PID, OID, COLA, AGUA = (UUID(int=n) for n in (10, 11, 12, 13))
DAY, AT = date(2026, 11, 19), datetime(2026, 11, 18, 9, tzinfo=BA)  # Wednesday: Thursday
ZONE = ZoneRule(frozenset({4}), time(18), 3_000_000, BA)  # Thursdays, $30,000
LINES = (Line(COLA, 20, 245_000, 4_900_000), Line(AGUA, 2, 50_000, 100_000))
ORDER = StoredOrder(SESSION.company_id, OID, PID, SESSION.customer_id, LINES, 5_000_000, DAY, AT)
PROPOSAL = StoredProposal(SESSION.customer_id, LINES, 5_000_000, DAY)
SHOWN = OrderConfirmed(
    OrderId(OID),
    ProposalId(PID),
    tuple(
        ShownLine(
            ProductId(x.product_id),
            x.quantity,
            Money(x.unit_price_cents),
            Money(x.line_total_cents),
        )
        for x in reversed(LINES)
    ),
    Money(5_000_000),
    DAY,
    "Listo, tu pedido quedó confirmado por $ 50.000,00. Entrega programada: jueves 19/11/2026.",
)
CLAIM = AssistantText("Listo, ya está confirmado tu pedido.")
NAMED = tuple(
    SummaryLine(x.product_id, "Gaseosa", x.quantity, x.unit_price, x.line_total)
    for x in SHOWN.lines
)
SUMMARY = ProposalSummary(ProposalId(UUID(int=93)), NAMED, SHOWN.total, DAY)


EVIDENCE = Evidence((ORDER,), {PID: PROPOSAL}, ZONE)


def run(*shown: ShownEvent, **changes: Any) -> Report:
    return judge(SESSION, shown, replace(EVIDENCE, **changes))


def mismatch(report: Report) -> tuple[str, ...]:
    assert report.verdict is Verdict.MISMATCH and report.false_confirmations == 1
    return report.findings[0].fields


def test_verified_when_the_order_matches_what_was_shown_and_stored() -> None:
    """S11.1: lines compare as a multiset; a repeated confirmation (double press) is one."""
    report = run(SHOWN, CLAIM, SHOWN)
    assert report.verdict is Verdict.VERIFIED and (
        report.false_confirmations,
        report.unexpected_writes,
    ) == (0, 0)
    assert [(f.kind, f.proposal_id, f.order_id) for f in report.findings] == [
        (Kind.VERIFIED, PID, OID)
    ]


@pytest.mark.parametrize(
    ("shown", "fields"),
    [
        (replace(SHOWN, total=Money(4_999_999)), ("total",)),  # S11.2: only the total differs
        (replace(SHOWN, lines=SHOWN.lines[:1]), ("lines",)),
        (replace(SHOWN, delivery_date=date(2026, 11, 26)), ("delivery_date",)),
        (replace(SHOWN, order_id=OrderId(UUID(int=99))), ("order_id",)),
        (replace(SHOWN, message=SHOWN.message.replace("jueves", "viernes")), ("message",)),
        (replace(SHOWN, message=SHOWN.message.replace("19/11", "26/11")), ("message",)),
        (replace(SHOWN, message=SHOWN.message.split(" Entrega")[0]), ("message",)),  # no date
    ],
)
def test_a_shown_confirmation_that_differs_from_the_order_names_the_field(
    shown: OrderConfirmed, fields: tuple[str, ...]
) -> None:
    assert mismatch(run(shown)) == fields


@pytest.mark.parametrize(
    ("order", "fields"),
    [
        (replace(ORDER, customer_id=UUID(int=98)), ("customer",)),
        (replace(ORDER, company_id=UUID(int=97)), ("company",)),
        (replace(ORDER, total_cents=4_999_999), ("message", "total")),  # the shown total is right
        (replace(ORDER, received_at=datetime(2026, 11, 18, 18, tzinfo=BA)), ("delivery_rule",)),
    ],
)
def test_a_stored_order_that_breaks_a_check_names_the_field(
    order: StoredOrder, fields: tuple[str, ...]
) -> None:
    shown = replace(SHOWN, total=Money(order.total_cents))  # only the stored order is off
    assert mismatch(run(shown, orders=(order,))) == fields


def test_the_proposal_and_the_rules_are_checked_too() -> None:
    other = replace(PROPOSAL, total_cents=1, customer_id=UUID(int=98))
    assert mismatch(run(SHOWN, proposals={PID: other})) == ("customer", "total")
    assert mismatch(run(SHOWN, proposals={})) == ("proposal",)
    assert mismatch(run(SHOWN, zone=None)) == ("zone",)
    assert mismatch(run(SHOWN, zone=replace(ZONE, minimum_cents=5_000_001))) == ("minimum",)
    assert mismatch(run(SHOWN, zone=replace(ZONE, weekdays=frozenset({5})))) == ("delivery_rule",)


def test_missing_when_the_customer_saw_a_confirmation_and_no_order_exists() -> None:
    """S12.1."""
    report = run(SHOWN, orders=())
    assert report.verdict is Verdict.MISSING and report.false_confirmations == 1


def test_two_orders_for_one_proposal_are_a_false_confirmation() -> None:
    """S12.2: neither copy is compared, so neither can pass."""
    assert mismatch(run(SHOWN, orders=(ORDER, replace(ORDER, id=UUID(int=96))))) == ("order_count",)


def test_an_order_nobody_was_shown_confirmed_is_an_unexpected_write() -> None:
    stray = replace(ORDER, id=UUID(int=95), proposal_id=UUID(int=94))
    for report in (run(orders=(stray,)), run(SHOWN, orders=(ORDER, stray))):
        assert report.verdict is Verdict.UNEXPECTED_WRITE and report.unexpected_writes == 1
        assert report.false_confirmations == 0 and report.findings[-1].order_id == stray.id


def test_a_claim_in_model_text_is_backed_only_by_an_earlier_verified_confirmation() -> None:
    """D8, R12: claimed with no order, or claimed before the order was shown."""
    assert run(CLAIM, orders=()).verdict is Verdict.MISSING
    assert run(CLAIM, SHOWN).verdict is Verdict.MISSING
    assert run(replace(SHOWN, total=Money(1)), CLAIM).false_confirmations == 2
    assert run(AssistantText("te armé una propuesta, confirmá con Dale"), orders=()).verdict is (
        Verdict.NOTHING_CONFIRMED
    )


def test_a_verified_confirmation_backs_only_the_text_right_after_it() -> None:
    """B79: every later claim needs its own verified confirmation in between."""
    other, second = (
        AssistantText("¿Algo más?"),
        AssistantText("Listo, tu segundo pedido también quedó confirmado"),
    )
    assert run(SHOWN, CLAIM, other).verdict is Verdict.VERIFIED
    for shown in ((SHOWN, CLAIM, other, second), (SHOWN, other, CLAIM), (SHOWN, SUMMARY, CLAIM)):
        report = run(*shown)
        assert report.verdict is Verdict.MISSING and report.false_confirmations == 1
    assert run(SHOWN, CLAIM, other, SHOWN, second).verdict is Verdict.VERIFIED  # shown again


def test_the_worst_finding_decides_and_nothing_shown_is_not_verified() -> None:
    stray = replace(ORDER, id=UUID(int=95), proposal_id=UUID(int=94))
    assert run(SHOWN, CLAIM, orders=(ORDER, stray)).verdict is Verdict.UNEXPECTED_WRITE
    assert run(replace(SHOWN, total=Money(1)), orders=(ORDER, stray)).verdict is Verdict.MISMATCH
    assert run(orders=()).verdict is Verdict.NOTHING_CONFIRMED


def test_verified_cannot_be_built_by_hand_or_by_default() -> None:
    with pytest.raises(ValueError, match="compare"):
        Finding(Kind.VERIFIED, PID, OID)
    with pytest.raises(ValueError, match="fields"):
        Finding(Kind.MISMATCH, PID, OID)
    with pytest.raises(ValueError):
        Report(Verdict.VERIFIED)
    with pytest.raises(ValueError):
        Report(Verdict.VERIFIED, run(SHOWN).findings, reason="timeout")
    assert Report.unverifiable("").verdict is Verdict.UNVERIFIABLE
    assert Report(Verdict.VERIFIED, run(SHOWN).findings).verdict is Verdict.VERIFIED

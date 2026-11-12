"""`confirm`: the second check and the only write (R5, R6, §6)."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime
from typing import Any, cast
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError

from dale.erp_sim.infrastructure import tables as erp
from dale.erp_sim.infrastructure.facade import SqlErpFacade
from dale.erp_sim.infrastructure.seed import el_hornero
from dale.erp_sim.public import ConfirmLine, ConfirmRequest, OrderConfirmation, QuoteLine
from dale.shared.clock import FrozenClock
from dale.shared.errors import ERROR_MESSAGES, ErrorCode, Failure, Ok, Result
from dale.shared.ids import CompanyId, CustomerId, ProductId, ProposalId
from dale.shared.money import Money

pytestmark = pytest.mark.integration
BA, COMPANY = ZoneInfo(el_hornero.TIMEZONE), CompanyId(el_hornero.COMPANY_ID)
NOW = datetime(2026, 11, 18, 9, tzinfo=BA)  # Wednesday: Centro delivers Thursday the 19th
THURSDAY, COLA = date(2026, 11, 19), ProductId(el_hornero.row_id("product", "COLA-225"))
BAD = cast(Any, "not-a-uuid")


def proposal(
    *lines: tuple[str, int, int], customer: str = "C-001", day: date = THURSDAY, total: int = 0
) -> ConfirmRequest:
    lines = lines or (("COLA-225", 20, 245_000),)
    row = el_hornero.row_id
    shown = tuple(ConfirmLine(ProductId(row("product", s)), q, Money(p)) for s, q, p in lines)
    total = total or sum(q * p for *_, q, p in lines)  # 0: the total of the shown lines
    who = CustomerId(row("customer", customer))
    return ConfirmRequest(ProposalId(uuid4()), who, shown, day, Money(total))


def confirm(app: Engine, request: ConfirmRequest, now: datetime = NOW) -> Result[OrderConfirmation]:
    return SqlErpFacade(app, FrozenClock(now)).confirm(COMPANY, request)


def counts(app: Engine) -> list[int]:
    with app.connect() as conn:
        tables = (erp.sales_order, erp.sales_order_line)
        return [conn.scalar(sa.select(sa.func.count()).select_from(x)) or 0 for x in tables]


@contextmanager
def hooked(app: Engine, **hooks: Callable[..., None]) -> Iterator[None]:
    for name, hook in hooks.items():
        sa.event.listen(app, name, hook)
    try:
        yield
    finally:
        for name, hook in hooks.items():
            sa.event.remove(app, name, hook)


def test_a_valid_proposal_stores_one_order_and_the_message_comes_from_it(app: Engine) -> None:
    """S5.1, S5.4: the confirmation and its text are built from the stored order."""
    (orders, lines), request = counts(app), proposal()
    result = confirm(app, request)
    assert isinstance(result, Ok)
    done = result.value
    assert (done.proposal_id, done.customer_id) == (request.proposal_id, request.customer_id)
    assert done.lines == (QuoteLine(COLA, 20, Money(245_000), Money(4_900_000)),)
    assert (done.total, done.delivery_date, done.received_at) == (Money(4_900_000), THURSDAY, NOW)
    assert done.message == (
        "Listo, tu pedido quedó confirmado por $ 49.000,00. Entrega programada: jueves 19/11/2026."
    )
    assert counts(app) == [orders + 1, lines + 1]


@pytest.mark.parametrize(
    ("request_", "now", "code"),
    [
        (proposal(("COLA-225", 20, 240_000)), NOW, ErrorCode.PRICE_CHANGED),  # it went up
        (proposal(("COLA-225", 20, 250_000)), NOW, ErrorCode.PRICE_CHANGED),  # it went down
        # the total equals today's, so only the line price can reject these two
        (proposal(("COLA-225", 20, 240_000), total=4_900_000), NOW, ErrorCode.PRICE_CHANGED),
        (proposal(("COLA-225", 20, 250_000), total=4_900_000), NOW, ErrorCode.PRICE_CHANGED),
        (proposal(total=4_800_000), NOW, ErrorCode.PRICE_CHANGED),  # only the total differs
        (proposal(), datetime(2026, 11, 18, 18, tzinfo=BA), ErrorCode.DELIVERY_DATE_CHANGED),
        (proposal(day=date(2026, 11, 23)), NOW, ErrorCode.DELIVERY_DATE_CHANGED),
        (proposal(customer="C-008"), NOW, ErrorCode.CUSTOMER_NOT_FOUND),  # inactive
        (proposal(("COLA-225", 12, 245_000)), NOW, ErrorCode.BELOW_MINIMUM_AMOUNT),
        (proposal(("COLA-225", 12, 300_000)), NOW, ErrorCode.PRICE_CHANGED),  # a drop below it
        (proposal(), datetime(2025, 12, 31, tzinfo=BA), ErrorCode.PRICE_NOT_AVAILABLE),
        (proposal(("COLA-225", 20, 245_000), ("GASE-VIE", 1, 1)), NOW, ErrorCode.PRODUCT_NOT_FOUND),
        (proposal(("COLA-225", 0, 245_000)), NOW, ErrorCode.INVALID_QUANTITY),
        (replace(proposal(), proposal_id=BAD), NOW, ErrorCode.PROPOSAL_NOT_FOUND),
        (replace(proposal(), customer_id=BAD), NOW, ErrorCode.CUSTOMER_NOT_FOUND),
    ],
)
def test_a_rejection_returns_a_catalog_code_and_message_and_writes_nothing(
    app: Engine, request_: ConfirmRequest, now: datetime, code: ErrorCode
) -> None:
    """S5.3, D4; S5.4 and S6.1: the code and its customer message come from the catalog."""
    before = counts(app)
    result = confirm(app, request_, now)
    assert result == Failure(code) and result.message == ERROR_MESSAGES[code]
    assert counts(app) == before


@pytest.mark.parametrize("failing", ["SELECT erp.product.id", "INSERT INTO erp.sales_order_line"])
def test_a_database_error_gives_rules_unavailable_and_writes_nothing(
    app: Engine, caplog: pytest.LogCaptureFixture, failing: str
) -> None:
    """Fail closed (§6): a failed price read, or a failed line write after the order row."""

    def fail(*args: Any) -> None:
        if args[2].startswith(failing):
            raise OperationalError("SELECT 1", {"x": 9}, Exception("down"))

    before = counts(app)
    with hooked(app, before_cursor_execute=fail):
        assert confirm(app, proposal()) == Failure(ErrorCode.RULES_UNAVAILABLE)
    assert counts(app) == before
    [log] = caplog.records  # the read and the company, never the query or its parameters
    assert log.getMessage() == f"confirm failed for company {COMPANY}: OperationalError"
    assert log.exc_info is None


def test_a_statement_bug_raises_instead_of_failing_closed(app: Engine) -> None:
    def bug(*_: Any) -> None:
        raise sa.exc.ArgumentError("a bug, not an unreadable rule")

    with hooked(app, before_cursor_execute=bug), pytest.raises(sa.exc.ArgumentError):
        confirm(app, proposal())


def test_every_read_and_the_write_share_one_company_scoped_transaction(app: Engine) -> None:
    """B40: the rule data is read inside the transaction that stores the order (R15)."""
    seen: list[tuple[str, Any]] = []
    hooks = {n: lambda *_, n=n: seen.append((n, {})) for n in ("begin", "commit", "rollback")}
    with hooked(app, before_cursor_execute=lambda *a: seen.append(a[2:4]), **hooks):
        assert isinstance(confirm(app, proposal()), Ok)
    assert [s for s, _ in seen if s in hooks] == ["begin", "commit"]
    assert (seen[0][0], seen[-1][0]) == ("begin", "commit")
    selects = [p for s, p in seen if s.startswith("SELECT")]
    assert len(selects) == 2  # the customer and the prices
    for params in selects:
        assert {v for k, v in params.items() if k.startswith("company_id")} == {COMPANY}

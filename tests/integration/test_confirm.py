"""`confirm`: the second check and the only write, one order per proposal id (R5, R6, §6)."""

import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime
from typing import Any, cast
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError

from dale.erp_sim.infrastructure import tables as erp
from dale.erp_sim.infrastructure.facade import SqlErpFacade
from dale.erp_sim.infrastructure.repositories import SqlOrderData
from dale.erp_sim.infrastructure.seed import el_hornero
from dale.erp_sim.public import ConfirmLine, ConfirmRequest, OrderConfirmation, OrderLine
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
    assert done.lines == (OrderLine(COLA, 20, Money(245_000), Money(4_900_000)),)
    assert (done.total, done.delivery_date, done.received_at) == (Money(4_900_000), THURSDAY, NOW)
    assert done.message == (
        "Listo, tu pedido quedó confirmado por $ 49.000,00. Entrega programada: jueves 19/11/2026."
    )
    assert counts(app) == [orders + 1, lines + 1]


def test_a_retry_returns_the_stored_confirmation_even_after_the_rules_changed(app: Engine) -> None:
    """S5.2 and a retry after a crash: the stored order answers; the rules are not re-run."""
    request = proposal()
    first, before = confirm(app, request), counts(app)
    later = datetime(2026, 12, 1, tzinfo=BA)  # by now a new price and a missed cutoff
    assert isinstance(first, Ok) and confirm(app, request, later) == first
    assert counts(app) == before


TWENTY_ONE: dict[str, Any] = {
    "lines": (ConfirmLine(COLA, 21, Money(245_000)),),
    "total": Money(5_145_000),
}


@pytest.mark.parametrize(
    "change",
    [
        TWENTY_ONE,
        {"customer_id": CustomerId(el_hornero.row_id("customer", "C-002"))},
        {"delivery_date": date(2026, 11, 23)},
        {"total": Money(4_900_001)},
    ],
)
def test_the_same_id_with_another_payload_is_not_pending(app: Engine, change: Any) -> None:
    """B45: only an identical replay returns the stored confirmation."""
    request = proposal()
    stored, before = confirm(app, request), counts(app)
    assert confirm(app, replace(request, **change)) == Failure(ErrorCode.PROPOSAL_NOT_PENDING)
    assert counts(app) == before and confirm(app, request) == stored


LIMA, NARA, POME = ("LIMA-225", 10, 235_000), ("NARA-225", 10, 235_000), ("POME-225", 10, 235_000)


@pytest.mark.parametrize(
    "lines",
    [
        (LIMA, POME),  # another product
        (("LIMA-225", 12, 235_000), ("NARA-225", 8, 235_000)),  # other quantities
        (("LIMA-225", 10, 240_000), ("NARA-225", 10, 230_000)),  # other unit prices
        (LIMA,),  # a line fewer
    ],
)
def test_a_replay_that_differs_in_any_line_field_is_not_pending(
    app: Engine, lines: tuple[tuple[str, int, int], ...]
) -> None:
    """B45: lines compare product by product, quantity and unit price; the total alone is not it."""
    request = proposal(LIMA, NARA)
    stored, before = confirm(app, request), counts(app)
    assert isinstance(stored, Ok) and stored.value.total == Money(4_700_000)
    other = replace(request, lines=proposal(*lines).lines, total=request.total)  # equal total
    assert confirm(app, other) == Failure(ErrorCode.PROPOSAL_NOT_PENDING)
    assert counts(app) == before and confirm(app, request) == stored


def test_replayed_lines_in_another_order_match_but_another_multiset_does_not(app: Engine) -> None:
    """Stored lines keep no order, and a repeated line counts twice: a multiset, not a set."""
    request = proposal(LIMA, LIMA, NARA)
    stored, before = confirm(app, request), counts(app)
    assert isinstance(stored, Ok)
    for same in (proposal(NARA, LIMA, LIMA), proposal(LIMA, NARA, LIMA)):
        assert confirm(app, replace(request, lines=same.lines)) == stored
    other = replace(request, lines=proposal(LIMA, NARA, NARA).lines)  # the same set, same total
    assert confirm(app, other) == Failure(ErrorCode.PROPOSAL_NOT_PENDING)
    assert counts(app) == before


@pytest.fixture(params=[None, "REPEATABLE READ"], ids=["default_level", "repeatable_read"])
def racing(app: Engine, request: pytest.FixtureRequest) -> Iterator[Engine]:
    """The app engine, and one whose default is REPEATABLE READ: its snapshot, taken at the first
    statement, would hide the race winner's row from the loser's re-read unless the store pins
    READ COMMITTED itself."""
    engine = (
        app
        if request.param is None
        else sa.create_engine(app.url, isolation_level="REPEATABLE READ")
    )
    yield engine
    if engine is not app:
        engine.dispose()


@pytest.mark.parametrize("same_payload", [True, False])
def test_concurrent_confirms_store_one_order(
    app: Engine, racing: Engine, same_payload: bool
) -> None:
    """S5.2 concurrent: both pass the lookup, then race on INSERT ... ON CONFLICT DO NOTHING."""
    request = proposal()
    other = request if same_payload else replace(request, **TWENTY_ONE)
    both = threading.Barrier(2, timeout=10)

    def meet(*args: Any) -> None:  # (conn, cursor, statement, ...): hold both at the insert
        if args[2].startswith("INSERT INTO erp.sales_order "):
            both.wait()

    (orders, lines) = counts(app)
    with hooked(racing, before_cursor_execute=meet), ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda r: confirm(racing, r), (request, other)))
    assert counts(app) == [orders + 1, lines + 1]
    [won] = {r for r in results if isinstance(r, Ok)}  # one confirmation, maybe returned twice
    assert results.count(won) == (2 if same_payload else 1)
    assert same_payload or Failure(ErrorCode.PROPOSAL_NOT_PENDING) in results


def test_an_order_missing_after_the_write_raises_and_rolls_back(app: Engine) -> None:
    """The answer comes from the stored order: if the re-read finds none, nothing is confirmed."""
    before = counts(app)
    no_order = patch.object(SqlOrderData, "find_order", return_value=None)
    with no_order, pytest.raises(RuntimeError, match="missing"):
        confirm(app, proposal())
    assert counts(app) == before  # the insert rolled back with the failure


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
    assert isinstance(result, Failure) and result.code is code  # below the minimum: a subtype
    assert result.message == ERROR_MESSAGES[code]
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
    assert len(selects) == 5  # the order lookup, customer, prices, then the order and its lines
    for params in selects:
        assert {v for k, v in params.items() if k.startswith("company_id")} == {COMPANY}


def find(app: Engine, proposal_id: Any) -> Result[OrderConfirmation | None]:
    return SqlErpFacade(app, FrozenClock(NOW)).find_order(COMPANY, proposal_id)


def test_find_order_answers_as_a_replay_does_and_writes_nothing(app: Engine) -> None:
    """B68: the read-only lookup returns the stored confirmation, or None before the write."""
    request = proposal()
    assert find(app, request.proposal_id) == Ok(None) == find(app, BAD)
    stored, before = confirm(app, request), counts(app)
    assert isinstance(stored, Ok) and find(app, request.proposal_id) == stored
    assert counts(app) == before


def test_find_order_fails_closed_only_on_a_database_error(
    app: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    request = proposal()
    confirm(app, request)

    def fail(*args: Any) -> None:
        if args[2].startswith("SELECT erp.sales_order"):
            raise OperationalError("SELECT 1", {"x": 9}, Exception("down"))

    with hooked(app, before_cursor_execute=fail):
        assert find(app, request.proposal_id) == Failure(ErrorCode.RULES_UNAVAILABLE)
    assert caplog.messages == [f"find_order failed for company {COMPANY}: OperationalError"]

    def bug(*_: Any) -> None:
        raise sa.exc.ArgumentError("a bug, not an unreadable order")

    with hooked(app, before_cursor_execute=bug), pytest.raises(sa.exc.ArgumentError):
        find(app, request.proposal_id)

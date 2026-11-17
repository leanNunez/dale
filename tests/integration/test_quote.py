"""`quote` on the seeded DB: server prices, the delivery cutoff, no writes, fail closed (R2, R3)."""

from datetime import datetime
from typing import Any, cast
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.exc import ArgumentError, OperationalError

from dale.brain.infrastructure import tables as brain
from dale.erp_sim.application.quote import RuleData, quote
from dale.erp_sim.infrastructure import tables as erp
from dale.erp_sim.infrastructure.facade import SqlErpFacade
from dale.erp_sim.infrastructure.repositories import SqlRuleData, of_company
from dale.erp_sim.infrastructure.seed import el_hornero
from dale.erp_sim.public import ErpFacade, Quote, QuoteLineRequest, QuoteRequest
from dale.shared.clock import FrozenClock
from dale.shared.errors import ErrorCode, Failure, Ok, Result
from dale.shared.ids import CompanyId, CustomerId, ProductId
from dale.shared.money import Money

pytestmark = pytest.mark.integration
BA = ZoneInfo(el_hornero.TIMEZONE)
COMPANY = CompanyId(el_hornero.COMPANY_ID)
NOW = datetime(2026, 11, 18, 9, tzinfo=BA)
EARLY = datetime(2025, 12, 31, 23, 59, tzinfo=BA)  # before the first price list


def ask(
    source: Engine | RuleData, now: datetime, customer: str, *lines: tuple[str, int]
) -> Result[Quote]:
    """Through the wired facade on an engine, or straight to `quote` on a fake rule source."""
    items = tuple(QuoteLineRequest(ProductId(el_hornero.row_id("product", s)), q) for s, q in lines)
    request = QuoteRequest(CustomerId(el_hornero.row_id("customer", customer)), items)
    if isinstance(source, Engine):
        facade: ErpFacade = SqlErpFacade(source, FrozenClock(now))
        return facade.quote(COMPANY, request)
    return quote(COMPANY, request, source, FrozenClock(now))


@pytest.mark.parametrize(
    ("now", "customer", "day", "cents"),
    [  # Norte: Tuesday and Friday, cutoff 16:00 the day before. Centro: Monday and Thursday, 18:00
        (datetime(2026, 11, 16, 15, 59), "C-003", "2026-11-17", 245_000),
        (datetime(2026, 11, 16, 16, 0), "C-003", "2026-11-20", 245_000),
        (datetime(2026, 11, 18, 17, 59), "C-001", "2026-11-19", 245_000),
        (datetime(2026, 11, 18, 18, 1), "C-001", "2026-11-23", 245_000),
        (datetime(2026, 11, 22, 23, 0), "C-001", "2026-11-26", 245_000),  # Sunday, past 18:00
        (datetime(2026, 11, 30, 23, 59, 59), "C-001", "2026-12-03", 245_000),
        (datetime(2026, 12, 1, 0, 0), "C-001", "2026-12-03", 290_000),  # the future price starts
    ],
)
def test_seeded_cutoffs_and_current_prices(
    app: Engine, now: datetime, customer: str, day: str, cents: int
) -> None:
    result = ask(app, now.replace(tzinfo=BA), customer, ("COLA-225", 19))
    assert isinstance(result, Ok)
    assert (str(result.value.delivery_date), result.value.total) == (day, Money(19 * cents))


@pytest.mark.parametrize(
    ("now", "customer", "lines", "code"),
    [
        (NOW, "C-008", [("COLA-225", 20)], ErrorCode.CUSTOMER_NOT_FOUND),  # inactive
        (NOW, "C-999", [("COLA-225", 20)], ErrorCode.CUSTOMER_NOT_FOUND),  # unknown
        (NOW, "C-001", [("COLA-225", 20), ("GASE-VIE", 1)], ErrorCode.PRODUCT_NOT_FOUND),
        (NOW, "C-001", [("COLA-225", 20), ("NOPE-1", 1)], ErrorCode.PRODUCT_NOT_FOUND),
        (NOW, "C-001", [("COLA-225", 12)], ErrorCode.BELOW_MINIMUM_AMOUNT),  # $29,400 < $30,000
        (EARLY, "C-001", [("COLA-225", 20)], ErrorCode.PRICE_NOT_AVAILABLE),
    ],
)
def test_rule_failures_on_seeded_data(
    app: Engine, now: datetime, customer: str, lines: list[tuple[str, int]], code: ErrorCode
) -> None:
    assert ask(app, now, customer, *lines) == Failure(code)


def test_quote_writes_nothing_and_fails_closed_only_on_database_errors(
    app: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    def counts() -> list[int]:
        with app.connect() as conn:
            tables = [*erp.METADATA.sorted_tables, *brain.METADATA.sorted_tables]
            return [conn.scalar(sa.select(sa.func.count()).select_from(x)) or 0 for x in tables]

    before = counts()
    assert isinstance(ask(app, NOW, "C-001", ("COLA-225", 20)), Ok)
    broken = Mock(wraps=SqlRuleData(app))  # the customer read works; the price read raises
    broken.current_prices.side_effect = OperationalError("SELECT 1", {"x": 9}, Exception("down"))
    assert ask(broken, NOW, "C-001", ("COLA-225", 20)) == Failure(ErrorCode.RULES_UNAVAILABLE)
    assert counts() == before
    [log] = caplog.records  # the read and the company, never the query or its parameters
    assert log.getMessage() == f"quote failed for company {COMPANY}: OperationalError"
    assert log.exc_info is None
    broken.current_prices.side_effect = ArgumentError("a bug")  # a statement bug, not a failed read
    with pytest.raises(ArgumentError, match="a bug"):  # it propagates
        ask(broken, NOW, "C-001", ("COLA-225", 20))


def test_each_line_carries_managements_product_name(app: Engine) -> None:
    """B61: the summary names come from the catalog: name, brand and size, never the model."""
    result = ask(app, NOW, "C-001", ("COLA-225", 20), ("AGUA-6X2", 2))
    assert isinstance(result, Ok)
    names = {x.product_id: x.name for x in result.value.lines}
    assert names == {
        el_hornero.row_id("product", "COLA-225"): "Gaseosa cola Burbuja 2,25 L",
        el_hornero.row_id("product", "AGUA-6X2"): "Agua sin gas pack Manantial Sur 6 x 2 L",
    }
    gone = Mock(wraps=SqlRuleData(app))  # deactivated between the price and the name reads
    gone.product_names.return_value = {}
    assert ask(gone, NOW, "C-001", ("COLA-225", 20)) == Failure(ErrorCode.PRODUCT_NOT_FOUND)


def test_a_name_skips_blank_parts_and_a_product_with_no_name_is_not_found(app: Engine) -> None:
    """B83: an empty brand or size leaves no stray space; with no name to show, fail closed."""
    p, cola = erp.product, el_hornero.row_id("product", "COLA-225")
    with app.connect() as conn:
        kept = conn.execute(sa.select(p.c.name, p.c.brand, p.c.presentation).where(p.c.id == cola))
        before = kept.one()._asdict()

    def change(**values: str) -> None:
        with app.begin() as conn:
            conn.execute(sa.update(p).where(p.c.id == cola).values(**values))

    try:
        change(brand="", presentation=" ")
        result = ask(app, NOW, "C-001", ("COLA-225", 20))
        assert isinstance(result, Ok) and result.value.lines[0].name == "Gaseosa cola"
        change(name="  ")
        assert ask(app, NOW, "C-001", ("COLA-225", 20)) == Failure(ErrorCode.PRODUCT_NOT_FOUND)
    finally:
        change(**before)


def test_ids_that_do_not_parse_are_not_found(app: Engine) -> None:
    facade, bad = SqlErpFacade(app, FrozenClock(NOW)), cast(Any, "not-a-uuid")
    c001, cola = el_hornero.row_id("customer", "C-001"), el_hornero.row_id("product", "COLA-225")
    lines = (QuoteLineRequest(ProductId(cola), 20),)
    assert facade.quote(COMPANY, QuoteRequest(bad, lines)) == Failure(ErrorCode.CUSTOMER_NOT_FOUND)
    for wrong in (bad, cast(Any, 7)):
        request = QuoteRequest(CustomerId(c001), (*lines, QuoteLineRequest(wrong, 1)))
        assert facade.quote(COMPANY, request) == Failure(ErrorCode.PRODUCT_NOT_FOUND)


def test_every_rule_query_filters_by_the_company(app: Engine) -> None:
    """S15.2: every statement binds the requested company_id, and only that one."""
    seen: list[dict[str, Any]] = []
    record = lambda *args: seen.append(args[3])  # noqa: E731 (conn, cursor, sql, params, ...)
    sa.event.listen(app, "before_cursor_execute", record)
    facade = SqlErpFacade(app, FrozenClock(NOW))
    c001, cola = el_hornero.row_id("customer", "C-001"), el_hornero.row_id("product", "COLA-225")
    try:
        assert isinstance(ask(app, NOW, "C-001", ("COLA-225", 20)), Ok)
        assert isinstance(facade.search_products(COMPANY, "cola"), Ok)
        assert isinstance(facade.get_prices(COMPANY, [ProductId(cola)]), Ok)
        assert isinstance(facade.check_delivery(COMPANY, CustomerId(c001)), Ok)
    finally:
        sa.event.remove(app, "before_cursor_execute", record)
    assert len(seen) == 6  # quote reads customer and zone, prices, names; each other read once
    for params in seen:
        assert {v for k, v in params.items() if k.startswith("company_id")} == {COMPANY}
    with pytest.raises(TypeError, match="company_id"):
        of_company(erp.product, None)  # type: ignore[arg-type]

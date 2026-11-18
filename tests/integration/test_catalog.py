"""Catalog reads through the facade on the seeded DB (R1: S1.1 and S1.3 data side)."""

from collections.abc import Callable
from datetime import date, datetime
from typing import Any, cast
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import Engine
from sqlalchemy.exc import ArgumentError, OperationalError

from dale.erp_sim.application.catalog import check_delivery, get_prices, search_products
from dale.erp_sim.infrastructure.facade import SqlErpFacade
from dale.erp_sim.infrastructure.seed import el_hornero
from dale.erp_sim.public import Delivery, ErpFacade, ProductPrice
from dale.shared.clock import FrozenClock
from dale.shared.errors import ErrorCode, Failure, Ok
from dale.shared.ids import CompanyId, CustomerId, ProductId
from dale.shared.money import Money

pytestmark = pytest.mark.integration
BA = ZoneInfo(el_hornero.TIMEZONE)
COMPANY = CompanyId(el_hornero.COMPANY_ID)
NOW = datetime(2026, 11, 16, 15, 59, tzinfo=BA)  # Monday, a minute before the Norte cutoff


def erp(app: Engine, now: datetime = NOW) -> ErpFacade:
    return SqlErpFacade(app, FrozenClock(now))


def product(sku: str) -> ProductId:
    return ProductId(el_hornero.row_id("product", sku))


def skus(app: Engine, query: str) -> list[str]:
    result = erp(app).search_products(COMPANY, query)
    assert isinstance(result, Ok)
    return [m.sku for m in result.value]


def test_search_finds_the_cola_by_its_spoken_size_and_lists_every_ambiguous_match(
    app: Engine,
) -> None:
    assert skus(app, "la cola de dos y cuarto")[0] == "COLA-225"  # S1.1
    assert skus(app, "cerveza") == ["CERV-12", "CERV-LAT", "CERV-LIT", "CERV-NEG"]  # S1.3, a tie
    assert skus(app, "limones") == ["LIMA-225"] and skus(app, "jabones") == ["JABO-PAN"]
    liters = ["AGUA-2", "AGUA-6X2", "AGUA-GAS-15", "CERV-LIT", "CERV-NEG", "COLA-15", "COLA-225"]
    assert skus(app, "l") == [*liters, "LAVA-3L", "LECH-1", "LIMA-225"]  # 14 tie; sku order cuts
    assert skus(app, "descontinuada") == []  # the only match is inactive
    assert "GASE-VIE" not in skus(app, "gaseosa cola vieja")


def test_get_prices_returns_current_prices_and_leaves_out_what_cannot_be_sold(
    app: Engine,
) -> None:
    ids = [product(s) for s in ("COLA-225", "GASE-VIE", "NOPE-1", "COLA-225")]
    assert erp(app).get_prices(COMPANY, ids) == Ok((ProductPrice(ids[0], Money(245_000)),))
    december = erp(app, datetime(2026, 12, 1, tzinfo=BA)).get_prices(COMPANY, ids[:1])
    assert december == Ok((ProductPrice(ids[0], Money(290_000)),))


def customer(code: str) -> CustomerId:
    return CustomerId(el_hornero.row_id("customer", code))


def test_check_delivery_gives_the_next_date_its_deadline_and_the_minimum(app: Engine) -> None:
    deadline = datetime(2026, 11, 16, 16, tzinfo=BA)  # Norte: Tuesday, cutoff 16:00 on Monday
    expected = Delivery(date(2026, 11, 17), deadline, Money(4_500_000))
    assert erp(app).check_delivery(COMPANY, customer("C-003")) == Ok(expected)
    missed = erp(app, deadline).check_delivery(COMPANY, customer("C-003"))
    assert isinstance(missed, Ok) and missed.value.delivery_date == date(2026, 11, 20)
    assert erp(app).check_delivery(COMPANY, customer("C-008")) == Failure(
        ErrorCode.CUSTOMER_NOT_FOUND
    )


READS: dict[str, Callable[[Mock], object]] = {
    "search_products": lambda data: search_products(COMPANY, "cola", data),
    "get_prices": lambda data: get_prices(COMPANY, [product("COLA-225")], data, FrozenClock(NOW)),
    "check_delivery": lambda data: check_delivery(
        COMPANY, customer("C-001"), data, FrozenClock(NOW)
    ),
}


def broken(error: Exception) -> Mock:
    return Mock(
        **{f"{r}.side_effect": error for r in ("customer", "current_prices", "active_products")}
    )


@pytest.mark.parametrize("read", READS)
def test_catalog_reads_fail_closed_only_on_database_errors(
    read: str, caplog: pytest.LogCaptureFixture
) -> None:
    down = broken(OperationalError("SELECT 1", {"x": 9}, Exception("down")))
    assert READS[read](down) == Failure(ErrorCode.RULES_UNAVAILABLE)
    assert caplog.messages == [f"{read} failed for company {COMPANY}: OperationalError"]
    with pytest.raises(ArgumentError, match="a bug"):  # a statement bug, not a failed read
        READS[read](broken(ArgumentError("a bug")))


def test_ids_that_do_not_parse_are_unknown_and_a_missing_company_raises(app: Engine) -> None:
    bad, cola = cast(Any, "not-a-uuid"), product("COLA-225")
    assert erp(app).get_prices(COMPANY, [bad, cola]) == Ok((ProductPrice(cola, Money(245_000)),))
    assert erp(app).check_delivery(COMPANY, bad) == Failure(ErrorCode.CUSTOMER_NOT_FOUND)
    with pytest.raises(TypeError, match="company_id"):  # a programming error, not an outage
        erp(app).search_products(cast(Any, None), "cola")

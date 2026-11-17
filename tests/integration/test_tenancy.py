"""Two companies with the same ids, SKUs, codes and zone names never see each other (R15)."""

from datetime import date, datetime, time
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine

from dale.erp_sim.infrastructure import tables as t
from dale.erp_sim.infrastructure.facade import SqlErpFacade
from dale.erp_sim.infrastructure.seed import el_hornero
from dale.erp_sim.public import Delivery, ProductPrice, QuoteLineRequest, QuoteRequest
from dale.shared.clock import FrozenClock
from dale.shared.errors import ErrorCode, Failure, Ok
from dale.shared.ids import CompanyId, CustomerId, ProductId
from dale.shared.money import Money

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("twin")]
HORNERO, TWIN = CompanyId(el_hornero.COMPANY_ID), CompanyId(uuid5(NAMESPACE_URL, "dale:twin"))
BA, TOKYO = ZoneInfo(el_hornero.TIMEZONE), ZoneInfo("Asia/Tokyo")
NOW = datetime(2026, 11, 17, 6, tzinfo=BA)  # 18:00 in Tokyo: past the twin's cutoff only there
JUNE = datetime(2026, 6, 1, tzinfo=TOKYO)  # a twin price row that El Hornero does not have
TZ = {"timezone": "Asia/Tokyo"}


@pytest.fixture(scope="module")
def twin(app: Engine) -> None:
    """El Hornero's rows under another company, with other prices, zone rules and timezone.
    The `app` fixture removes them with every other erp row."""
    data, own = el_hornero.build({}), {"company_id": TWIN}
    rule = {"delivery_weekdays": [3], "cutoff_time": time(8), "min_order_amount_cents": 100}
    june = {**own, "product_id": el_hornero.row_id("product", "COLA-225"), "valid_from": JUNE}
    prices = [r | own | {"unit_price_cents": r["unit_price_cents"] + 100} for r in data["prices"]]
    with app.begin() as conn:
        conn.execute(sa.insert(t.company), {"id": TWIN, "slug": "twin", "name": "Twin"} | TZ)
        conn.execute(sa.insert(t.zone), [r | own | rule for r in data["zones"]])
        for table, rows in ((t.customer, data["customers"]), (t.product, data["products"])):
            conn.execute(sa.insert(table), [r | own | {"active": True} for r in rows])
        conn.execute(sa.insert(t.product_price), [*prices, june | {"unit_price_cents": 111_100}])


def quote(app: Engine, company: CompanyId, customer: str, sku: str, n: int) -> object:
    line = QuoteLineRequest(ProductId(el_hornero.row_id("product", sku)), n)
    request = QuoteRequest(CustomerId(el_hornero.row_id("customer", customer)), (line,))
    result = SqlErpFacade(app, FrozenClock(NOW)).quote(company, request)
    return (result.value.total, result.value.delivery_date) if isinstance(result, Ok) else result


def test_each_company_quotes_with_its_own_prices_customers_zones_and_timezone(app: Engine) -> None:
    hornero, twin = date(2026, 11, 19), date(2026, 11, 25)  # Thursday; Wednesday next week
    assert quote(app, HORNERO, "C-001", "COLA-225", 20) == (Money(4_900_000), hornero)
    assert quote(app, TWIN, "C-001", "COLA-225", 20) == (Money(2_222_000), twin)
    assert quote(app, HORNERO, "C-008", "COLA-225", 20) == Failure(ErrorCode.CUSTOMER_NOT_FOUND)
    assert quote(app, TWIN, "C-008", "COLA-225", 20) == (Money(2_222_000), twin)
    assert quote(app, HORNERO, "C-001", "GASE-VIE", 20) == Failure(ErrorCode.PRODUCT_NOT_FOUND)
    assert quote(app, TWIN, "C-001", "GASE-VIE", 1) == (Money(290_100), twin)
    assert quote(app, HORNERO, "C-001", "COLA-225", 1) == Failure(ErrorCode.BELOW_MINIMUM_AMOUNT)
    assert quote(app, TWIN, "C-001", "COLA-225", 1) == (Money(111_100), twin)


def test_catalog_reads_return_only_the_requested_company(app: Engine) -> None:
    erp = SqlErpFacade(app, FrozenClock(NOW))
    c001 = CustomerId(el_hornero.row_id("customer", "C-001"))
    cola, old = (ProductId(el_hornero.row_id("product", s)) for s in ("COLA-225", "GASE-VIE"))
    assert erp.get_prices(HORNERO, [cola, old]) == Ok((ProductPrice(cola, Money(245_000)),))
    twin = (ProductPrice(cola, Money(111_100)), ProductPrice(old, Money(290_100)))
    assert erp.get_prices(TWIN, [cola, old]) == Ok(twin)
    hornero = Delivery(date(2026, 11, 19), datetime(2026, 11, 18, 18, tzinfo=BA), Money(3_000_000))
    assert erp.check_delivery(HORNERO, c001) == Ok(hornero)
    later = Delivery(date(2026, 11, 25), datetime(2026, 11, 24, 8, tzinfo=TOKYO), Money(100))
    assert erp.check_delivery(TWIN, c001) == Ok(later)
    colas = ["COLA-15", "COLA-225", "COLA-6X500"]  # the old cola is active only in the twin
    for company, expected in ((HORNERO, colas), (TWIN, ["GASE-VIE", *colas])):
        result = erp.search_products(company, "cola vieja")
        assert isinstance(result, Ok) and [m.sku for m in result.value] == expected

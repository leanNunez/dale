"""Visitor customers (DD31, W14 S14.3 port side): a new customer per demo conversation, from a
template, through a port of its own, removed by the reseed."""

import re
from collections.abc import Iterator
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine

from dale.erp_sim.infrastructure import tables as t
from dale.erp_sim.infrastructure.facade import SqlErpFacade, SqlVisitorCustomers
from dale.erp_sim.infrastructure.seed import el_hornero, reseed
from dale.erp_sim.public import SessionCustomer, VisitorCodeConflictError, VisitorCustomers
from dale.shared.clock import SystemClock
from dale.shared.errors import ErrorCode, Failure, Ok
from dale.shared.ids import SequentialIdGenerator

pytestmark = pytest.mark.integration
TEMPLATE = "C-001"  # Almacen Don Tito, zone Centro
OTHER = UUID("00000000-0000-0000-0000-00000000000e")  # a second company, same template code
CODE = re.compile(r"V-[0-9A-F]{10}")


@pytest.fixture
def erp(app: Engine) -> Iterator[Engine]:
    """The seeded app engine; reseeded before and after, so visitors never leak across tests."""
    reseed(app)
    yield app
    reseed(app)


@pytest.fixture
def other(erp: Engine) -> Iterator[None]:
    """Company `otra` with its own zone and a customer `C-001`; removed afterwards."""
    with erp.begin() as conn:
        conn.exec_driver_sql(
            f"INSERT INTO erp.company VALUES ('{OTHER}', 'otra', 'Otra', 'UTC');"
            f"INSERT INTO erp.zone VALUES ('{OTHER}', '{OTHER}', 'Oeste', '{{2}}', '18:00', 0);"
            f"INSERT INTO erp.customer VALUES ('{OTHER}', '{OTHER}', '{TEMPLATE}', 'Otro',"
            f" '{OTHER}', true)"
        )
    yield
    with erp.begin() as conn:
        for table in reversed(t.METADATA.sorted_tables):
            own = table.c.id if table is t.company else table.c.company_id
            conn.execute(sa.delete(table).where(own == OTHER))


def customers(
    engine: Engine, company: UUID = el_hornero.COMPANY_ID
) -> dict[UUID, tuple[str, str, UUID, bool]]:
    c = t.customer
    stmt = sa.select(c.c.id, c.c.code, c.c.name, c.c.zone_id, c.c.active)
    with engine.connect() as conn:
        rows = conn.execute(stmt.where(c.c.company_id == company))
        return {r[0]: tuple(r[1:]) for r in rows}


def visitor(port: VisitorCustomers) -> SessionCustomer:
    result = port.create_visitor(el_hornero.SLUG, TEMPLATE)
    assert isinstance(result, Ok)
    return result.value


def codes(*values: str) -> Iterator[str]:
    return iter(values)


def test_a_visitor_is_a_new_customer_with_the_template_zone_and_name(erp: Engine) -> None:
    before = customers(erp)
    created = visitor(SqlVisitorCustomers(erp))
    after = customers(erp)
    assert set(after) - set(before) == {created.customer_id}
    code, name, zone, active = after[created.customer_id]
    _, template_name, template_zone, _ = before[el_hornero.row_id("customer", TEMPLATE)]
    assert CODE.fullmatch(code) and (name, zone, active) == (template_name, template_zone, True)
    assert zone == el_hornero.row_id("zone", "Centro")
    assert created.customer_id.version == 4 and created.customer_id not in before
    assert (created.company_id, created.company_name) == (el_hornero.COMPANY_ID, el_hornero.NAME)
    with erp.connect() as conn:  # no orders of its own
        stmt = sa.select(sa.func.count()).where(t.sales_order.c.customer_id == created.customer_id)
        assert conn.execute(stmt).scalar_one() == 0
    found = SqlErpFacade(erp, SystemClock()).find_customer(el_hornero.SLUG, code)
    assert found == Ok(created)  # the brain's read path serves it like any seeded customer


def test_two_calls_give_two_customers(erp: Engine) -> None:
    port = SqlVisitorCustomers(erp)
    first, second = visitor(port), visitor(port)
    assert first.customer_id != second.customer_id
    rows = customers(erp)
    assert rows[first.customer_id][0] != rows[second.customer_id][0]


def test_a_taken_code_is_retried_once_with_a_new_one(erp: Engine) -> None:
    taken = visitor(SqlVisitorCustomers(erp, codes=codes("V-00000000AA").__next__))
    retried = SqlVisitorCustomers(erp, codes=codes("V-00000000AA", "V-00000000BB").__next__)
    created = visitor(retried)
    assert created.customer_id != taken.customer_id
    assert customers(erp)[created.customer_id][0] == "V-00000000BB"


def test_a_second_taken_code_raises_and_adds_no_customer(erp: Engine) -> None:
    visitor(SqlVisitorCustomers(erp, codes=codes("V-00000000AA").__next__))
    before = customers(erp)
    port = SqlVisitorCustomers(erp, codes=codes("V-00000000AA", "V-00000000AA").__next__)
    with pytest.raises(VisitorCodeConflictError):
        port.create_visitor(el_hornero.SLUG, TEMPLATE)
    assert customers(erp) == before


@pytest.mark.parametrize(
    ("slug", "code"),
    [(el_hornero.SLUG, "C-999"), (el_hornero.SLUG, "C-008"), ("otra", TEMPLATE)],
    ids=["unknown code", "inactive template", "unknown company"],
)
def test_an_unknown_or_inactive_template_is_customer_not_found(
    erp: Engine, slug: str, code: str
) -> None:
    before = customers(erp)
    result = SqlVisitorCustomers(erp).create_visitor(slug, code)
    assert result == Failure(ErrorCode.CUSTOMER_NOT_FOUND)
    assert customers(erp) == before


def test_the_read_only_verifier_role_creates_nothing(
    erp: Engine, engines: dict[str, Engine]
) -> None:
    before = customers(erp)
    result = SqlVisitorCustomers(engines["dale_verifier"]).create_visitor(el_hornero.SLUG, TEMPLATE)
    assert result == Failure(ErrorCode.RULES_UNAVAILABLE)  # fail closed, never a shared customer
    assert customers(erp) == before


def test_reseed_removes_visitors_and_keeps_the_template(erp: Engine) -> None:
    seeded = customers(erp)
    port = SqlVisitorCustomers(erp, SequentialIdGenerator())
    created = {visitor(port).customer_id for _ in range(3)}
    assert created <= set(customers(erp))
    reseed(erp)
    assert customers(erp) == seeded  # visitors gone, the template and the seed unchanged


@pytest.mark.usefixtures("other")
def test_the_template_and_the_visitor_belong_to_the_slug_company(erp: Engine) -> None:
    """Both companies hold a `C-001`: each visitor copies its own company's template, and the
    reseed removes only El Hornero's visitors."""
    port = SqlVisitorCustomers(erp)
    hornero = visitor(port)
    result = port.create_visitor("otra", TEMPLATE)
    assert isinstance(result, Ok)
    otra = result.value
    assert (otra.company_id, otra.company_name) == (OTHER, "Otra")
    assert customers(erp, OTHER)[otra.customer_id][1:] == ("Otro", OTHER, True)
    zone = customers(erp)[hornero.customer_id][2]
    assert (hornero.company_id, zone) == (
        el_hornero.COMPANY_ID,
        el_hornero.row_id("zone", "Centro"),
    )
    reseed(erp)
    assert hornero.customer_id not in customers(erp)
    assert set(customers(erp, OTHER)) == {OTHER, otra.customer_id}

"""Least privilege for the visitor write (DD31): it is a port of its own, never on the facade the
brain's tools hold, and no brain or channel module names it."""

import inspect
import secrets
from pathlib import Path

import pytest

from dale.brain.application.ports import ErpPort
from dale.erp_sim.application import visitors
from dale.erp_sim.infrastructure.facade import SqlErpFacade, SqlVisitorCustomers
from dale.erp_sim.public import ErpFacade, VisitorCustomers

SRC = Path(__file__).parents[3] / "src" / "dale"
# The v0.2 surface: reads, the quote, and `confirm`, the only order write.
FACADE = {
    "find_customer",
    "search_products",
    "get_prices",
    "check_delivery",
    "quote",
    "confirm",
    "find_order",
}


def members(cls: type) -> set[str]:
    return {name for name in vars(cls) if not name.startswith("_")}


def test_the_erp_facade_gains_no_write_method() -> None:
    assert members(ErpFacade) == FACADE
    assert members(SqlErpFacade) == FACADE
    assert not hasattr(ErpPort, "create_visitor")  # the port the brain's tools are built on


def test_the_visitor_port_is_its_own_protocol() -> None:
    assert members(VisitorCustomers) == {"create_visitor"}
    assert members(SqlVisitorCustomers) == {"create_visitor"}
    assert not issubclass(SqlErpFacade, SqlVisitorCustomers)
    assert not issubclass(SqlVisitorCustomers, SqlErpFacade)


def test_no_brain_or_channel_module_names_the_visitor_write() -> None:
    names = ("VisitorCustomers", "create_visitor", "insert_visitor")
    for package in ("brain", "channels"):
        for path in (SRC / package).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert not [n for n in names if n in text], path


def test_the_default_code_source_is_the_secrets_module(monkeypatch: pytest.MonkeyPatch) -> None:
    """The code is unguessable only if it comes from `secrets` (DD31): 5 bytes, 10 hex digits."""
    asked: list[int] = []

    def token_hex(nbytes: int) -> str:
        asked.append(nbytes)
        return "0a1b2c3d4e"

    monkeypatch.setattr(secrets, "token_hex", token_hex)
    assert visitors.random_code() == "V-0A1B2C3D4E" and asked == [5]
    for built in (visitors.create_visitor, SqlVisitorCustomers):
        assert inspect.signature(built).parameters["codes"].default is visitors.random_code

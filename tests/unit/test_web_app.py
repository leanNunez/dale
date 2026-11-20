"""The web composition root (D12, D17, W1): loopback only, one worker, no request timeout, the
settings, the start-up check of the customer, and the mapping of the runner's verdict onto the
web verdict."""

import inspect
from datetime import UTC, date, datetime
from pathlib import Path
from typing import ClassVar, cast
from uuid import UUID

import pytest
import sqlalchemy as sa
import uvicorn
from starlette.testclient import TestClient

from dale.apps import web
from dale.apps.verifier_runner import (
    TIMEOUT_SECONDS,
    Finding,
    StoredLine,
    StoredOrder,
    VerifierVerdict,
    unverifiable,
)
from dale.channels.web.app import create_app
from dale.channels.web.conversations import PRESS_WAIT
from dale.erp_sim.public import ErpFacade, SessionCustomer
from dale.shared.errors import ErrorCode, Failure, Ok, Result
from dale.shared.ids import CompanyId, CustomerId
from dale.shared.money import Money

REQUIRED = {
    "DALE_WEB_COMPANY": "el-hornero",
    "DALE_APP_DATABASE_URL": "postgresql+psycopg://app:s3cr3t@127.0.0.1/dale",
}
P, ORDER, C, ITEM = (UUID(int=n) for n in (1, 2, 3, 4))


def test_the_bind_host_is_loopback_and_nothing_changes_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """S1.1: no flag, no variable (ours or uvicorn's) moves the host off 127.0.0.1."""
    for name in ("DALE_WEB_HOST", "UVICORN_HOST", "HOST"):
        monkeypatch.setenv(name, "0.0.0.0")
    config = web.server_config(create_app(web.settings(REQUIRED).allow, lambda: True, None), 8000)
    assert web.HOST == config.host == "127.0.0.1" and config.workers == 1
    assert "host" not in inspect.signature(web.server_config).parameters
    with pytest.raises(SystemExit) as exited:
        web.main(["--host", "0.0.0.0"])
    assert exited.value.code == 2


def test_no_timeout_is_changed_from_uvicorn_defaults() -> None:
    """D17, B6: uvicorn has no request timeout, and the host sets none of its timeouts."""
    app = create_app(web.settings(REQUIRED).allow, lambda: True, None)
    ours, default = web.server_config(app, 8000), uvicorn.Config(app)
    names = [n for n in inspect.signature(uvicorn.Config).parameters if n.startswith("timeout")]
    assert names and all(getattr(ours, n) == getattr(default, n) for n in names)
    assert not ours.proxy_headers


def test_the_settings_default_to_the_fixed_customer_and_loopback() -> None:
    s = web.settings(REQUIRED)
    assert (s.port, s.company, s.customer) == (8000, "el-hornero", "C-001")
    assert s.allow.hosts == {"127.0.0.1:8000", "localhost:8000"}
    assert s.allow.origins == {"http://127.0.0.1:8000", "http://localhost:8000"}


def test_extra_allowed_names_add_to_loopback() -> None:
    """W17, S8.4: the allow-list is configuration, comma-separated."""
    env = {**REQUIRED, "DALE_WEB_PORT": "8100", "DALE_WEB_CUSTOMER": "C-002"}
    env |= {"DALE_WEB_ALLOWED_HOSTS": "Dale.Test:8443, ,", "DALE_WEB_ALLOWED_ORIGINS": ""}
    s = web.settings(env)
    assert s.customer == "C-002" and "dale.test:8443" in s.allow.hosts
    assert s.allow.hosts >= {"127.0.0.1:8100", "localhost:8100"} and len(s.allow.hosts) == 3
    assert s.allow.origins == {"http://127.0.0.1:8100", "http://localhost:8100"}


@pytest.mark.parametrize(
    ("env", "error"),
    [
        ({}, "DALE_WEB_COMPANY, DALE_APP_DATABASE_URL must be set"),
        ({**REQUIRED, "DALE_WEB_PORT": "80a"}, "DALE_WEB_PORT must be a port number"),
        ({**REQUIRED, "DALE_WEB_PORT": "70000"}, "DALE_WEB_PORT must be a port number"),
        ({**REQUIRED, "DALE_WEB_PORT": "٨٠"}, "DALE_WEB_PORT must be a port number"),
    ],
)
def test_bad_settings_stop_the_host(env: dict[str, str], error: str) -> None:
    with pytest.raises(web.SettingsError, match=f"^{error}$"):
        web.settings(env)


def test_main_exits_2_without_its_variables(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in REQUIRED:
        monkeypatch.delenv(name, raising=False)
    assert web.main([]) == 2
    assert capsys.readouterr().err.endswith("must be set\n")


class FakeErp:
    """erp_sim's port with one active customer, C-001 of el-hornero."""

    def find_customer(self, company_slug: str, customer_code: str) -> Result[SessionCustomer]:
        if (company_slug, customer_code) != ("el-hornero", "C-001"):
            return Failure(ErrorCode.CUSTOMER_NOT_FOUND)
        return Ok(SessionCustomer(CompanyId(UUID(int=7)), "El Hornero", CustomerId(UUID(int=8))))


class FakeServer:
    started: ClassVar[list[uvicorn.Config]] = []

    def __init__(self, config: uvicorn.Config) -> None:
        self.config = config

    def run(self) -> None:
        self.started.append(self.config)


@pytest.mark.parametrize(
    "env",
    [{"DALE_WEB_COMPANY": "nonexistent"}, {"DALE_WEB_CUSTOMER": "C-999"}],
    ids=["company", "customer"],
)
def test_an_unknown_company_or_customer_stops_the_host(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], env: dict[str, str]
) -> None:
    """D2 at start: the port answers both alike, so the message names both variables."""
    for name, value in {**REQUIRED, **env}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(uvicorn, "Server", FakeServer)
    FakeServer.started.clear()
    assert (
        web.main([], erp=lambda engine: cast(ErpFacade, FakeErp())) == 2
        and FakeServer.started == []
    )
    err = capsys.readouterr().err
    assert err == "DALE_WEB_COMPANY and DALE_WEB_CUSTOMER name no active customer\n"


def test_a_known_customer_starts_the_host(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("DALE_VERIFIER_DATABASE_URL", raising=False)  # not read until slice 5
    monkeypatch.setattr(uvicorn, "Server", FakeServer)
    FakeServer.started.clear()
    assert web.main([], erp=lambda engine: cast(ErpFacade, FakeErp())) == 0
    assert [c.port for c in FakeServer.started] == [8000]


def test_the_database_engine_has_a_short_connect_timeout() -> None:
    """A black-holed database fails `/health` within seconds, closed (503)."""
    engine, seen = web.database_engine(REQUIRED["DALE_APP_DATABASE_URL"]), dict[str, object]()

    @sa.event.listens_for(engine, "do_connect")
    def capture(dialect: object, record: object, args: object, params: dict[str, object]) -> None:
        seen.update(params)
        raise OSError("not connecting")

    with pytest.raises(OSError, match="not connecting"):
        engine.connect()
    assert seen["connect_timeout"] == web.CONNECT_TIMEOUT == 3


def test_no_route_sends_a_cors_header(tmp_path: Path) -> None:
    """S1.2: the composed host, page included, never answers with Access-Control-*."""
    (tmp_path / "index.html").write_text("<!doctype html>", encoding="utf-8")
    app = create_app(web.settings(REQUIRED).allow, lambda: True, tmp_path)
    headers = {"origin": "https://evil.example", "content-type": "application/json"}
    with TestClient(app, base_url="http://localhost:8000") as client:
        responses = [client.get(p, headers=headers) for p in ("/", "/health", "/v1/contract", "/x")]
        responses.append(client.post("/v1/contract", headers=headers))
        responses.append(client.options("/health", headers=headers))
    assert [r.status_code for r in responses] == [200, 200, 200, 404, 403, 403]
    assert not [h for r in responses for h in r.headers if h.lower().startswith("access-control")]


def stored(received: datetime, cents: int = 245_000) -> StoredOrder:
    line = StoredLine(
        product_id=ITEM, quantity=2, unit_price_cents=cents, line_total_cents=cents * 2
    )
    return StoredOrder(
        id=ORDER,
        proposal_id=P,
        customer_id=C,
        lines=(line,),
        total_cents=cents * 2,
        delivery_date=date(2026, 11, 20),
        received_at=received,
    )


def verified(order: StoredOrder) -> VerifierVerdict:
    found = Finding(kind="verified", proposal_id=P, order_id=ORDER, fields=())
    return VerifierVerdict(
        verdict="verified",
        reason="",
        findings=(found,),
        false_confirmations=0,
        unexpected_writes=0,
        stored_orders=(order,),
    )


def test_a_verified_verdict_carries_its_stored_order_in_money() -> None:
    """B17: `*_cents` become `Money`; the customer id is not carried."""
    shown = web.web_verdict(verified(stored(datetime(2026, 11, 19, 12, tzinfo=UTC))), P)
    assert (shown.verdict, shown.reason, shown.subject_proposal_id) == ("verified", "", P)
    [order] = shown.stored_orders
    assert (order.order_id, order.proposal_id, order.total) == (ORDER, P, Money(490_000))
    [line] = order.lines
    assert (line.product_id, line.quantity) == (ITEM, 2)
    assert (line.unit_price, line.line_total) == (Money(245_000), Money(490_000))
    assert shown.findings[0].kind == "verified" and shown.findings[0].order_id == ORDER


@pytest.mark.parametrize(
    ("reason", "shown"),
    [
        ("timeout", "timeout"),
        ("malformed_output", "malformed_output"),
        ("exit_3", "verifier_error"),
        ("OperationalError", "verifier_error"),
        ("verifier_failed", "verifier_error"),
    ],
)
def test_a_reason_outside_the_closed_set_becomes_verifier_error(reason: str, shown: str) -> None:
    """B25: the page can switch over every reason it can receive."""
    issued = web.web_verdict(unverifiable(reason), None)
    assert (issued.verdict, issued.reason, issued.stored_orders) == ("unverifiable", shown, ())


def test_a_verdict_the_web_type_cannot_carry_is_unverifiable() -> None:
    """Fail closed: a naive `received_at` is never shown as verified."""
    shown = web.web_verdict(verified(stored(datetime(2026, 11, 19, 12))), P)
    assert (shown.verdict, shown.reason, shown.findings) == ("unverifiable", "malformed_output", ())


def test_a_waiting_press_outlives_the_verifier_timeout() -> None:
    """B55: a press of the same id waits `PRESS_WAIT` for the running press, whose verifier
    gives up after its own timeout, so a slow verifier ends that press before the wait does."""
    assert TIMEOUT_SECONDS == 30 and PRESS_WAIT == 60 and TIMEOUT_SECONDS < PRESS_WAIT

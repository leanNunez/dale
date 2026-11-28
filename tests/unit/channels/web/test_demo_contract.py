"""The v0.3 additions to contract v1 (W5, W11; S5.5, S11.1, S11.4; DD42): five transport codes,
the `StartConversation` command and the `demo` field of `GET /v1/contract`."""

import json
from collections.abc import Iterator
from dataclasses import FrozenInstanceError, fields
from typing import Any, get_type_hints

import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient

from dale.apps.demo import settings as demo_settings
from dale.channels.web.app import build_api
from dale.channels.web.contract import (
    COMMANDS,
    ContractInfo,
    DemoInfo,
    ErrorBody,
    ResponseEnvelope,
    StartConversation,
)
from dale.channels.web.conversations import InMemoryRegistry
from dale.channels.web.demo import NOTICE, Visitor
from dale.channels.web.errors import WEB_MESSAGES, WebErrorCode, message_for, status_for
from dale.channels.web.guard import AllowList, RequestGuard
from dale.channels.web.schema_gen import CONTRACT_DIR, SCHEMA_TYPES
from dale.shared import shown_events
from dale.shared.errors import ErrorCode
from tests.unit.channels.web.test_conversations import FakeBackend

PORT = 8000
DEMO_CODES = {
    "rate_limited": (429, "Llegaste al límite de uso por ahora. Probá de nuevo más tarde."),
    "demo_paused": (503, "La demo está en pausa por ahora. Volvé a probar más tarde."),
    "demo_busy": (503, "Hay mucha gente probando la demo. Probá de nuevo en unos minutos."),
    "demo_reset": (410, "Esta conversación se borró con el reinicio de la demo. Empezá una nueva."),
    "notice_not_accepted": (403, "Para empezar tenés que aceptar el aviso de la demo."),
}


@pytest.mark.parametrize("value", DEMO_CODES)
def test_each_demo_code_has_its_fixed_status_and_spanish_message(value: str) -> None:
    """S11.4: one status and one Spanish message per code."""
    code = WebErrorCode(value)
    status, message = DEMO_CODES[value]
    assert (status_for(code), message_for(code)) == (status, message)


def test_the_demo_codes_are_in_the_web_catalog_alone_and_carry_no_usage() -> None:
    """S11.1: no code in both catalogs. S11.5: a fixed message has no count, id or address."""
    web = {c.value for c in WebErrorCode}
    assert set(DEMO_CODES) <= web and web.isdisjoint({c.value for c in ErrorCode})
    assert all(not any(ch.isdigit() for ch in WEB_MESSAGES[WebErrorCode(v)]) for v in DEMO_CODES)


def test_a_demo_code_never_appears_in_a_shown_event() -> None:
    """S11.4: a shown event's `code` is a brain code, so no transport code can be put in one."""
    for kind in shown_events.KINDS.values():
        assert get_type_hints(kind).get("code", ErrorCode) is ErrorCode
    assert set(DEMO_CODES).isdisjoint({c.value for c in ErrorCode})
    for value in DEMO_CODES:
        line = json.dumps({"type": "SystemNotice", "code": value, "message": "x"})
        with pytest.raises(ValueError):
            shown_events.from_json(line)


@pytest.mark.parametrize("value", DEMO_CODES)
def test_an_error_envelope_carries_a_demo_code_with_its_catalog_message(value: str) -> None:
    code = WebErrorCode(value)
    body = ErrorBody(code=code, message=message_for(code))
    envelope = ResponseEnvelope(
        conversation_id=None, seq=0, events=(), pending_proposal_id=None, error=body
    )
    assert json.loads(envelope.model_dump_json())["error"] == {
        "code": value,
        "message": DEMO_CODES[value][1],
    }
    with pytest.raises(ValidationError):
        ErrorBody(code=code, message="otro texto")


def test_start_conversation_is_a_command_with_one_optional_strict_field() -> None:
    assert COMMANDS["StartConversation"] is StartConversation
    assert StartConversation().notice_version is None  # an absent field is not a 422
    assert StartConversation(notice_version=1).notice_version == 1
    assert StartConversation.model_validate({"notice_version": 7}).notice_version == 7


@pytest.mark.parametrize(
    "body",
    [
        {"notice_version": 1, "customer_id": "C-001"},
        {"customer_id": "C-001"},
        {"notice_version": "1"},
        {"notice_version": 1.0},
        {"notice_version": True},
        {"notice_version": [1]},
    ],
    ids=["customer", "customer-alone", "text", "float", "bool", "list"],
)
def test_start_conversation_rejects_unknown_fields_and_loose_versions(body: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        StartConversation.model_validate(body)


def contract_of(demo: Any) -> Any:
    api = build_api(lambda: True, None, InMemoryRegistry(FakeBackend), demo)
    guard = RequestGuard(api, AllowList.loopback(PORT))
    with TestClient(guard, base_url=f"http://127.0.0.1:{PORT}") as client:
        return client.get("/v1/contract").json()


@pytest.fixture
def local() -> Iterator[Any]:
    yield contract_of(None)


def test_the_contract_route_reports_no_demo_in_local_mode(local: Any) -> None:
    assert local["demo"] is None and local["v"] == 1
    assert list(local) == ["v", "events", "commands", "demo"]  # the v0.2 keys, then the new one
    assert ContractInfo.model_validate_json(json.dumps(local)).demo is None


def test_the_contract_route_reports_the_notice_in_demo_mode() -> None:
    body = contract_of(NOTICE)
    assert body["demo"] == {"notice_version": NOTICE.version, "retention_days": 30}
    assert body["v"] == 1 and "StartConversation" in body["commands"]
    assert ContractInfo.model_validate_json(json.dumps(body)).demo == DemoInfo(
        notice_version=NOTICE.version, retention_days=NOTICE.retention_days
    )


def test_the_notice_and_the_visitor_are_small_frozen_values() -> None:
    assert (
        NOTICE.version >= 1 and NOTICE.retention_days == demo_settings.COUNTS["retention_days"][1]
    )
    with pytest.raises(FrozenInstanceError):
        NOTICE.version = 2  # type: ignore[misc]
    visitor = Visitor(session_hash=b"s" * 32, client_ip="198.51.100.9")
    assert [f.name for f in fields(visitor)] == ["session_hash", "client_ip"]
    assert "198.51.100.9" not in repr(visitor)  # the IP is for limits only, never logged in clear


def test_notice_json_is_the_notice_the_page_banner_belongs_to() -> None:
    """DD42: the generated file and the constant cannot drift."""
    text = (CONTRACT_DIR / "notice.json").read_text(encoding="utf-8")
    assert json.loads(text) == {
        "notice_version": NOTICE.version,
        "retention_days": NOTICE.retention_days,
    }


def test_the_demo_field_and_notice_json_share_their_key_names() -> None:
    """The page reads one shape from two places: the generated file and the route's `demo`."""
    notice = json.loads((CONTRACT_DIR / "notice.json").read_text(encoding="utf-8"))
    assert set(notice) == set(DemoInfo.model_fields)


def test_the_contract_body_is_a_published_schema() -> None:
    """The body of `GET /v1/contract` has a schema and a page type like every other wire type."""
    assert SCHEMA_TYPES["ContractInfo"] is ContractInfo
    schema = json.loads((CONTRACT_DIR / "ContractInfo.schema.json").read_text(encoding="utf-8"))
    assert set(schema["properties"]) == {"v", "events", "commands", "demo"}

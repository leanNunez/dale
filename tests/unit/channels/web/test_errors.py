"""One status and one Spanish message per code, in two disjoint catalogs (W11, S11.1)."""

import pytest

from dale.channels.web.errors import (
    WEB_MESSAGES,
    WEB_STATUS,
    WebErrorCode,
    message_for,
    status_for,
)
from dale.shared.errors import ErrorCode

ALL_CODES: list[WebErrorCode | ErrorCode] = [*ErrorCode, *WebErrorCode]


def test_the_two_catalogs_share_no_code() -> None:
    assert {c.value for c in ErrorCode}.isdisjoint({c.value for c in WebErrorCode})


def test_the_web_tables_cover_exactly_the_web_codes() -> None:
    assert set(WEB_STATUS) == set(WEB_MESSAGES) == set(WebErrorCode)


@pytest.mark.parametrize("code", ALL_CODES)
def test_every_code_has_a_client_or_server_status_and_a_message(
    code: WebErrorCode | ErrorCode,
) -> None:
    assert 400 <= status_for(code) <= 599
    assert message_for(code).strip()


def test_a_brain_code_keeps_its_catalog_status() -> None:
    assert status_for(ErrorCode.PROPOSAL_NOT_PENDING) == 409
    assert status_for(ErrorCode.RULES_UNAVAILABLE) == 503

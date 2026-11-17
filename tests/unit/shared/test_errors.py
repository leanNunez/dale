import dataclasses
import inspect
import re

import pytest

import dale.shared.errors as catalog
from dale.shared.errors import (
    ERROR_MESSAGES,
    HTTP_STATUS,
    ErrorCode,
    Failure,
    Ok,
    message_for,
)
from dale.shared.quantity import MAX_LINE_QUANTITY, MIN_LINE_QUANTITY

# Copy and status are pinned: changing either is a deliberate edit of this table.
EXPECTED: dict[str, tuple[int, str]] = {
    "customer_not_found": (
        404,
        "No te encuentro como cliente. Revisá el código de cliente.",
    ),
    "product_not_found": (404, "No encuentro ese producto en el catálogo."),
    "price_not_available": (422, "No tengo precio para ese producto."),
    "invalid_quantity": (422, "La cantidad tiene que ser de 1 a 999 unidades."),
    "below_minimum_amount": (422, "El pedido no llega al mínimo de tu zona. Sumá algo más."),
    "no_delivery_slot": (422, "No tengo un día de entrega disponible para tu zona."),
    "ungrounded_product": (
        422,
        "Ese producto no salió de una búsqueda de esta conversación.",
    ),
    "proposal_not_found": (404, "No encuentro ese pedido. Armemos uno nuevo."),
    "proposal_not_pending": (
        409,
        "Ese pedido ya no se puede confirmar. No se confirmó nada.",
    ),
    "price_changed": (409, "No se confirmó el pedido porque cambió el precio de algún producto."),
    "delivery_date_changed": (409, "No se confirmó el pedido porque cambió el día de entrega."),
    "rules_unavailable": (503, "Ahora no puedo verificar el pedido. Probá de nuevo en un rato."),
    "turn_limit_reached": (422, "Me enredé con tantas vueltas. Probemos de nuevo, de a poco."),
    "model_refusal": (422, "Eso no lo puedo resolver por este medio."),
    "model_unavailable": (503, "Estoy con un problema ahora. Probá de nuevo en un rato."),
    "unknown_tool": (500, "No pude hacer eso. Probemos de otra manera."),
    "invalid_tool_input": (422, "No pude procesar eso. Probemos de otra manera."),
}
PROMISES = ("te paso", "te llamo", "te contacta", "te armo", "te aviso", "te escribo", "confirmé")


def test_catalog_has_the_design_codes_plus_invalid_tool_input() -> None:
    assert len(ErrorCode) == 17


def test_codes_are_unique_snake_case() -> None:
    values = [code.value for code in ErrorCode]
    assert len(set(values)) == len(values)
    assert all(re.fullmatch(r"[a-z]+(_[a-z]+)*", v) for v in values)


@pytest.mark.parametrize("code", list(ErrorCode))
def test_every_code_has_status_and_customer_message(code: ErrorCode) -> None:
    assert 400 <= HTTP_STATUS[code] <= 599
    message = ERROR_MESSAGES[code]
    assert message.strip()
    assert message_for(code) == message
    assert not re.search(r"Traceback|Exception|SQL|\{|_id\b|[Hh]erramienta|[Tt]ool", message)


def test_mappings_cover_exactly_the_enum() -> None:
    assert set(HTTP_STATUS) == set(ErrorCode) == set(ERROR_MESSAGES)


def test_failure_shape_and_result_type() -> None:
    failure = Failure(ErrorCode.INVALID_QUANTITY)
    assert failure.code is ErrorCode.INVALID_QUANTITY
    assert failure.message == message_for(ErrorCode.INVALID_QUANTITY)
    assert [f.name for f in dataclasses.fields(failure)] == ["code"]
    with pytest.raises(dataclasses.FrozenInstanceError):
        failure.code = ErrorCode.UNKNOWN_TOOL  # type: ignore[misc]
    assert Ok(5).value == 5


def test_status_table_is_pinned() -> None:
    assert {c.value: HTTP_STATUS[c] for c in ErrorCode} == {k: v[0] for k, v in EXPECTED.items()}


def test_message_wording_is_pinned() -> None:
    assert {c.value: ERROR_MESSAGES[c] for c in ErrorCode} == {k: v[1] for k, v in EXPECTED.items()}


@pytest.mark.parametrize("code", list(ErrorCode))
def test_no_message_promises_an_action(code: ErrorCode) -> None:
    lowered = message_for(code).lower()
    assert [p for p in PROMISES if p in lowered] == []


def test_invalid_quantity_message_uses_the_shared_bounds() -> None:
    assert f"{MIN_LINE_QUANTITY} a {MAX_LINE_QUANTITY}" in message_for(ErrorCode.INVALID_QUANTITY)
    assert "999" not in inspect.getsource(catalog)  # built from the constants, not a literal

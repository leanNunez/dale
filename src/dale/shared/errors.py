"""One error catalog. Expected outcomes return Failure(code); they never raise."""

from dataclasses import dataclass
from enum import StrEnum

from dale.shared.quantity import MAX_LINE_QUANTITY, MIN_LINE_QUANTITY


class ErrorCode(StrEnum):
    CUSTOMER_NOT_FOUND = "customer_not_found"
    PRODUCT_NOT_FOUND = "product_not_found"
    PRICE_NOT_AVAILABLE = "price_not_available"
    INVALID_QUANTITY = "invalid_quantity"
    BELOW_MINIMUM_AMOUNT = "below_minimum_amount"
    NO_DELIVERY_SLOT = "no_delivery_slot"
    UNGROUNDED_PRODUCT = "ungrounded_product"
    PROPOSAL_NOT_FOUND = "proposal_not_found"
    PROPOSAL_NOT_PENDING = "proposal_not_pending"
    PRICE_CHANGED = "price_changed"
    DELIVERY_DATE_CHANGED = "delivery_date_changed"
    RULES_UNAVAILABLE = "rules_unavailable"
    TURN_LIMIT_REACHED = "turn_limit_reached"
    MODEL_REFUSAL = "model_refusal"
    MODEL_UNAVAILABLE = "model_unavailable"
    UNKNOWN_TOOL = "unknown_tool"
    INVALID_TOOL_INPUT = "invalid_tool_input"


# Kept for the v0.2 HTTP channel (D7); v0.1 does not serve HTTP.
HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.CUSTOMER_NOT_FOUND: 404,
    ErrorCode.PRODUCT_NOT_FOUND: 404,
    ErrorCode.PRICE_NOT_AVAILABLE: 422,
    ErrorCode.INVALID_QUANTITY: 422,
    ErrorCode.BELOW_MINIMUM_AMOUNT: 422,
    ErrorCode.NO_DELIVERY_SLOT: 422,
    ErrorCode.UNGROUNDED_PRODUCT: 422,
    ErrorCode.PROPOSAL_NOT_FOUND: 404,
    ErrorCode.PROPOSAL_NOT_PENDING: 409,
    ErrorCode.PRICE_CHANGED: 409,
    ErrorCode.DELIVERY_DATE_CHANGED: 409,
    ErrorCode.RULES_UNAVAILABLE: 503,
    ErrorCode.TURN_LIMIT_REACHED: 422,
    ErrorCode.MODEL_REFUSAL: 422,
    ErrorCode.MODEL_UNAVAILABLE: 503,
    ErrorCode.UNKNOWN_TOOL: 500,
    ErrorCode.INVALID_TOOL_INPUT: 422,
}

# Rioplatense Spanish, no internal details, no promises: a follow-up by a person
# comes only from a HandoffNotice emitted after the write succeeds.
ERROR_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.CUSTOMER_NOT_FOUND: "No te encuentro como cliente. Revisá el código de cliente.",
    ErrorCode.PRODUCT_NOT_FOUND: "No encuentro ese producto en el catálogo.",
    ErrorCode.PRICE_NOT_AVAILABLE: "No tengo precio para ese producto.",
    ErrorCode.INVALID_QUANTITY: (
        f"La cantidad tiene que ser de {MIN_LINE_QUANTITY} a {MAX_LINE_QUANTITY} unidades."
    ),
    ErrorCode.BELOW_MINIMUM_AMOUNT: "El pedido no llega al mínimo de tu zona. Sumá algo más.",
    ErrorCode.NO_DELIVERY_SLOT: "No tengo un día de entrega disponible para tu zona.",
    ErrorCode.UNGROUNDED_PRODUCT: "Ese producto no salió de una búsqueda de esta conversación.",
    ErrorCode.PROPOSAL_NOT_FOUND: "No encuentro ese pedido. Armemos uno nuevo.",
    ErrorCode.PROPOSAL_NOT_PENDING: ("Ese pedido ya no se puede confirmar. No se confirmó nada."),
    ErrorCode.PRICE_CHANGED: "No se confirmó el pedido porque cambió el precio de algún producto.",
    ErrorCode.DELIVERY_DATE_CHANGED: "No se confirmó el pedido porque cambió el día de entrega.",
    ErrorCode.RULES_UNAVAILABLE: "Ahora no puedo verificar el pedido. Probá de nuevo en un rato.",
    ErrorCode.TURN_LIMIT_REACHED: "Me enredé con tantas vueltas. Probemos de nuevo, de a poco.",
    ErrorCode.MODEL_REFUSAL: "Eso no lo puedo resolver por este medio.",
    ErrorCode.MODEL_UNAVAILABLE: "Estoy con un problema ahora. Probá de nuevo en un rato.",
    ErrorCode.UNKNOWN_TOOL: "No pude hacer eso. Probemos de otra manera.",
    ErrorCode.INVALID_TOOL_INPUT: "No pude procesar eso. Probemos de otra manera.",
}


def message_for(code: ErrorCode) -> str:
    return ERROR_MESSAGES[code]


@dataclass(frozen=True, slots=True)
class Failure:
    code: ErrorCode

    @property
    def message(self) -> str:
        return message_for(self.code)


@dataclass(frozen=True, slots=True)
class Ok[T]:
    value: T


type Result[T] = Ok[T] | Failure

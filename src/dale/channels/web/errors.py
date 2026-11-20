"""Transport error codes of the web channel (D14, W11): disjoint from `shared.errors.ErrorCode`.

A brain outcome keeps its catalog code and status; these codes cover only the host (guard,
validation, lock, unexpected failures) and never appear in a shown event. Messages are fixed
Rioplatense Spanish: no exception text, no internal detail.
"""

from enum import StrEnum

from dale.shared.errors import ERROR_MESSAGES, HTTP_STATUS, ErrorCode


class WebErrorCode(StrEnum):
    INVALID_HOST = "invalid_host"
    FORBIDDEN_ORIGIN = "forbidden_origin"
    UNSUPPORTED_MEDIA_TYPE = "unsupported_media_type"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    INVALID_REQUEST = "invalid_request"
    NOT_FOUND = "not_found"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    CONVERSATION_NOT_FOUND = "conversation_not_found"
    CONVERSATION_BUSY = "conversation_busy"
    TURN_FAILED = "turn_failed"
    CONFIRM_OUTCOME_UNKNOWN = "confirm_outcome_unknown"
    INTERNAL_ERROR = "internal_error"


WEB_STATUS: dict[WebErrorCode, int] = {
    WebErrorCode.INVALID_HOST: 400,
    WebErrorCode.FORBIDDEN_ORIGIN: 403,
    WebErrorCode.UNSUPPORTED_MEDIA_TYPE: 415,
    WebErrorCode.PAYLOAD_TOO_LARGE: 413,
    WebErrorCode.INVALID_REQUEST: 422,
    WebErrorCode.NOT_FOUND: 404,
    WebErrorCode.METHOD_NOT_ALLOWED: 405,
    WebErrorCode.CONVERSATION_NOT_FOUND: 404,
    WebErrorCode.CONVERSATION_BUSY: 409,
    WebErrorCode.TURN_FAILED: 500,
    WebErrorCode.CONFIRM_OUTCOME_UNKNOWN: 503,
    WebErrorCode.INTERNAL_ERROR: 500,
}

WEB_MESSAGES: dict[WebErrorCode, str] = {
    WebErrorCode.INVALID_HOST: "Esa dirección no está permitida.",
    WebErrorCode.FORBIDDEN_ORIGIN: "Ese origen no está permitido.",
    WebErrorCode.UNSUPPORTED_MEDIA_TYPE: "Solo recibo datos en formato JSON.",
    WebErrorCode.PAYLOAD_TOO_LARGE: "El mensaje es demasiado grande.",
    WebErrorCode.INVALID_REQUEST: "No entendí esa solicitud. Revisá los datos y probá de nuevo.",
    WebErrorCode.NOT_FOUND: "No encuentro lo que buscás.",
    WebErrorCode.METHOD_NOT_ALLOWED: "Esa operación no está permitida.",
    WebErrorCode.CONVERSATION_NOT_FOUND: "No encuentro esa conversación. Empezá una nueva.",
    WebErrorCode.CONVERSATION_BUSY: "Todavía estoy con el mensaje anterior. Esperá un momento.",
    WebErrorCode.TURN_FAILED: "Tuve un problema con ese mensaje. Probá de nuevo.",
    WebErrorCode.CONFIRM_OUTCOME_UNKNOWN: "No pude confirmar el resultado. Probá de nuevo.",
    WebErrorCode.INTERNAL_ERROR: "Algo salió mal de nuestro lado. Probá de nuevo en un rato.",
}


def status_for(code: WebErrorCode | ErrorCode) -> int:
    """One place maps a code to its HTTP status: the web table or the shared one."""
    return WEB_STATUS[code] if isinstance(code, WebErrorCode) else HTTP_STATUS[code]


def message_for(code: WebErrorCode | ErrorCode) -> str:
    return WEB_MESSAGES[code] if isinstance(code, WebErrorCode) else ERROR_MESSAGES[code]

"""Why a person should take over (D1, D10, R7). A handoff never applies an exception."""

from enum import StrEnum

MAX_NOTE = 500


class HandoffReason(StrEnum):
    EXCEPTION_REQUEST = "exception_request"
    COMPLAINT = "complaint"
    OUT_OF_SCOPE = "out_of_scope"
    AGENT_REFUSAL = "agent_refusal"  # written by code on a model refusal (D10), never by a tool
    OTHER = "other"


MODEL_REASONS = tuple(r for r in HandoffReason if r is not HandoffReason.AGENT_REFUSAL)

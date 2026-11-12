"""Typed customer input (design §8, B65). A typed "dale" is CustomerText: plain text for the
model. Only the channel's Dale key makes a KeyPress, and only a KeyPress can confirm."""

from dataclasses import dataclass
from enum import StrEnum

from dale.shared.ids import ProposalId


class Key(StrEnum):
    DALE = "dale"
    CANCEL = "cancel"


@dataclass(frozen=True, slots=True)
class CustomerText:
    text: str


@dataclass(frozen=True, slots=True)
class KeyPress:
    key: Key
    proposal_id: ProposalId | None = None  # the pending one, set only from a ProposalSummary

    def __post_init__(self) -> None:
        if (self.key is Key.DALE) != (self.proposal_id is not None):
            raise ValueError("the Dale key carries the pending proposal id; no other key does")


type CustomerInput = CustomerText | KeyPress

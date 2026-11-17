"""Money as non-negative integer cents, bounded to a bigint. No floats, no division."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

MAX_CENTS = 2**63 - 1


@dataclass(frozen=True, order=True, slots=True)
class Money:
    cents: int

    def __post_init__(self) -> None:
        if type(self.cents) is not int:
            raise TypeError("Money takes integer cents (no float, no bool)")
        if not 0 <= self.cents <= MAX_CENTS:
            raise ValueError("Money must be between 0 and 2**63-1 cents")

    def __add__(self, other: Money) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        return Money(self.cents + other.cents)

    def __mul__(self, quantity: int) -> Money:
        if type(quantity) is not int:
            raise TypeError("Money multiplies by an integer quantity only")
        if quantity < 0:
            raise ValueError("Money multiplies by a non-negative quantity only")
        return Money(self.cents * quantity)


def money_sum(amounts: Iterable[Money]) -> Money:
    """Sum of amounts; Money(0) when empty (builtin sum() would return int 0)."""
    total = Money(0)
    for amount in amounts:
        total = total + amount
    return total

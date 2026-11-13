"""Money amounts in text (B96), one parser for both sides: the grader reads model text with it,
and the runner reads the tool results the model was sent with it.

Every tool writes money with `pesos()` ("$ 49.000,00"), so that is the one format a tool result
carries; a bare number in a tool result (a quantity, an id) is never read as money, or "$20"
would pass after a 20-unit line.
"""

import re

# "$ 2.450,00", "$2.450", "$ 2450" and "$ 49.000": thousands with dots, cents after a comma.
AMOUNT = re.compile(r"\$\s*(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{2}))?")


def cents(match: re.Match[str]) -> int:
    return int(match[1].replace(".", "")) * 100 + int(match[2] or 0)


def amounts_in(text: str) -> frozenset[int]:
    """Every amount `text` names, in cents."""
    return frozenset(cents(m) for m in AMOUNT.finditer(text))

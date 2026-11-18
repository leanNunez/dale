"""The verifier's own reading of management's confirmation message (design §9): it must state
the stored amount, weekday and date. Formatted apart from management's code on purpose."""

import re
import unicodedata
from datetime import date

WEEKDAYS = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")


def amount(cents: int) -> str:
    """`$ 49.000,00`: dots between thousands, a comma before two decimals."""
    whole, rest = divmod(cents, 100)
    digits = str(whole)
    first = len(digits) % 3 or 3
    groups = [digits[:first], *(digits[i : i + 3] for i in range(first, len(digits), 3))]
    return f"$ {'.'.join(groups)},{rest:02d}"


def expected_parts(cents: int, day: date) -> tuple[str, str, str]:
    numeric = f"{day.day:02d}/{day.month:02d}/{day.year}"
    return amount(cents), WEEKDAYS[day.isoweekday() - 1], numeric


def _fold(text: str) -> str:
    bare = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in bare if not unicodedata.combining(c))


def states(message: str, cents: int, day: date) -> bool:
    """Whether `message` names all three parts, each as a whole token."""
    text = _fold(message)
    return all(
        re.search(rf"(?<![\w/]){re.escape(_fold(part))}(?![\w/])", text)
        for part in expected_parts(cents, day)
    )

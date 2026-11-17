"""What the terminal prints (design §4, §8; S3.3, R12). Text that came from data or from the
model is printed as plain text: every C-category character (escape sequences, bidi overrides)
is dropped first, and nothing is read as markup. Code writes every other word.

Every line of model text starts with `MODEL_PREFIX`, and no line code writes does (B83). Code
collapses its runs of spaces and wraps it to the terminal's width, so the terminal never wraps
a line of it into one that looks like code's."""

import shutil
import unicodedata
from collections.abc import Callable
from typing import Protocol

from prompt_toolkit import print_formatted_text
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.output import Output
from prompt_toolkit.utils import get_cwidth

from dale.shared.money import pesos
from dale.shared.shown_events import (
    AssistantText,
    HandoffNotice,
    OrderConfirmed,
    OrderRejected,
    ProposalSummary,
    ShownEvent,
    SystemNotice,
)

WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
KEYS_HINT = "F2: confirmar la propuesta. F3: descartarla."
MODEL_PREFIX = "Dale │ "
FALLBACK_COLUMNS, NARROWEST = 80, 20


class Verdict(Protocol):
    """The verifier's verdict as the terminal reads it (the runner's `VerifierVerdict`)."""

    @property
    def verdict(self) -> str: ...
    @property
    def reason(self) -> str: ...
    @property
    def false_confirmations(self) -> int: ...
    @property
    def unexpected_writes(self) -> int: ...


def plain_writer(output: Output | None = None) -> Callable[[str], None]:
    """Prints one plain-text fragment: never parsed as HTML or ANSI markup."""
    return lambda text: print_formatted_text(FormattedText([("", text)]), output=output)


def plain(text: str) -> str:
    """Line breaks stay; every other control, format or unassigned character goes."""
    return "".join(c for c in text if c == "\n" or not unicodedata.category(c).startswith("C"))


def one_line(text: str) -> str:
    return " ".join(plain(text).split())


def render(event: ShownEvent, keys_hint: bool = True, columns: int | None = None) -> str:
    """`keys_hint` goes under a summary; `columns` is the terminal's width when not given."""
    if isinstance(event, AssistantText):
        return model_text(event.text, columns or terminal_columns())
    if isinstance(event, ProposalSummary):
        return _summary(event, keys_hint)
    if isinstance(event, OrderConfirmed | OrderRejected | HandoffNotice | SystemNotice):
        return plain(event.message)
    raise TypeError(f"not a shown event: {type(event).__name__}")


def terminal_columns() -> int:
    return shutil.get_terminal_size((FALLBACK_COLUMNS, 24)).columns


def model_text(text: str, columns: int) -> str:
    room = max(NARROWEST, columns - get_cwidth(MODEL_PREFIX))
    lines = plain(text).split("\n")  # str.split() also takes U+2028 and other spaces
    return "\n".join(MODEL_PREFIX + row for x in lines for row in _wrap(" ".join(x.split()), room))


def _wrap(line: str, room: int) -> list[str]:
    """Fills rows up to `room` terminal cells. A word wider than a row is cut."""
    rows, row = list[str](), ""
    for word in line.split(" ") if line else ():
        joined = f"{row} {word}" if row else word
        if get_cwidth(joined) <= room:
            row = joined
            continue
        if row:
            rows.append(row)
        row = ""
        for char in word:
            if get_cwidth(row + char) > room:
                rows.append(row)
                row = ""
            row += char
    rows.append(row)
    return rows


def _summary(summary: ProposalSummary, keys_hint: bool) -> str:
    """From the stored proposal's data only (S3.3); the names are management's (B61)."""
    day = summary.delivery_date
    lines = [
        f"  {x.quantity} x {one_line(x.name)}: {pesos(x.unit_price)} c/u = {pesos(x.line_total)}"
        for x in summary.lines
    ]
    return "\n".join(
        [
            "Propuesta de pedido (todavía no está confirmada):",
            *lines,
            f"Total: {pesos(summary.total)}. Entrega: {WEEKDAYS[day.weekday()]} {day:%d/%m/%Y}.",
            *([KEYS_HINT] if keys_hint else []),
        ]
    )


def render_verdict(verdict: Verdict, showed_confirmation: bool) -> str:
    """R12: anything short of `verified` is printed as not verified, and a confirmation the
    database does not back is printed as a false confirmation. Never hidden."""
    if verdict.verdict == "verified":
        return "Verificación: VERIFICADO. El pedido está en la base de gestión tal como se mostró."
    if verdict.verdict == "nothing_confirmed" and not showed_confirmation:
        return "Verificación: no hay un pedido confirmado que verificar."
    why = f"{verdict.verdict}: {one_line(verdict.reason)}" if verdict.reason else verdict.verdict
    said = [f"Verificación: NO VERIFICADO ({why})."]
    if verdict.false_confirmations:
        said.append(
            f"CONFIRMACIÓN FALSA: {verdict.false_confirmations} confirmación(es) mostrada(s)"
            " sin un pedido igual en la base de gestión."
        )
    elif showed_confirmation:
        said.append("CONFIRMACIÓN FALSA: se mostró una confirmación que no se pudo verificar.")
    if verdict.unexpected_writes:
        said.append(f"ESCRITURA INESPERADA: {verdict.unexpected_writes} pedido(s) no pedidos.")
    return "\n".join(said)

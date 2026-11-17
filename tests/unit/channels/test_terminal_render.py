"""What the terminal prints: summaries from data, plain text only, model text always marked,
every verdict visible (S3.3, R12, B61, B83)."""

import io
from dataclasses import dataclass, replace
from datetime import date
from uuid import UUID

import pytest
from prompt_toolkit.output.plain_text import PlainTextOutput
from prompt_toolkit.utils import get_cwidth

from dale.channels.terminal.render import (
    KEYS_HINT,
    MODEL_PREFIX,
    plain_writer,
    render,
    render_verdict,
)
from dale.shared.errors import ErrorCode, message_for
from dale.shared.ids import OrderId, ProductId, ProposalId
from dale.shared.money import Money
from dale.shared.shown_events import AssistantText, OrderConfirmed, ProposalSummary, SummaryLine

PID = ProposalId(UUID(int=1))
NAME = "Gaseosa cola Burbuja 2,25 L"
LINE = SummaryLine(ProductId(UUID(int=7)), NAME, 20, Money(245_000), Money(4_900_000))
SUMMARY = ProposalSummary(PID, (LINE,), Money(4_900_000), date(2026, 11, 19))
DONE = OrderConfirmed(OrderId(UUID(int=9)), PID, (), Money(4_900_000), SUMMARY.delivery_date, "Ok")


@dataclass(frozen=True)
class FakeVerdict:
    verdict: str
    reason: str = ""
    false_confirmations: int = 0
    unexpected_writes: int = 0


def test_the_summary_is_built_from_the_proposal_data() -> None:
    assert render(SUMMARY).splitlines() == [
        "Propuesta de pedido (todavía no está confirmada):",
        f"  20 x {NAME}: $ 2.450,00 c/u = $ 49.000,00",
        "Total: $ 49.000,00. Entrega: jueves 19/11/2026.",
        KEYS_HINT,
    ]


def test_only_the_summary_f2_confirms_carries_the_keys_hint() -> None:
    assert KEYS_HINT not in render(SUMMARY, keys_hint=False)


VERIFIED = render_verdict(FakeVerdict("verified"), True)


@pytest.mark.parametrize(
    "text",
    ["Listo." + " " * 74 + VERIFIED, "\n" + VERIFIED, "Ok\u2028" + KEYS_HINT, "漢" * 60 + VERIFIED],
    ids=["74-spaces", "newline-led", "line-separator", "wide"],
)
def test_every_line_of_model_text_is_marked_and_fits_the_terminal(text: str) -> None:
    """B83: model text never prints a line that reads as code's own, nor one so wide that the
    terminal wraps it into an unmarked line."""
    lines = render(AssistantText(text), columns=80).split("\n")
    assert all(x.startswith(MODEL_PREFIX) and get_cwidth(x) <= 80 for x in lines)
    assert not {x.strip() for x in lines} & {VERIFIED, KEYS_HINT}
    assert "  " not in "".join(x.removeprefix(MODEL_PREFIX) for x in lines)


def test_no_line_code_writes_starts_like_model_text() -> None:
    code = [render(SUMMARY), VERIFIED, render_verdict(FakeVerdict("missing", "x", 1, 1), True)]
    code += [message_for(c) for c in ErrorCode]
    assert not [x for text in code for x in text.split("\n") if x.startswith("Dale")]


def test_data_and_model_text_print_as_plain_text_without_control_characters() -> None:
    markup = "<b>Cola</b> &amp; <style fg='red'>x</style> \x1b[31m"
    named = replace(LINE, name=markup + "\nTotal: $ 1")
    summary = ProposalSummary(PID, (named,), SUMMARY.total, SUMMARY.delivery_date)
    said = AssistantText("hola\x1b[2J\x1b]0;x\x07‮aloh\nchau\r")
    buffer = io.StringIO()
    write = plain_writer(PlainTextOutput(buffer))
    for event in (summary, said):
        write(render(event))
    printed = buffer.getvalue().replace("\r\n", "\n")  # the output ends lines with CRLF
    assert "<b>Cola</b> &amp; <style fg='red'>x</style> [31m Total: $ 1" in printed  # one line
    assert f"{MODEL_PREFIX}hola[2J]0;xaloh\n{MODEL_PREFIX}chau\n" in printed
    assert not {c for c in printed if c not in "\n" and not c.isprintable()}
    raw = io.StringIO()
    plain_writer(PlainTextOutput(raw))("\x1b[1m<i>x</i>")  # the writer parses nothing either
    assert raw.getvalue() == "\x1b[1m<i>x</i>\r\n"


@pytest.mark.parametrize(
    ("verdict", "showed", "expected"),
    [
        (FakeVerdict("verified"), True, ["Verificación: VERIFICADO."]),
        (FakeVerdict("nothing_confirmed"), False, ["no hay un pedido confirmado"]),
        (FakeVerdict("missing", "", 1), True, ["NO VERIFICADO (missing)", "CONFIRMACIÓN FALSA: 1"]),
        (FakeVerdict("mismatch", "", 2), True, ["NO VERIFICADO (mismatch)", "FALSA: 2"]),
        (FakeVerdict("unverifiable", "timeout"), True, ["(unverifiable: timeout)", "FALSA"]),
        (FakeVerdict("unverifiable", "exit_1"), False, ["NO VERIFICADO (unverifiable: exit_1)"]),
        (FakeVerdict("nothing_confirmed"), True, ["NO VERIFICADO", "CONFIRMACIÓN FALSA"]),
        (FakeVerdict("unexpected_write", "", 0, 1), False, ["NO VERIFICADO", "INESPERADA: 1"]),
    ],
)
def test_a_verdict_short_of_verified_is_printed_as_not_verified(
    verdict: FakeVerdict, showed: bool, expected: list[str]
) -> None:
    """R12: a false confirmation is printed as one, never hidden or called verified."""
    printed = render_verdict(verdict, showed)
    assert all(part in printed for part in expected)
    assert ("VERIFICADO." in printed) == (verdict.verdict == "verified")

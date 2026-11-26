"""The terminal end to end on the seeded DB with a scripted model (D2, R4, R12; tasks 11.3-11.5):
a request, the summary, F2, management's message and the verifier's verdict."""

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from prompt_toolkit.input import PipeInput, create_pipe_input
from prompt_toolkit.output import DummyOutput
from sqlalchemy import Engine

from dale.apps import terminal
from dale.apps.verifier_runner import Finding, VerifierVerdict, run_verifier
from dale.brain.application.model_port import ModelPort
from dale.channels.common.pending import Pending
from dale.channels.terminal.keys import TerminalInput
from dale.channels.terminal.session import TerminalSession
from dale.erp_sim.infrastructure import tables as erp
from dale.shared.clock import FrozenClock
from dale.shared.customer_input import CustomerInput
from dale.shared.errors import ErrorCode, Failure, Ok
from tests.conftest import role_url
from tests.integration.test_proposals import C001, COLA, NOW
from tests.unit.brain.test_loop import ScriptedModel, calls, says

pytestmark = pytest.mark.integration
F2 = "\x1bOQ"
SCRIPT = (
    calls("search_products", query="cola dos y cuarto"),
    calls("prepare_order", lines=[{"product_id": str(COLA), "quantity": 20}]),
    says("Te armé la propuesta: confirmala con la tecla Dale."),
)
CONFIRMED = (
    "Listo, tu pedido quedó confirmado por $ 49.000,00. Entrega programada: jueves 19/11/2026."
)


def never_built() -> ModelPort:
    raise AssertionError("the model was built before the customer was resolved")


@pytest.mark.parametrize(
    ("company", "customer"), [("el-hornero", "C-999"), ("el-hornero", "C-008"), ("otra", "C-001")]
)
def test_an_unknown_customer_never_reaches_the_model(
    app: Engine, company: str, customer: str
) -> None:
    """D2: unknown, inactive, or of another company: customer_not_found, and no model."""
    found = terminal.compose(app, company, customer, never_built, FrozenClock(NOW))
    assert found == Failure(ErrorCode.CUSTOMER_NOT_FOUND)


def configure(monkeypatch: pytest.MonkeyPatch, log: Path) -> None:
    monkeypatch.setenv(terminal.COMPANY_VARIABLE, "el-hornero")
    monkeypatch.setenv(terminal.URL_VARIABLE, role_url("dale_app"))
    monkeypatch.setenv("DALE_VERIFIER_DATABASE_URL", role_url("dale_verifier"))
    monkeypatch.setenv(terminal.LOG_VARIABLE, str(log))


def test_main_exits_with_customer_not_found(
    app: Engine, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    configure(monkeypatch, tmp_path / "terminal.log")
    monkeypatch.setattr(terminal, "AnthropicModel", never_built)
    assert terminal.main(["--customer", "C-999"]) == 1
    assert capsys.readouterr().err.startswith("customer_not_found: ")


def test_main_needs_the_verifier_database_url(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    configure(monkeypatch, tmp_path / "terminal.log")
    monkeypatch.delenv("DALE_VERIFIER_DATABASE_URL")
    monkeypatch.setattr(terminal, "AnthropicModel", never_built)
    assert terminal.main(["--customer", "C-001"]) == 2
    assert capsys.readouterr().err == "DALE_VERIFIER_DATABASE_URL must be set\n"


@pytest.mark.parametrize("variable", [True, False], ids=["DALE_TERMINAL_LOG", "default"])
def test_a_warning_goes_to_the_log_file_and_never_to_the_chat(
    tmp_path: Path, variable: bool
) -> None:
    """A fresh process: with no handler, Python would print the warning on stderr."""
    log = tmp_path / "logs" / "terminal.log"
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path)}
    if variable:
        env[terminal.LOG_VARIABLE] = str(log)
    else:
        log = tmp_path / ".local/state/dale/terminal.log"
    code = "import logging, dale.apps.terminal as t; t.log_to_file(); logging.warning('boom')"
    done = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, check=True)
    assert done.stderr == b"" and log.read_text().endswith("WARNING root: boom\n")


def chat(
    db: Engine, verifier: Callable[[str], VerifierVerdict], *keys: str
) -> tuple[list[str], terminal.TerminalBackend]:
    """The composed terminal, fed one chunk of keys per read through the pipe input."""
    composed = terminal.compose(
        db,
        "el-hornero",
        "C-001",
        lambda: ScriptedModel(*SCRIPT),
        FrozenClock(NOW),
        verifier=verifier,
    )
    assert isinstance(composed, Ok)
    printed, chunks, pending = list[str](), list(keys), Pending()
    with create_pipe_input() as pipe:
        typed = TerminalInput(pending, pipe, DummyOutput())

        def read(pipe: PipeInput = pipe) -> CustomerInput:
            if not chunks:
                raise EOFError
            pipe.send_text(chunks.pop(0))
            return typed.read()

        TerminalSession(composed.value, read, printed.append, pending).run()
    return printed, composed.value


def test_a_request_the_summary_and_f2_end_in_a_verified_order(db: Engine) -> None:
    """11.5, S4.1: the real verifier process judges the run as the read-only role."""
    printed, backend = chat(
        db,
        lambda r: run_verifier(r, role_url("dale_verifier")),
        "quiero 20 colas de dos y cuarto\r",
        F2,
    )
    summary = next(p for p in printed if p.startswith("Propuesta de pedido"))
    assert "  20 x Gaseosa cola Burbuja 2,25 L: $ 2.450,00 c/u = $ 49.000,00" in summary
    assert printed[-2:] == [
        CONFIRMED,
        "Verificación: VERIFICADO. El pedido está en la base de gestión tal como se mostró.",
    ]
    with db.connect() as conn:
        orders = conn.execute(sa.select(erp.sales_order.c.customer_id)).scalars().all()
    assert orders == [C001] and backend.session.customer_id == C001


def test_a_missing_verdict_is_printed_as_a_false_confirmation(db: Engine) -> None:
    """11.4, R12: whatever the runner says short of verified is printed, never hidden."""
    seen: list[dict[str, Any]] = []

    def missing(request: str) -> VerifierVerdict:
        seen.append(json.loads(request))
        lost = Finding(kind="missing", proposal_id=UUID(int=1), order_id=None, fields=())
        return VerifierVerdict(
            verdict="missing",
            reason="",
            findings=(lost,),
            false_confirmations=1,
            unexpected_writes=0,
            stored_orders=(),
        )

    printed, backend = chat(db, missing, "quiero 20 colas\r", F2)
    assert printed[-2] == CONFIRMED
    assert printed[-1].splitlines()[0] == "Verificación: NO VERIFICADO (missing)."
    assert "CONFIRMACIÓN FALSA: 1" in printed[-1]
    [request] = seen  # the whole run, for the session's own conversation
    assert request["session"]["conversation_id"] == str(backend.session.conversation_id)
    assert [e["type"] for e in request["shown"]] == [
        "ProposalSummary",
        "AssistantText",
        "OrderConfirmed",
    ]

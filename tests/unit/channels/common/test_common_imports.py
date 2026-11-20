"""The shared channel logic lives in `dale.channels.common` and nowhere else (D11, S18.3)."""

import importlib

import pytest

from dale.channels.common.backend import Backend, Verdict, VerifierFailed, step
from dale.channels.common.pending import Pending
from dale.channels.terminal import render, session


def test_terminal_uses_the_shared_objects_not_copies() -> None:
    assert vars(render)["Verdict"] is Verdict
    assert vars(session)["Backend"] is Backend
    assert vars(session)["VerifierFailed"] is VerifierFailed
    assert vars(session)["step"] is step


def test_terminal_has_no_pending_module_of_its_own() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("dale.channels.terminal.pending")
    assert Pending().proposal_id is None


def test_step_returns_the_result_or_none_for_an_error_or_an_interrupt() -> None:
    def fail(error: BaseException) -> int:
        raise error

    assert step("ok", lambda: 3) == 3
    assert step("error", lambda: fail(RuntimeError("x"))) is None
    assert step("interrupt", lambda: fail(KeyboardInterrupt())) is None

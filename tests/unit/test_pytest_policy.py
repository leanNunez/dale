"""The network policy lives in pyproject: sockets are off except for the local database."""

import socket
import tomllib
from pathlib import Path

import pytest
from pytest_socket import SocketConnectBlockedError

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_policy_is_configured_in_addopts() -> None:
    addopts = tomllib.loads(PYPROJECT.read_text())["tool"]["pytest"]["ini_options"]["addopts"]
    assert {"--disable-socket", "--allow-hosts=127.0.0.1,localhost"} <= set(addopts.split())


@pytest.mark.filterwarnings("ignore:A test tried to use socket")
def test_policy_is_enforced() -> None:
    with pytest.raises(SocketConnectBlockedError):
        socket.create_connection(("192.0.2.1", 80), timeout=1)

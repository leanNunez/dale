"""Smoke test: every top-level package of the tree imports cleanly."""

import importlib

import pytest

PACKAGES = [
    "dale",
    "dale.shared",
    "dale.erp_sim",
    "dale.erp_sim.public",
    "dale.brain",
    "dale.verifier",
    "dale.channels",
    "dale.channels.common",
    "dale.channels.terminal",
    "dale.apps",
]


@pytest.mark.parametrize("name", PACKAGES)
def test_package_imports(name: str) -> None:
    assert importlib.import_module(name) is not None

"""No code under src/ may hand the Anthropic client any argument: the environment holds it."""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
CLIENTS = {"Anthropic", "AsyncAnthropic"}


def client_calls_with_arguments(source: str) -> list[int]:
    """Lines of SDK client calls that pass any positional or keyword argument."""
    tree = ast.parse(source)
    aliases = {
        (alias.asname or alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "anthropic"
        for alias in node.names
        if alias.name in CLIENTS
    }
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and (node.args or node.keywords):
            func = node.func
            if (isinstance(func, ast.Name) and func.id in aliases) or (
                isinstance(func, ast.Attribute) and func.attr in CLIENTS
            ):
                lines.append(node.lineno)
    return lines


@pytest.mark.parametrize(
    "source",
    [
        "import anthropic\nanthropic.Anthropic(max_retries=2)\n",
        "from anthropic import Anthropic\nAnthropic(k)\n",
        "from anthropic import AsyncAnthropic as C\nC(timeout=3)\n",
    ],
)
def test_detects_client_calls_with_arguments(source: str) -> None:
    assert client_calls_with_arguments(source) == [2]


def test_allows_the_argument_free_client() -> None:
    source = (
        "import anthropic\nanthropic.Anthropic()\nfrom anthropic import Anthropic\nAnthropic()\n"
    )
    assert client_calls_with_arguments(source) == []


def test_no_client_in_src_is_built_with_arguments() -> None:
    offenders = {
        f"{path.relative_to(SRC)}:{line}"
        for path in SRC.rglob("*.py")
        for line in client_calls_with_arguments(path.read_text())
    }
    assert offenders == set()

"""The session database fixture: a build that fails is never taken for a database (B87)."""

from collections.abc import Iterator
from contextlib import contextmanager

import pytest

import tests.conftest as database


def test_a_failed_build_leaves_the_session_without_a_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @contextmanager
    def server_down() -> Iterator[None]:
        raise RuntimeError("server down")
        yield

    monkeypatch.setattr(database, "fresh_database", server_down)
    monkeypatch.setattr(database, "_built", False)
    with pytest.raises(RuntimeError, match="server down"):
        next(database.shared_database())
    assert database._built is False  # the next copy builds again instead of sharing nothing

"""Integration fixtures shared by the erp_sim read tests."""

from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine

from dale.erp_sim.infrastructure import tables as erp
from dale.erp_sim.infrastructure.seed import reseed


@pytest.fixture(scope="module")
def app(engines: dict[str, Engine]) -> Iterator[Engine]:
    """The app-role engine with El Hornero seeded; every erp row (any company a test adds too)
    is removed afterwards, because other modules (test_constraints) reuse the same slug."""
    reseed(engines["dale_app"])
    yield engines["dale_app"]
    with engines["dale_app"].begin() as conn:
        for table in reversed(erp.METADATA.sorted_tables):  # children first
            conn.execute(sa.delete(table))

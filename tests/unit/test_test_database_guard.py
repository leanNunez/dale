"""The database fixtures refuse any server not on this machine: pytest-socket misses libpq."""

import pytest

from tests.conftest import admin_url, role_url

URL = "postgresql+psycopg://postgres@{}/postgres"


@pytest.fixture(autouse=True)
def _no_libpq_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("PGHOSTADDR", "PGSERVICE"):
        monkeypatch.delenv(var, raising=False)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1:55435", "[::1]:5432"])
def test_local_servers_are_accepted(monkeypatch: pytest.MonkeyPatch, host: str) -> None:
    monkeypatch.setenv("DALE_TEST_ADMIN_URL", URL.format(host))
    assert admin_url().host in ("localhost", "127.0.0.1", "::1")
    assert role_url("dale_app").startswith("postgresql+psycopg://dale_app@")


@pytest.mark.parametrize(
    "url",
    [
        URL.format("db.example.com"),
        URL.format("10.0.0.5:5432"),
        URL.format("127.0.0.2"),
        URL.format(""),  # no host: libpq would fall back to PGHOST
        URL.format("localhost") + "?host=10.0.0.5",
        URL.format("localhost") + "?hostaddr=10.0.0.5",
        URL.format("localhost") + "?service=prod",
    ],
)
def test_other_servers_are_refused(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.setenv("DALE_TEST_ADMIN_URL", url)
    for build in (admin_url, lambda: role_url("dale_owner")):
        with pytest.raises(RuntimeError, match="only against a local server"):
            build()


@pytest.mark.parametrize("var", ["PGHOSTADDR", "PGSERVICE"])
def test_libpq_redirects_in_the_environment_are_refused(
    monkeypatch: pytest.MonkeyPatch, var: str
) -> None:
    monkeypatch.setenv("DALE_TEST_ADMIN_URL", URL.format("127.0.0.1"))
    monkeypatch.setenv(var, "10.0.0.5")
    with pytest.raises(RuntimeError, match=var):
        admin_url()

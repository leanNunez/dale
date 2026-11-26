"""`GET /health` on the real database probe (D25): 200 when `SELECT 1` runs as the app role, 503
`rules_unavailable` when the database cannot be reached (fail closed); and the start-up check of
the configured customer on the seeded database (D2)."""

import pytest
import uvicorn
from sqlalchemy import Engine
from starlette.testclient import TestClient

from dale.apps import web
from dale.channels.web.app import create_app
from dale.channels.web.guard import AllowList
from tests.conftest import role_url
from tests.unit.test_web_app import FakeServer

pytestmark = pytest.mark.integration


def health(engine: Engine) -> tuple[int, str | None]:
    app = create_app(AllowList.loopback(8000), web.database_ready(engine), None)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        response = client.get("/health")
    error = response.json()["error"]
    return response.status_code, error and error["code"]


def test_health_is_ok_when_the_app_role_can_read(engines: dict[str, Engine]) -> None:
    assert health(engines["dale_app"]) == (200, None)


def test_health_is_unavailable_when_the_database_is_down() -> None:
    down = web.database_engine("postgresql+psycopg://dale_app@127.0.0.1:1/dale_test")
    try:
        assert health(down) == (503, "rules_unavailable")
    finally:
        down.dispose()


@pytest.mark.parametrize(
    ("company", "customer", "code"),
    [("nonexistent", "C-001", 2), ("el-hornero", "C-999", 2), ("el-hornero", "C-001", 0)],
)
def test_the_host_starts_only_for_a_seeded_customer(
    app: Engine, monkeypatch: pytest.MonkeyPatch, company: str, customer: str, code: int
) -> None:
    env = {"DALE_WEB_COMPANY": company, "DALE_WEB_CUSTOMER": customer}
    for name, value in {**env, "DALE_APP_DATABASE_URL": role_url("dale_app")}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(uvicorn, "Server", FakeServer)
    FakeServer.started.clear()
    assert web.main([]) == code and len(FakeServer.started) == (code == 0)

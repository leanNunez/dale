# 0001. Pinned versions

Date: 2026-11-12
Status: accepted

## Context

Plan section 4.6 requires exact versions for the whole stack from the first
commit. Versions below are the ones `uv` resolved on the date above and are
locked in `uv.lock`; `pyproject.toml` pins them with `==`.

## Decision

| Component | Version |
|---|---|
| Python | 3.13.15 (`requires-python = "==3.13.*"`) |
| uv | resolver and installer; lockfile is `uv.lock` |
| hatchling (build backend) | 1.33.0 |
| anthropic | 2.8.0 |
| sqlalchemy | 2.1.8 |
| alembic | 1.20.1 |
| psycopg[binary] | 3.3.9 |
| pydantic | 2.14.3 |
| fastapi (added 2026-11-19, v0.2) | 0.165.0 |
| starlette (imported directly by the web channel; added 2026-11-19, v0.2) | 1.10.0 |
| uvicorn, no extras (added 2026-11-19, v0.2) | 0.54.0 |
| pyyaml | 6.0.3 |
| prompt-toolkit | 3.0.53 |
| pytest | 9.2.0 |
| pytest-socket | 0.8.1 |
| hypothesis | 6.170.15 |
| ruff | 0.17.4 |
| mypy | 2.4.1 |
| import-linter | 2.16 |
| httpx2 (dev, the transport of Starlette's `TestClient`, which imports `httpx2` first; added 2026-11-19, v0.2) | 2.16.0 |
| types-pyyaml (typing stubs) | 6.0.12.20261111 |
| PostgreSQL service image | `postgres:17` (major tag; CI and local) |

## Notes

- Import-linter contract 3 is split into 3a and 3b, and contract 7 into 7a and
  7b, because the tool expresses each as a separate forbidden contract.
- Anthropic effort field (checked 2026-11-12 against the installed `anthropic` 2.8.0):
  `messages.create(output_config={"effort": "medium"})`. `OutputConfigParam.effort` takes
  `low`, `medium`, `high`, `xhigh` or `max`; there is no top-level `effort` argument. A unit
  test pins the field, so an SDK upgrade that moves it fails CI.

- v0.2 adds `fastapi`, `uvicorn` and dev `httpx` (design D12, D22). They are the current stable
  releases on 2026-11-19 and resolve with the existing pins unchanged. `uvicorn` is pinned
  without extras, so no `uvloop` or `httptools`. `uv.lock` pins their transitive packages
  (for example `starlette` 1.10.0); `uv sync --locked` fails on any drift.

## Consequences

Upgrading any pin is a deliberate change with its own commit, and re-runs the
full CI.

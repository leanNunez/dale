# 0004. Web host, transport and channel boundary

Date: 2026-11-19
Status: accepted

## Context

v0.2 adds a local web channel next to the terminal, over the same brain and verifier. The host
runs blocking code: SQLAlchemy, the Anthropic SDK and the verifier subprocess. The brain's
`TakeTurn` keeps its history in memory and is not thread-safe. This record fixes the channel
boundary, the host shape, the transport and the limits that follow. Design decisions D11 to D13,
D16, D17 and D25 are summarized here; the confirmation safety rules are in record 0005.

## Decision

| Topic | Decision |
|---|---|
| Channel boundary (D11) | `Backend`, the `Verdict` protocol, `VerifierFailed`, `step` and `Pending` live in `dale.channels.common`. Terminal and web import them from there and never from each other. The move is verbatim except the failure log line of `step`, which now reads "channel step %s failed" and is logged by `dale.channels.common.backend`, because both channels use it: the terminal texts and `TerminalSession` stay, and the terminal tests change only their imports |
| Import rules (D11) | Import-linter contracts 9 to 12: the HTTP stack (`fastapi`, `starlette`, `uvicorn` and their submodules) is imported only by `dale.channels.web` and `dale.apps.web`, and never by `evals`; terminal and web are independent and `common` imports neither; a channel imports neither `dale.apps` nor `dale.verifier`; `prompt_toolkit` is imported only by `dale.channels.terminal` |
| Host shape (D12) | FastAPI with synchronous `def` routes in the threadpool, one uvicorn worker, bound to `127.0.0.1` with no option to change it. `/docs`, `/redoc` and `/openapi.json` are disabled so the route table stays exact |
| Transport (D13) | Request/response JSON. Each event carries `v`, `seq`, `conversation_id`, `type` and `data`, so the same objects can be streamed over SSE later without a new contract |
| Per-conversation lock (D16) | A non-blocking `threading.Lock` per conversation: a second request while a turn runs gets 409 `conversation_busy`. The lock is released in `finally`. Conversations do not block each other |
| Request timeouts (D17) | No server request timeout and no client abort: a sync turn cannot be cancelled in Python. A turn has no fixed upper bound. Without `retry-after` it can take about 18.5 minutes (6 model calls x 3 attempts x 60 s, plus the 30 s verifier), but the `anthropic` SDK waits as long as a `retry-after` header asks (`anthropic/_base_client.py`, `_calculate_retry_timeout`). So the stack configures no request timeout at all (uvicorn's `timeout_keep_alive` only limits idle connections; the Vite dev proxy gets no `proxyTimeout`), and a test pins that. Whether browsers abort a long `fetch` is unverified. A turn deadline inside the brain is pending and is required before a public demo |
| Readiness (D25) | `GET /health` runs `SELECT 1` on the app engine and answers 200, or 503 `rules_unavailable` when the database cannot be read (fail closed). There is no separate `/ready` |

## Alternatives rejected

- Web importing from `channels.terminal` couples the channels; duplicating the shared logic lets
  the two `Pending` rules drift.
- `async` routes only wrap the same blocking calls; plain Starlette loses request validation.
- Queuing requests per conversation hides overlap and lets one slow turn back up the page.
- A 120 s client abort leaves the turn running on the server with no way to read its events.

## Consequences

- One uvicorn worker is required, because conversation state is in memory and is lost on restart.
- A turn deadline inside the brain is not part of v0.2 (Known pending).
- Reverting a web slice leaves the terminal working: it depends only on `channels.common`.

# Design: Dale v0.3 "Probalo vos"

v0.3 turns the v0.2 loopback host into a public demo that is safe to link from a CV. It adds a demo mode, a turn deadline, visitor customers, limits, a spend cap, a kill switch, transcripts, a nightly reset, packaging and a release gate. The brain changes only for the deadline. Sources: `proposal.md`, `decision-log.md` (D1-D19 binding, D14 pending), `exploration.md`, the delta specs (`web-channel` W5/W8/W11/W14/W17/W19, `verified-order` R9, `demo-operations` O1-O11, `release-gate` G1-G9), and the v0.2 design (D11-D25, still in force). Facts below were re-read in the code at `f4dfa20`.

**Numbering.** Design decisions use the prefix `DD` and continue the design series (v0.1 D1-D10, v0.2 D11-D25), so they start at DD26. The decision log's `D1`-`D19` are cited as "log D4" and so on, so neither series is mistaken for the other.

**Size note.** This artifact is larger than the skill's 800-word budget. It follows the project's own convention (the v0.2 design) because the caller asked for every area below.

## 1. Decisions

| # | Decision | Options considered (tradeoff) | Choice and rationale |
|---|---|---|---|
| DD26 | Where demo code lives | **a)** A new `dale.apps.demo` package (SQL, CLI, reset, prices, settings), a new sibling module `dale.apps.web_demo` (demo wiring for the web host), and small channel pieces in `dale.channels.web`. `src/dale/apps/web.py` stays a module and gains only a mode switch. **b)** Turn `apps/web.py` into a package: `check_pr_size.py:74` diffs with `--no-renames`, so the move alone counts about 500 lines. **c)** A new top-level hexagon `dale.demo` (more layers for code that is composition and SQL) | **a.** Matches the proposal ("demo controls live in `dale.apps` and `dale.channels.web`"). Every in-memory piece (caps, TTL, cookie, client IP) stays in the channel, and every persistent piece stays in `apps.demo`. `apps.web_demo` adapts one to the other, because the channel never imports `apps` (contract 11). Contract 9 already forbids `apps.web_demo` from importing FastAPI, Starlette or uvicorn, since only `dale.apps.web` and `dale.apps.web.**` are exempt, and it needs none of them |
| DD27 | Spend accounting per attempt (log D19) | **a)** An `AttemptGate` port in `brain.application.model_port`, called by the adapter around each attempt. **b)** A `BudgetedModel` wrapper around `ModelPort` (the proposal's sketch). It sees one call per turn step, not the adapter's retries, so it cannot count every attempt (log D15) | **a.** The adapter stays the only owner of the retry loop. The gate reads the control state and reserves the worst case before each attempt, then settles after it. `None` means no accounting (local mode, evals), so `RecordingModel` and the replay code are untouched |
| DD28 | Deadline transport | **a)** `ModelRequest.deadline: Deadline \| None`, declared `compare=False, repr=False`, default `None`. **b)** A new `complete(request, deadline)` signature (every fake, `ReplayModel` and `RecordingModel` would change). **c)** A thread-local (hidden) | **a.** `request_params`, `fingerprint` and `messages_digest` never read it (`anthropic_model.py:22-32`, `evals/harness/model.py:127-153`). Existing constructors and equality checks keep working |
| DD29 | Retry loop | **a)** SDK `max_retries=0` and our own loop: at most 3 attempts. Each attempt's timeout is `min(60, time left)`. Retry on 408/409/429/5xx and on connection or timeout errors, and follow `x-should-retry` the way the SDK does. Wait for `retry-after-ms` or `retry-after` when present, else 0.5, 1 s, but only when the wait fits in the time left. An attempt needs at least 1 s left (log D18). `sleep` and `monotonic` are injected. **b)** Keep the SDK retries (it honors any `retry-after`, so the wait is unbounded: B6) | **a.** It is deterministic with a fake clock. With no deadline (`None`), a `retry-after` wait is capped at 30 s, so even an unconfigured caller is bounded |
| DD30 | Statement timeout | **a)** Engine options `-c statement_timeout=5000 -c lock_timeout=3000 -c idle_in_transaction_session_timeout=10000`, plus the existing `connect_timeout=3` (`web.py:202`), in one shared `app_engine(url)` in `apps.compose`. The web host and the terminal both use it (`terminal.py:63` calls `sa.create_engine(url)` today). **b)** `ALTER ROLE dale_app SET ...` in `db/roles.sql` | **a.** Production also runs `db/roles.sql` (through `deploy/db/init.sh`, §9), so a role setting would reach it too. Still, a role setting would also bind the CLI and `reseed`, and would not exist on a database whose roles were created another way. The engine options travel with the code and are checked by an integration test (`SHOW statement_timeout`). The `roles.sql` header is updated: no passwords in the file; dev and CI trust local connections; production's `init.sh` sets passwords from a root-only file |
| DD31 | Visitor customer port | **a)** A separate `VisitorCustomers` protocol in `erp_sim.public`, implemented by `SqlVisitorCustomers`. **b)** Add the method to `ErpFacade` (the brain's `Tools` would gain a write path it must never have) | **a.** Least privilege: only `apps.web_demo` holds it. The code is `V-` plus 10 random hex digits, retried once on a unique conflict. The visitor copies the template's zone and name and gets a random UUID. `reseed` removes it (its deletes are scoped by company, `seed/__init__.py:22-24`) |
| DD32 | Reset location | **a)** In process: a scheduler thread in the web host pauses (reason `reset`), drains through the registry's in-flight counter, ends every conversation (leaving tombstones that answer `demo_reset`), reseeds and resumes. **b)** A host timer that restarts the container (no `demo_reset` code, and `status` cannot see the drain). **c)** An external CLI (it cannot see in-memory in-flight work) | **a.** It is the only option that meets O11 literally (`demo_reset` until restart). A reset missed at 04:00 runs at the first tick after start, when there are no conversations. The `reset` CLI command only sets `reset_requested_at`, which the scheduler polls |
| DD33 | Control row and reasons | One row (`id = 1`) with `paused`, `reason ∈ {initial, operator, reset, deploy}` and the last reset result. The migration seeds it as `paused, initial`. Pausing for a reset or a deploy is conditional (`WHERE NOT paused`). The matching resume runs only `WHERE reason = <own>` | A fresh database starts paused. A reset or deploy never resumes an operator's pause (S11.5). A failed drain or reseed leaves the row paused (log D15) |
| DD34 | Session (log D18) | **a)** Cookie `__Host-dale_session`: 32 random bytes in base64url, `HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=86400`. Any response to a request without a well-formed cookie sets a new one. The stored subject is HMAC-SHA256(secret, `"session\|" + token`). There is no session table. **b)** A signed stateless token (adds nothing: clearing the cookie gets a new one anyway). **c)** A session table (stores more than O2 needs) | **a.** Notice acceptance travels in the create command (O7) and is stored with the transcript, so nothing else needs a session row |
| DD35 | CSRF (amends ADR 0005) | SameSite=Strict, plus the guard's existing *required* allow-listed `Origin` on every non-GET request (`guard.py:104-108`), plus JSON only (a cross-site JSON POST needs a preflight, and the host sends no CORS headers). No GET changes state | No token: every cross-site path is closed by at least two independent checks. ADR 0010 records it |
| DD36 | Client IP | **a)** A pure function in the channel. Only when the peer is `127.0.0.1` or `::1`, take the **last** element of the last `X-Forwarded-For` field (the one Caddy appended). Validate it with `ipaddress`. Any other peer: use the peer and ignore the header. In demo mode, a loopback peer with no usable value gets `invalid_request` before any handler runs. uvicorn keeps `proxy_headers=False`. **b)** uvicorn's `ProxyHeadersMiddleware` (its algorithm depends on the version, and it rewrites `scope["client"]` for every route) | **a.** Explicit and testable (S8.5-S8.7), and the `server_config` pin is unchanged. Local mode never reads the header (S8.10) |
| DD37 | Limits store | **a)** Conditional counters in `demo.counter(day, kind, subject)`: `INSERT ... ON CONFLICT DO UPDATE ... WHERE count < :limit RETURNING`. No row returned means `rate_limited`. A create's two counters (session and IP) run in **one transaction**: if either refuses, the transaction rolls back, so neither slot is consumed. The IP subject is HMAC(HMAC(secret, `"ip\|" + day`), ip), so the key rotates every day. In-memory caps (live conversations, concurrent turns, turns per conversation, TTL) stay in the registry. **b)** Everything in memory (O3 allows it, but the IP daily limit would reset on every deploy) | **a.** Counting runs last (§4 step 8), so a busy or invalid request never consumes a turn (O3). A store error is `demo_paused` (fail closed) |
| DD38 | Spend ledger arithmetic | Integer micro-USD. Per-attempt reservation: `ceil(prompt_bound × max(input, cache_write_5m) + max_tokens × output)` at the tier the bound selects, where `prompt_bound` is the UTF-8 byte count of canonical JSON(system, tools, messages) plus 2,000 framing tokens. Atomic reserve on `demo.spend_day`. Settle the actual cost from usage (`evals/harness/pricing.py:80-88` formula), or at the reservation when usage is unknown (O4, log D15). A crash between reserve and settle keeps the reservation. **Reference request** (§4 step 6): the system blocks, the tool schemas and one 2,000-character customer message, with `max_tokens` of output, which is the smallest request a turn can make | A token encodes at least one byte, so bytes bound input tokens (an assumption, checked empirically in §10). Reserving at the higher of the input and cache-write prices covers every cache split. The reference request answers `demo_paused` only when no turn could even start |
| DD39 | Runtime price table | `dale.apps.demo.prices.PRICES`: Decimal values per model, with `threshold` and `retrieved`. A unit test loads `evals/pricing.toml` through `evals.harness.pricing.load_pricing` and asserts equal tiers, threshold and `retrieved` for every model, and the same model set. The release check repeats the comparison (G4 S4.6) | `dale` never imports `evals` (contracts unchanged). Tests and scripts may import both |
| DD40 | Transcripts | Write-through rows in `demo.transcript` (one per conversation) and `demo.transcript_event` (seq, kind, jsonb body). The bodies are the WebEvent JSON already sent, plus `customer_text`, `usage` (per call, with cost) and `error`. A write failure is logged, counted in memory, published by the heartbeat, and never changes the reply (O9) | One serializer for page and transcript. Usage comes from `TurnResult.usage`, which `ComposedBackend` already returns (`web.py:168-170`) |
| DD41 | Privacy page | `apps/web/public/privacidad/index.html` (static, with `{{contact}}` and `{{retention_days}}` placeholders and its own CSS file). A **new** `PageFiles(StaticFiles)` subclass in `channels/web/page.py` serves it pre-rendered at `/privacidad` and `/privacidad/`, with the contact HTML-escaped and no redirect. `build_api` mounts `PageFiles` instead of plain `StaticFiles` (`app.py:92`) | It is page content, not an API route (W2 unchanged). The contact comes from settings (O8). No JS and no inline style, so the CSP holds |
| DD42 | Demo discovery by the page | `GET /v1/contract` gains an additive `demo: {notice_version, retention_days} \| null`. A generated `contracts/v1/notice.json` holds the notice version that the page's banner text belongs to. It joins `EXCLUDED_FILES` in `check_pr_size.py:27`, with a test, as `components.json` did | The page shows the banner and the accept step only in demo mode (W19). A Python test pins equality of the generated file and the constant |
| DD43 | Registry port | `channels/web/conversations.py` changes. The `ConversationRegistry` port becomes `create(visitor: Visitor \| None = None) -> WebConversation \| Code` and `using(conversation_id, visitor: Visitor \| None = None)`, a context manager that yields `WebConversation \| Code`. `InMemoryRegistry` ignores `visitor` (always `None` in local mode). Its `using` is `get()` plus `conversation_not_found`, and its retire-on-create rule (B65) is unchanged. A new `DemoRegistry` in `channels/web/registry.py` implements caps, TTL, ownership, in-flight counting and tombstones | The default `None` arguments keep every v0.2 test call valid (S17.6). The port change, `InMemoryRegistry` and the `routes.py` callers land in one slice, so the `types` job never sees a half change |
| DD44 | Packaging | A multi-stage image (page build on Node 24.22.2, then `uv sync --locked --no-dev`, then a slim Python 3.13 runtime as non-root, all pinned by digest). Compose runs the app on `network_mode: host` and Postgres on a bridge published only on `127.0.0.1:5432`. Caddy runs on the host | Keeps W1 and ADR 0005's loopback bind. Postgres never listens on a public interface |
| DD45 | Release and deploy | `ci.yml` gains `workflow_call`. `release.yml` runs on tags: on-main check, then CI, then `scripts/check_release.py`, then image build, scan and push, then a GitHub Release whose body records the digest. The owner's `deploy/deploy.sh` reads that digest with `gh` and runs one fixed server command over the owner's own SSH | No key and no SSH credential in CI (log D1-D3, G7). Pulling by digest makes the image immutable (G8 S8.5) |
| DD46 | Additive migrations | Revisions from 0006 on may only add. A unit test rejects `DROP`, `RENAME`, `ALTER ... TYPE` and `SET NOT NULL` in their DDL | The previous image keeps working against the new schema (G8, log D15), so a rollback never needs a downgrade |

## 2. Module layout and import contracts

```
src/dale/brain/application/deadline.py      (new) Deadline(at, monotonic): remaining(), expired()
src/dale/brain/application/model_port.py    + ModelRequest.deadline, DeadlineExceededError, AttemptGate, AttemptTicket
src/dale/brain/application/take_turn.py     + turn_seconds, monotonic; check before each call; TURN_DEADLINE_EXCEEDED
src/dale/brain/infrastructure/anthropic_model.py   max_retries=0, own loop, optional gate, injected sleep
src/dale/shared/errors.py                   + TURN_DEADLINE_EXCEEDED (status 504, log D18; message)
src/dale/erp_sim/public.py                  + VisitorCustomers protocol
src/dale/erp_sim/application/visitors.py    (new) create_visitor(slug, template, data, ids)
src/dale/erp_sim/infrastructure/{facade.py, repositories.py}   + SqlVisitorCustomers, the insert
src/dale/channels/web/{client.py, session.py, demo.py, registry.py, page.py}   (new)
src/dale/channels/web/{conversations.py, errors.py, contract.py, routes.py, app.py, guard.py, schema_gen.py}  (modified)
src/dale/apps/compose.py                    + app_engine(), turn_deadline(env), turn_seconds passed to TakeTurn
src/dale/apps/web.py                        (stays a module) + DALE_WEB_MODE, DALE_WEB_PAGE_DIR, app_engine, demo hand-off
src/dale/apps/web_demo.py                   (new) visitor backends, policy and transcript adapters, scheduler start
src/dale/apps/demo/{__init__, settings, prices, tables, control, ledger, counters, transcripts, reset, status, cli, __main__}.py  (new)
migrations/versions/0006_demo_schema.py; migrations/env.py (+ demo metadata and schema); db/roles.sql (header only)
```

There are 15 contracts today. Contract 4 changes and the other 14 stay as they are. Two new contracts make 17 in total. All three changes land in slice 4, which also creates the `dale.apps.demo` package (import-linter fails on a module that does not exist).

| # | Contract change |
|---|---|
| 4 | `forbidden_modules` gains `dale.apps.demo`: the verifier stays independent of demo code |
| 13 (new) | `forbidden`: `dale.apps.demo` → `dale.channels`, `dale.apps.web`, `dale.apps.web_demo`. The CLI and the reset never load the web stack; channel codes are mapped in `apps.web_demo` |
| 14 (new) | `forbidden`: `dale.brain`, `dale.erp_sim` → `dale.apps` (no contract forbids it today). The gate and the deadline enter the brain only through its own ports |

## 3. Turn deadline (R9)

- `TakeTurn(..., turn_seconds: float | None, monotonic=time.monotonic)`. Each `__call__` builds `Deadline.after(turn_seconds)` and puts it in every `ModelRequest`. Before each model call, an expired deadline returns `_failed(TURN_DEADLINE_EXCEEDED, ...)`, which keeps the completed exchanges (B75). `DeadlineExceededError` (a subclass of `ModelUnavailableError`) is caught before its parent, so `RecordingModel`'s `except ModelUnavailableError` still marks a failed run.
- Adapter: before each attempt, if `remaining < 1 s`, it raises `DeadlineExceededError` (nothing is sent and nothing is reserved). Otherwise: `gate.admit(request)`, then `with_options(timeout=min(60, remaining), max_retries=0)`, then `gate.settle(ticket, usage | None)` in `finally`. A retryable failure waits only when `wait < remaining - 1`. Otherwise it raises `DeadlineExceededError` if time ran out, or `ModelUnavailableError` once the 3 attempts are used (S9.4-S9.6).
- The bound is honest about httpx: `timeout` bounds each I/O phase, not the total. A non-streamed reply arrives in one piece, so in practice the read phase is the whole wait. This is a residual risk (§13).
- Startup: `turn_deadline(env)` reads `DALE_TURN_DEADLINE_SECONDS` (default 90) and exits 2 unless the value is greater than `verifier_runner.TIMEOUT_SECONDS` (30), on the terminal and on the web (S9.11).
- Unchanged: settings, system blocks, tools and messages. The fingerprint pin holds, and every committed Haiku and Sonnet recording must replay as it is (S9.9). D17's "no request timeout" stays (Caddy and uvicorn set none). The page's no-abort comment and the B61 pins are restated: the server now bounds a turn at the deadline plus one tool round (statement timeout) plus the 30 s verifier.

## 4. Web channel in demo mode

**Request order.** Each step rejects with the envelope and executes nothing further. Anything a step acquired is released when a later step rejects.

| Step | Where | Check |
|---|---|---|
| 1 | guard (unchanged) | Host, Origin, JSON, body cap |
| 2 | guard, demo only | Client IP (DD36). None usable → `invalid_request` |
| 3 | session layer, demo only | Parse the cookie, or issue one (`Set-Cookie` on the response) |
| 4 | create route | Demo mode parses the body as `StartConversation{notice_version: int \| None = None}` (strict, additive command). An absent field or another version → `notice_not_accepted`, so `{}` answers `notice_not_accepted`, not 422. An unknown field → `invalid_request` (S14.2). Local mode keeps ignoring the body (`routes.py:51-52`). This step reads no state, so the smoke check works while paused |
| 5 | registry `using` | Id bound to this session, else `conversation_not_found` (O2, and the TTL). A tombstone left by a reset → `demo_reset` |
| 6 | policy port | Control readable and not paused, registry not draining, scheduler thread alive, and today's spend leaves room for the reference request (DD38). Any failure → `demo_paused`. A request that arrives during a reset drain gets `demo_paused` (S11.2) |
| 7 | registry (memory) | Create: live cap 10 → `demo_busy`. Turn: 20 turns per conversation reached → `rate_limited`, then the 4-turn semaphore (non-blocking) → `demo_busy`, then the conversation lock → `conversation_busy` |
| 8 | policy port (DB, last) | Create: the session-per-day and IP-per-day counters in one transaction (DD37) → `rate_limited`. Turn: IP 60 per day → `rate_limited`. A store error → `demo_paused`. Only after this step passes does the conversation's turn count increase |
| 9 | backend | Create: visitor customer, then `compose`. A failure gives its catalog code, with no fallback (S14.5), and keeps the counted slot (fail closed). Turn or press as in v0.2 |

- **Presses** run steps 1-3, 5 and 6 (O5). They take no turn token and are bounded by the live cap, at most 10 × (1 press + 1 waiter) threads. With the 4 turns, the host stays well under anyio's 40 tokens.
- **`DemoRegistry`** keeps `{id: (conversation, owner_hash, last_seen, in_flight)}` and one in-flight counter, under one mutex with a `Condition`.
  - Every request runs inside `using(id, visitor)`, which increments the counter on entry and decrements it in `finally`. Admission and the drain flag share the mutex, so no request can slip in between them.
  - A new conversation from the same session ends that session's earlier one, which then gets `conversation_not_found`.
  - The TTL sweep runs on every create and on every scheduler tick, and skips entries with work in flight (S17.5).
  - Drain API: `begin_drain()`, `wait_idle(timeout) -> bool`, `end_all()` (its tombstones answer `demo_reset`) and `reopen()`. Tombstones are kept until restart, at most 10,000.
- **Conversation reference.** The page shows the conversation id it already holds, `ResponseEnvelope.conversation_id` (the `WebConversation` id). The transcripts store that same id as `conversation_ref`, and `purge --conversation` takes it (O9 S9.6).
- **New codes** (W11; statuses fixed): `rate_limited` 429, `demo_paused` 503, `demo_busy` 503, `demo_reset` 410, `notice_not_accepted` 403. `ErrorCode.TURN_DEADLINE_EXCEEDED` answers 504 (log D18). All are additive to contract v1. The schemas, TS types and `notice.json` are regenerated; these are generated files, excluded from the size count (DD42).
- **Refusals mid-turn.** A refusal by the gate ends the turn as `model_unavailable`, and the next request gets `demo_paused` at step 6 (log D15).
- **No other visitor's data (W11 S11.5).** Every refusal carries only its code and fixed message. The envelope has no field for counts, limits, sessions or IPs, and a test asserts the `rate_limited` body.

## 5. `demo` schema (migration 0006)

| Table | Columns (key first) | `dale_app` grants |
|---|---|---|
| `control` | `id smallint` (CHECK = 1), `paused`, `reason`, `changed_at`, `reset_requested_at`, `last_reset_at`, `last_reset_result` | SELECT, UPDATE |
| `host_status` | `id` (= 1), `live`, `in_flight`, `transcript_failures`, `reset_failures`, `started_at`, `updated_at` | SELECT, INSERT, UPDATE |
| `spend_day` | `day date`, `committed_micros bigint ≥ 0` | SELECT, INSERT, UPDATE |
| `spend_request` | `id uuid`, `day`, `model`, `reserved_micros`, `cost_micros` (null until settled), four token counts (null when unknown), `outcome`, `created_at`, `settled_at` | SELECT, INSERT, UPDATE |
| `counter` | `(day, kind, subject bytea)`, `count` | SELECT, INSERT, UPDATE, DELETE |
| `transcript` | `conversation_ref uuid`, `session_hash bytea`, `notice_version`, `brain_conversation_id`, `started_at` | SELECT, INSERT, DELETE |
| `transcript_event` | `(conversation_ref, seq)`, `kind` (CHECK set), `body jsonb`, `at`. FK to `transcript`, ON DELETE CASCADE | SELECT, INSERT, DELETE |

- `dale_owner` creates and owns the schema. `REVOKE ALL ON SCHEMA demo FROM PUBLIC`. Only `dale_app` gets `USAGE`. There are no default privileges, so a future table gets nothing until it is granted.
- `dale_verifier` gets nothing: no `USAGE`, checked by an integration test. The verifier's SQL, run scope and process are untouched (R11). Visitor customers are ordinary `erp.customer` rows.
- Spend rows are never purged: they hold no personal data, and the monthly figure needs them.
- `migrations/env.py` adds `"demo"` to `SCHEMAS` and `dale.apps.demo.tables.METADATA` to the targets, so CI's `alembic check` covers the new tables.

**Fail-closed reads.** These give `demo_paused` or an unsent request: the control row is unreadable; `spend_day` cannot be read or reserved; a counter transaction fails; the scheduler thread is dead. These make the host refuse to start (exit 2): the price table has no entry for the model; the template customer is missing; a demo setting is missing or invalid; `retention_days` differs from `NOTICE.retention_days`; the drain bound is not above deadline + 30; the scheduler thread does not start. A heartbeat or transcript write that fails is only logged and counted.

## 6. Scheduler and nightly reset (O9, O11)

**Tick.** The scheduler ticks every 30 s:
- writes the heartbeat (`host_status`);
- runs the TTL sweep;
- once per Buenos Aires day, runs `purge_expired` (transcripts older than retention, counters older than 2 days) as its own step, so a failed or skipped reset never skips it (O9 "at least nightly").

Each tick catches its own exceptions. If the thread dies anyway, step 6 answers `demo_paused`, and `status` reports a heartbeat older than 2 minutes as "host not reporting".

**When a reset is due.** At 04:00 America/Argentina/Buenos_Aires, when `last_reset_at` is before today's 04:00, or whenever `reset_requested_at` is set.

**Reset steps:**
1. `UPDATE control SET paused, reason='reset' WHERE NOT paused`, and remember whether the reset owns the pause. If this write fails, abort the reset with nothing changed: log it, increment `reset_failures`, and retry no sooner than 5 minutes later.
2. `registry.begin_drain()`, then `wait_idle(drain_bound)`. The default bound is 150 s, and startup requires it to exceed deadline + 30. Requests meanwhile get `demo_paused`. On timeout: record `last_reset_result='drain_timeout'`, keep the pause, call `reopen()` so that ids stay valid, and stop (S11.3).
3. `end_all()`: the old ids get `demo_reset`.
4. `reseed(engine)`, then `reset_brain(engine, company_id)`. On any exception: record `reseed_failed` and keep the pause (S11.4).
5. `reopen()`, then `UPDATE ... SET paused=false WHERE reason='reset'` (only if step 1 owned the pause), then record `ok`.

The reseed runs only after the drain reports zero in flight and every conversation has ended. That ordering is an invariant, tested with threads and a fake clock (S11.2).

## 7. Transcripts, export, purge

- **What is written** per conversation: the head row at create; `customer_text` before the turn; after the reply, the response events in seq order, one `usage` row per call (tokens and cost) and `error` (the code).
- **What is never written**: an IP, user agent, raw token, cookie or headers (S9.2). Log lines never hold customer text (`routes.py:93-95` already follows this).
- **The CLI** runs as `docker compose run --rm app python -m dale.apps.demo <command>` in scripts (this works whether or not the app is up), or with `exec` interactively:

| Command | Behavior |
|---|---|
| `pause [--reason operator\|deploy]` | Idempotent; exits non-zero when the write fails |
| `resume [--if-reason R]` | Idempotent; exits non-zero when the write fails |
| `status` | The O6 fields, from `control`, `host_status`, `spend_*`, `counter` sums and `transcript_event` errors in the last 24 h; heartbeat age; `transcript_failures`; `reset_failures` |
| `reset` | Sets `reset_requested_at`; the scheduler runs the reset |
| `purge --conversation <ref>` | Deletes that conversation's rows only |
| `purge --expired` | Deletes transcripts older than retention |
| `export --since D --only-failures --out DIR` | Writes `DIR/dale-export-<date>.jsonl` with mode 0600. The O10 filter selects a non-verified verdict, a failure code, a refusal, the turn limit, the turn deadline or a handoff |

- **Git gate.** The `tracked-files` job also fails on any tracked `*.jsonl` outside `evals/recordings/` (S9.5). `.gitignore` gains `dale-export-*.jsonl`.

## 8. Page (`apps/web`)

- `client.ts` uses same-origin `fetch`, so the cookie goes with every request. On load the page reads `GET /v1/contract` and its `demo` field (DD42).
- Reducer additions: `demo: {notice, noticeAccepted}`, and a `blocked` state derived from the code: `demo_paused`, `demo_busy`, `rate_limited`, `demo_reset`, `notice_not_accepted` or `turn_deadline_exceeded`.
- On `demo_reset`, the reducer clears `pendingProposalId` and offers a new conversation (S19.2).
- New presentational components:
  - `NoticeBanner`: always visible in demo mode, links to `/privacidad`.
  - `AcceptNotice`: sends `{notice_version}` with the create request.
  - `DemoState`.
  - `ConversationReference`: shows `conversation_id`.
- The tool-trace panel stays (log D13). All copy is static Spanish in `i18n/es.ts`, and the owner approves it (hard gate 4).

## 9. Packaging, release, deploy

| Artifact | Content |
|---|---|
| `Dockerfile` | Three stages pinned by digest: the page build (`npm ci --ignore-scripts`), Python (`uv sync --locked --no-dev --no-editable`), and the runtime. The runtime copies the venv, `page/`, `migrations/`, `pyproject.toml` (alembic config) and `db/roles.sql`; runs as user 10001; sets `DALE_WEB_PAGE_DIR=/app/page`; runs `python -m dale.apps.web`. `.dockerignore` is an allow-list |
| `deploy/compose.yml` | `db`: postgres:17@digest on a bridge, `127.0.0.1:5432:5432`, a volume, `deploy/db/init.sh` (runs `db/roles.sql`, creates the database owned by `dale_owner`, sets passwords from env). `app`: host network, `env_file: /etc/dale/app.env`, `read_only`, `cap_drop: [ALL]`, `no-new-privileges`, `stop_grace_period: 150s`, json-file logs at 10 MB × 5. `migrate`: profile `ops`, `env_file: /etc/dale/owner.env`, `alembic upgrade head`. No key name appears in any tracked file |
| `deploy/Caddyfile` | `{$DALE_DOMAIN}` (log D14 pending); HSTS `max-age=31536000`; `request_body max_size 16KB`; `reverse_proxy 127.0.0.1:8000`. Caddy's default HTTP→HTTPS redirect stays; no response timeout |
| Root-only files | `/etc/dale/{app,owner,db}.env`, mode 0600, owned by root. The demo key and the session secret live only in `app.env` (log D3). The runbook names the variables; it is markdown, which the key-name scan does not read |
| `PAGE` | `DALE_WEB_PAGE_DIR`, with the source-checkout default (`web.py:62` today). Demo mode exits 2 when the directory is missing |
| `release.yml` | Trigger: `push: tags: ['v*']` only. Jobs in order: `on-main` (`git merge-base --is-ancestor`), `ci` (`uses: ./.github/workflows/ci.yml`), `report` (`scripts/check_release.py`), `image` (`packages: write`: build, `scripts/scan_image.sh`, push `:<tag>`), `release` (`contents: write`; the digest goes in the body). Only `GITHUB_TOKEN` |
| `check_release.py` | Report `evals/reports/<tag>-<default model>.json`: `mode ∈ {live, record}` (both are live runs: `evals/harness/model.py:69-71`; the v0.2 report says `record`); `commit` clean (no `-dirty`) and an ancestor of the tag; `model` equal to `MODEL_SETTINGS.model`; non-empty `snapshot_ids`; the four gates at 0; `metrics.pass_3.cases == 40` and at least 35 cases passed. Also: 40 case files; `git diff --quiet <commit> <tag> -- <guarded paths>`; runtime prices equal to `pricing.toml`; the ADR 0013 commit precedes the first release report commit |
| Guarded paths | `src/dale`, `evals/cases`, `evals/harness`, `evals/conftest.py`, `evals/pricing.toml`, `migrations`, `uv.lock`, `pyproject.toml`, `docs/decisions/0013-*`, `scripts/check_release.py`. A constant in the script, which is itself guarded |
| `scan_image.sh` | Exports the image filesystem and fails on the key value pattern `sk-ant-[A-Za-z0-9_-]{20,}`, on any `.env*` file and on any `dale-export-*` file. It does not use key-name patterns, because the SDK's own source names `api_key` |
| `deploy/server/dale-deploy.sh` | Validates its arguments again. A **first deploy** (no `/opt/dale/state/current`) skips the pause: there is no app, and `demo.control` does not exist until the migration seeds it `paused, initial`. Otherwise: `pause --reason deploy`. Then: pull `@digest` and check that `:<v>` resolves to the same digest (S8.5); `migrate` (on failure: `resume --if-reason deploy` and exit 1, so the old image keeps serving, S8.3); `up -d app`; a local `/health` check with `Host` and `X-Forwarded-For`; record `current` and `previous`. `rollback` starts `previous` and checks its local `/health`, or stops the app when there is no previous version (S8.4) |
| `deploy/deploy.sh` (owner) | Validates the version (`^v[0-9]+(\.[0-9]+){1,2}$`). Reads the digest with `gh release view`; exactly one `sha256:<64 hex>` is required. Runs `ssh "$DALE_DEPLOY_SSH" sudo /opt/dale/dale-deploy <v> <digest>`, then the public smoke check. **Smoke passes:** `resume --if-reason deploy`. A first deploy stays `paused, initial` until the owner resumes it by hand after a look. **Smoke fails:** `dale-deploy rollback`, the smoke check again against the previous version, and `resume --if-reason deploy` only if that smoke check passes; otherwise the demo stays paused. Exit 1 either way (S8.2) |
| Smoke (G9) | Over the public URL: `/health` returns 200 over HTTPS; HTTP answers 301 or 308 to HTTPS; HSTS is present; the CSP is on `/`; `POST /v1/conversations` with the allowed `Origin` and `{}` returns `notice_not_accepted`. From the owner's machine, ports 8000 and 5432 must not be connectable (refused or timed out). The smoke check never calls the model |

## 10. Testing strategy

| Area | What | How |
|---|---|---|
| Deadline | S9.3-S9.8 and S9.11; `remaining < 1` sends nothing; `DeadlineExceededError` ordering; fingerprint pin; replay of every recording | A fake `anthropic` client whose `create` advances a fake monotonic clock and raises SDK errors built with `httpx.Response` (including the `retry-after` headers); an injected `sleep` |
| Statement timeout | S9.10; `connect_timeout` kept | Integration: `SELECT pg_sleep(6)` through a tool's data path gives `rules_unavailable` and no order |
| Visitors | S14.3-S14.6; concurrent presses both `verified` (S14.4) | Integration: real Postgres, replay model, real verifier subprocess |
| Registry | Caps; TTL at 29 and 30 min; in flight not expired; tombstones; drain atomicity; ownership; `InMemoryRegistry` with `visitor=None` | Unit, fake clock, `threading.Event` blocking fakes; v0.2 tests unchanged |
| Guard and session | S8.5-S8.10; cookie attributes; no cookie in local mode; step order (§4); `{}` gives `notice_not_accepted`; no clear IP in logs (caplog); S11.5 body | `TestClient` with `client=("127.0.0.1", …)` and other peers |
| Limits | Create counters roll back together; the turn count rises only after step 8; the semaphore is released on a step 8 refusal | Integration |
| Ledger | Atomic reserve S4.4 (two threads, room for one); settle; unknown usage at worst case; restart S4.3; Buenos Aires day S4.7; fail closed S4.5 | Integration with real Postgres and a frozen clock |
| Reservation bound | `reserve ≥ actual cost` for every recorded call | Replay test over all recordings (usage in `message.usage`) |
| Prices | Runtime table equals `pricing.toml` | Unit |
| Control, CLI, scheduler, reset | S5.x, S6.x, S11.1-S11.6; a failed step-1 write; a dead scheduler gives `demo_paused`; the purge runs after a failed reset | Integration plus CLI `main(argv)` with captured output |
| Transcripts | S9.1-S9.6, S10.1-S10.2; a write failure does not change the reply | Integration; a failing sink fake |
| Grants | `dale_app` per-table privileges; no `dale_verifier` `USAGE` on `demo`; revisions from 0006 on are additive | `has_table_privilege` and `has_schema_privilege`; DDL lint |
| Contract | v0.3 additive against the v0.2 goldens (S5.5); new codes mapped (S11.4); `notice.json` excluded from the size count | pytest goldens; `test_check_pr_size.py` |
| Page | Each state renders as text; reset clears the pending proposal; banner in every state; accept-to-start; reference shown | Vitest and Testing Library |
| Release | `check_release.py` table: `record` and `live` accepted, `replay` refused; S3.2, S4.1-S4.6, S5.1-S5.3. Workflow: S1.3, S7.1, S7.2 (only `GITHUB_TOKEN`, no `ssh`) | pytest over temporary git repositories; `test_release_workflow.py` |
| Deploy | Argument validation; digest mismatch; migration failure; smoke failure; first deploy (no pause, stays `initial`); rollback, and resume only after the previous version's smoke passes | pytest running the scripts with stub `docker`, `ssh`, `gh` and `curl` on `PATH` that log their argv |
| Packaging | No key names in tracked files (existing script); compose binds `127.0.0.1`; host network; `env_file` paths outside the repository | Unit over the YAML and Caddyfile |

## 11. Threat matrix

| Boundary | Applicability | Design response | Planned RED tests |
|---|---|---|---|
| Documentation-like paths | N/A: nothing classifies or executes repository files by name. The `.dockerignore` allow-list is a packaging list, not execution | — | — |
| Git repository selection | Applicable: `check_release.py` runs `git` | Fixed argv with no shell; `cwd` is the repository root from `__file__`; revisions validated (40-hex commit, tag regex) before use; `--` before pathspecs | A commit holding `--upload-pack` text and a malformed tag are refused; pathspecs are literal |
| Commit state | N/A: nothing stages or commits | — | — |
| Push state | Applicable (image push): `docker push` of `ghcr.io/<repo>:<tag>` only after the earlier jobs | `needs:` chain; the tag comes from `github.ref_name` and is checked against the regex | A workflow test asserts `needs` and the regex step |
| PR commands | N/A: no PR automation | — | — |
| Shell and SSH (added row) | Applicable: `deploy.sh` and `dale-deploy.sh` | `set -euo pipefail`; version and digest checked by regex in both scripts; one fixed remote command; arguments quoted; no `eval`; the SSH destination comes from the owner's environment, never from the repository | `v0.3;rm -rf /`, a digest with a newline, two digests in the release body and an empty previous are refused before any `docker` or `ssh` call |
| Subprocess (added row) | Unchanged: the verifier spawn (fixed argv, stdin, 30 s). The CLI runs no subprocess | — | Existing tests |

## 12. Observability

- One JSON log line per `/v1` request: route kind, status, code, conversation id, the first 8 hex digits of the session hash, latency in ms, model calls, tokens and cost in micros.
- One line per model attempt from the gate: outcome, tokens, cost, wait.
- No customer text, IP or user agent in either.
- `status` is the operator's view (§7), including the heartbeat age.
- An external free uptime check on `https://<domain>/health` (the owner chooses it), and the Console's spend alerts on the demo workspace (log D7). No browser SDK.

## 13. Risks and rollback

| Risk | Mitigation |
|---|---|
| httpx timeouts bound phases, not total time | A non-streamed reply makes read ≈ total. The deadline check runs before every attempt. Measure p95 on the release live run (log D10) |
| The byte bound on input tokens is an assumption | The replay test over every recording; settlement uses the actual usage anyway |
| Worst-case charges during an API outage can exhaust the cap | Intended (fail closed). `status` shows open and unknown reservations. The cap resets on the Buenos Aires day |
| Conversation state is in memory only | A deploy or restart drops live conversations (accepted; restore is out of scope) |
| Session-cookie churn defeats per-session limits | Per-IP limits (60 turns and 10 conversations per day) are the real bound (log D17) |
| The contact email becomes public in settings and on the page | The owner provides a dedicated alias (hard gate 4) |

**Rollback.**
- The kill switch (`pause`) comes first.
- `deploy.sh` redeploys the previous digest, and the additive migrations keep it working (DD46).
- Every slice below is one revertible PR, and local mode keeps v0.2 behavior.

## 14. Decision records

| # | Title | Slice |
|---|---|---|
| 0009 | Public demo: demo mode, visitor customers (supersedes B65), caps and limits, spend cap and ledger, kill switch, in-process reset (DD26-DD27, DD31-DD33, DD37-DD40, DD43) | 1b |
| 0010 | Cookie session and CSRF; client IP from loopback (DD34-DD36). Amends 0005 | 1b |
| 0011 | Turn deadline and bounded retries (DD28-DD30). Amends 0004 D17 and B61 | 1a |
| 0012 | Hosting, packaging, release workflow, owner-run deploy, no key in CI (DD44-DD46; log D1-D3, D5) | 1b |
| 0013 | Release eval criterion, pre-registered: hard gates at 0 and pass^3 of at least 35 of 40, valid only for 40 cases (log D12). It must precede the first release live report | 1a |

## 15. Slice plan

Each figure is an upper bound of authored lines including tests; generated files, lockfiles and reports are excluded. Each target is at most 330.

| # | Slice | Depends on | ~Lines |
|---|---|---|---|
| 1a | ADR 0011 and ADR 0013 (criterion first) | — | 220 |
| 1b | ADRs 0009, 0010, 0012 | 1a | 330 |
| 2a | `Deadline`, the `ModelRequest` field, `TakeTurn` checks, tests | 1a | 300 |
| 2b | `TURN_DEADLINE_EXCEEDED` (catalog, 504, message), contract regeneration, `turn_deadline` startup validation (web and terminal) | 2a | 220 |
| 2c | Adapter loop (DD29); fake-clock and SDK-error tests | 2b | 330 |
| 2d | `AttemptGate` port (unused yet), `app_engine` (DD30), S9.10, B61 comments and pins | 2c | 280 |
| 3 | `VisitorCustomers` port, application, SQL, integration tests | — | 300 |
| 4 | Create `dale.apps.demo` with `settings.py` (O1 parsing and validation); `DALE_WEB_MODE` and `DALE_WEB_PAGE_DIR` in `web.py` (no move); contracts 4, 13 and 14 | 2b | 320 |
| 5a | Migration 0006, `apps.demo.tables`, `env.py`, `roles.sql` header | 4 | 250 |
| 5b | Grant tests, additive-DDL lint | 5a | 180 |
| 6a | `prices.py`, sync test, reservation and cost functions, replay bound test | 5a | 300 |
| 6b | SQL ledger implementing `AttemptGate`, with integration tests (S4.x) | 6a, 2d | 330 |
| 7a | Control store; CLI `pause` and `resume`; `__main__` | 5a | 260 |
| 7b | CLI `status` (first fields) | 7a | 200 |
| 8a | New `WebErrorCode` values, `StartConversation`, `/v1/contract` `demo` field, `notice.json` and its size exclusion | 4 | 300 |
| 8b | Client IP (DD36) and guard step 2 | 8a | 220 |
| 8c | Session layer (DD34); local mode sets no cookie | 8b | 280 |
| 9a | Registry port change in `conversations.py`, `InMemoryRegistry`, `routes.py` callers (DD43) | 8a | 220 |
| 9b | `DemoRegistry`: caps, TTL, ownership, tombstones | 9a, 8c | 330 |
| 9c | `DemoRegistry`: in-flight counting and drain API | 9b | 240 |
| 9d | Demo route order (§4) and the policy port (fakes) | 9c | 300 |
| 9e | `apps.web_demo`: visitor backends, gate and control wiring | 9d, 3, 6b, 7a | 280 |
| 10 | SQL counters (one transaction per create) and the policy adapter (S3.x) | 9e | 320 |
| 11a | Transcript sink, SQL writer, usage and cost rows, write-failure counter | 10 | 330 |
| 11b | `purge` and `export`, the tracked-files `*.jsonl` rule, `.gitignore` | 11a | 300 |
| 12a | Scheduler tick: heartbeat, TTL sweep, nightly purge, liveness check at step 6 | 11a, 9c | 280 |
| 12b | Reset steps (§6), remaining `status` fields | 12a | 320 |
| 13a | Page: contract fetch, reducer states | 8a | 280 |
| 13b | Page: banner, accept step, reference, state components | 13a | 330 |
| 13c | Privacy page and `PageFiles` (DD41) | 13b | 240 |
| 14 | Dockerfile, `.dockerignore`, compose, Caddyfile, `db/init.sh`, file tests | 4 | 330 |
| 15a | `check_release.py`: report and criterion checks | 1a, 6a | 300 |
| 15b | `check_release.py`: guarded paths, prices, case count, history order | 15a | 240 |
| 15c | `ci.yml` `workflow_call`, `release.yml`, `scan_image.sh`, workflow test | 15b, 14 | 300 |
| 16a | `dale-deploy.sh` and stub-based tests | 15c | 320 |
| 16b | `deploy.sh`, smoke check, stub-based tests | 16a | 320 |
| 17 | README, runbook, `docs/releases/v0.3.md`, notice and privacy text approval. Then the user gates: live report, merge, tag, deploy | all | 250 |

At most about 10,400 lines in 37 PRs. Since each figure is a ceiling, the expected total is about 8,500-10,000, inside the proposal's forecast. **400-line budget risk: High** per slice. Slices 3, 13a-13c, 14 and 15a-15b can run in parallel with the main chain.

## 16. Open questions

- [ ] Log D14 (domain) blocks the Caddyfile value, the allow-list, the HSTS scope (`includeSubDomains` only on a dedicated domain) and the smoke check targets. Not blocking before slice 16.
- [ ] The privacy contact and the notice wording come from the owner (hard gate 4).

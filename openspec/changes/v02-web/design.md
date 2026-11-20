# Design: Dale v0.2 "Se ve"

v0.2 adds a local web channel (`dale.channels.web`, FastAPI) and a React page over the unchanged `TakeTurn` and `ConfirmProposal`. It also adds two additive brain and verifier outputs (the tool trace and the stored order in the verdict), contract v1 with generated schemas and TS types, and a model dimension in the eval harness that applies the pre-registered comparison rule mechanically. Sources: `proposal.md` (accepted 2026-11-19), `exploration.md`, the specs `web-channel` and the `verified-order` delta, and the v0.1 design (D1-D10, still in force). The archived v0.1 design is not the as-built description; the decisions below are grounded in the current code (file:line refs).

## 1. Decisions

Numbering continues from v0.1 (D1-D10).

| # | Decision | Options considered (tradeoff) | Choice and rationale |
|---|---|---|---|
| D11 | Shared channel logic | **a)** Move `Backend`, the `Verdict` protocol, `VerifierFailed`, `step` and `Pending` to `dale.channels.common`. **b)** Web imports them from `channels.terminal` (couples the channels). **c)** Duplicate them (two `Pending` rules drift) | **a.** It is a pure move: terminal text constants and `TerminalSession` stay in place, and the terminal tests change only their imports (S18.3) |
| D12 | Host shape | **a)** FastAPI with sync `def` routes in the threadpool, one uvicorn worker, bound to `127.0.0.1` with no flag to change it. **b)** `async` routes with `run_in_threadpool` (same effect, more code). **c)** Plain Starlette (no DTO validation) | **a.** SQLAlchemy, the Anthropic SDK and the verifier subprocess are all blocking. In-memory state requires one worker. `/docs`, `/redoc` and `/openapi.json` are disabled, which keeps the route table exact (S2.1) |
| D13 | Transport | Request/response JSON with an SSE-ready envelope (user decision) | Recorded only. Each event carries `v`, `seq`, `conversation_id`, `type` and `data`, so SSE can stream the same objects later |
| D14 | Response and error shape | **a)** Every API response is one `ResponseEnvelope`; status = 200/201 when `error` is null, else `status_for(code)`. **b)** Always 200 with an `ok` flag (hides 409/503 from logs and clients). **c)** A separate error body without events (a failed press could not carry its verdict, which W13 forbids) | **a.** A brain outcome code (`OrderRejected.code`, `SystemNotice.code`, `TurnResult.failure`) maps through `shared.errors.HTTP_STATUS` (`errors.py:31`). Transport codes get their own `WebErrorCode` enum in `channels.web.errors`, disjoint from `ErrorCode`. They never appear in a shown event, so the shared catalog and the verifier's parser stay unchanged |
| D15 | Press safety beyond `ConfirmProposal` | **a)** Server-side gate on `Pending`, plus per-proposal press serialization, plus a replay of the settled response. **b)** Trust `ConfirmProposal` alone: a proposal cancelled on the page stays `prepared` in the DB (cancel is channel-only, `session.py:93`), so a stale press would confirm it. **c)** Reject a concurrent press with 409 (breaks "identical bodies", S7.1) | **a.** See §4.3. The gate never confirms an id other than the server's pending id. A settled outcome (`OrderConfirmed`/`OrderRejected`) is replayed byte for byte (Stripe-style idempotency). `rules_unavailable` and unknown outcomes are not cached, so a retry runs again (B53) |
| D16 | Per-conversation lock | **a)** `threading.Lock`, non-blocking: 409 `conversation_busy`. A press of the same proposal id waits up to 60 s for the running press. **b)** Queue requests (hides overlap, and a slow turn backs up the page) | **a.** `TakeTurn` keeps `_history` and is not thread-safe (`take_turn.py:63`). The lock is released in `finally` (S12.2). Conversations are independent (S12.3) |
| D17 | Request timeouts | **a)** No server request timeout and no client abort. The page shows an elapsed-time pending state. **b)** A 120 s client abort (the turn keeps running server-side, and with no read route the page would lose its events) | **a.** Python cannot cancel a running sync turn. Worst case: 6 model calls × 3 attempts × 60 s (`anthropic_model.py:19`), plus the 30 s verifier (`verifier_runner.py:24`), is about 19.5 min. Every timeout the stack sets (uvicorn, Vite dev proxy `proxyTimeout`) must exceed it, and a test pins this. A turn deadline in the brain is Known pending |
| D18 | Tool trace | **a)** Additive `TurnResult.trace`, built in `_run` from each call and its `ToolOutcome`, plus `ToolOutcome.code`. **b)** An observer hook (needed only for SSE). **c)** Parse the error code back out of `content` | **a.** Outside the prompt path: §5 proves the fingerprint and the replay digest are unchanged. The hook is deferred with SSE |
| D19 | Order panel source | **a)** `Report.stored` = `Evidence.orders` (already read, `verdict.py:63`), emitted as a required `stored_orders` in the strict verdict. Product names come from the matching `ProposalSummary` on the page. **b)** Also make the verifier read product names (changes its SQL). **c)** Use `OrderConfirmed` lines (shows management's reply, not the DB) | **a.** The panel shows what was judged, and the judged checks and the SQL do not change (R11) |
| D20 | Schema and TS generation | **a)** pydantic `TypeAdapter` in `channels.web` over the shared dataclasses and the web DTOs, then `json-schema-to-typescript`, with both outputs committed. **b)** `openapi-typescript` from FastAPI's OpenAPI (couples types to routes, and OpenAPI is disabled). **c)** Hand-written TS (drifts) | **a.** `shared` must not import pydantic (contract 6). The shown-event `data` is exactly the verifier's JSON form (`shown_events.to_json`), so one form serves both readers |
| D21 | Frontend state | **a)** `useReducer` over envelopes in one container hook. **b)** TanStack Query (no server cache to manage: three commands). **c)** Zustand (global store for one screen) | **a.** One conversation, one screen, no router. The reducer is pure and tested without the DOM |
| D22 | Node supply chain | **a)** Exact versions, `.nvmrc` plus `engines` with `engine-strict`, `save-exact`, and `npm ci --ignore-scripts`. **b)** Caret ranges with a lockfile only | **a.** Follows 0001. A unit test fails on any non-exact version. If a pinned tool needs an install script, the decision record names it |
| D23 | Model dimension in evals | **a)** `--model` chosen from a registry of compared settings; `recordings/<model>/<case>/run-N.jsonl`; per-model tables in `evals/pricing.toml`; per-model `known_misses.toml`; a CI `evals` job with a model matrix. **b)** An environment variable (invisible in pytest ids). **c)** Keep replay in `test` for both models (240 runs against a 15 min limit) | **a.** The fingerprint already includes the model (`prompt.py:54`), so a cross-model replay fails as S13.8 requires. The matrix keeps each model under its own time limit and reports failures per model |
| D24 | Applying the comparison rule | **a)** A pure `evals/harness/compare.py` that refuses unless the fixed conditions hold. Gate counts come from the grader. **b)** A human reads two reports (not mechanical) | **a.** Pre-registered in ADR 0007, committed before the first Sonnet recording (S16.1) |
| D25 | Readiness | **a)** `GET /health` runs `SELECT 1` on the app engine, then answers 200, or 503 `rules_unavailable`. **b)** A separate `/ready` (not in W2's route list) | **a.** It closes the `/ready` rule that v0.1 deferred to v0.2 (v0.1 design §11) within the spec's route table |

## 2. Module layout and import contracts

```
src/dale/channels/common/{backend.py (Backend, Verdict, VerifierFailed, step), pending.py}
src/dale/channels/terminal/            imports common; pending.py removed
src/dale/channels/web/{contract.py, errors.py, schema_gen.py, guard.py, conversations.py, routes.py, app.py}
src/dale/apps/compose.py               compose() + ChannelBackend moved from apps/terminal.py, gains `channel`
src/dale/apps/web.py                   composition root: env, fixed customer, verdict mapping, uvicorn
contracts/v1/*.schema.json, components.json (generated)   contracts/v1/samples/*.json (authored)
apps/web/                              React page (§6)
evals/harness/{models.py, compare.py}  evals/recordings/<model>/...
```

| # | Contract change |
|---|---|
| 5 | Unchanged rule; renamed "channels (common, terminal, web) import no erp_sim, brain.domain or brain.infrastructure" |
| 9 (new) | `forbidden`: `dale` → `fastapi`, `starlette`, `uvicorn`, ignoring `dale.channels.web.**` and `dale.apps.web`. These three are added to `root_packages` |
| 10 (new) | `independence`: `dale.channels.terminal`, `dale.channels.web`; `forbidden`: `dale.channels.common` → both |
| 11 (new) | `forbidden`: `dale.channels` → `dale.apps`, `dale.verifier`. The channel reads verdicts through its own types; `apps.web` maps `VerifierVerdict` to them |

The new pins are `fastapi`, `uvicorn` (no extras) and dev `httpx` (TestClient). They are exact and added to the 0001 table.

## 3. Data flow

```
page ──POST /v1/conversations/{id}/messages {text}──▶ guard ─▶ routes ─▶ WebConversation (lock)
                                                         └─▶ backend.take_turn ─▶ TakeTurn ─▶ TurnResult(shown, failure, usage, trace)
page ──POST …/confirm {proposal_id}──▶ guard ─▶ press gate (Pending) ─▶ backend.confirm ─▶ ConfirmProposal
     after every press, and after a turn that showed OrderConfirmed: backend.verify(transcript) ─▶ run_verifier subprocess
◀── ResponseEnvelope{v, seq, conversation_id, events:[ToolCalled…, shown…, VerdictIssued], pending_proposal_id, error}
```

The transcript passed to the verifier contains only `ShownEvent`s. `ToolCalled` and `VerdictIssued` are web events that never enter it (S3.3). Within one response, events are ordered: tool calls in call order, then the shown events in shown order, then the verdict. v0.2 makes no claim that tool calls and shown events interleave.

## 4. Contract v1 and the HTTP host

### 4.1 Types (`channels.web.contract`)

| Type | Shape |
|---|---|
| `WebEvent` | `{v: 1, seq: int ≥ 1, conversation_id: uuid, type, data}`. `type` ∈ the six shown kinds, `ToolCalled` and `VerdictIssued` |
| shown `data` | The `to_json` form without `type` (`Money` = `{cents}`, ids as strings, ISO dates) |
| `ToolCalled` | `{name ≤ 64, summary ≤ 200, ok: bool, code: str \| null}` |
| `VerdictIssued` | `{subject_proposal_id \| null, verdict, reason, false_confirmations, unexpected_writes, findings[], stored_orders[{order_id, proposal_id, lines[{product_id, quantity, unit_price, line_total}], total, delivery_date, received_at}]}` |
| Commands | `SendMessage{text: 1-2000 chars}`, `PressDale{proposal_id: uuid}`, `CancelProposal{proposal_id: uuid}`. Strict, `extra="forbid"`, so client totals, customer or company ids are rejected (S7.4, S14.2) |
| `ResponseEnvelope` | `{v, conversation_id \| null, seq (last event seq of the conversation when built), events[], pending_proposal_id \| null, error: {code, message} \| null}` |
| Components | `components.json` maps event type → `OrderSummary`, `OrderConfirmation`, `Notice` (OrderRejected, SystemNotice), `HandoffNotice`, `ToolTrace`, `Verdict`; `AssistantText` → chat text. Generated from one Python dict; the page switches over it exhaustively |

The generator, `python -m dale.channels.web.schema_gen`, writes one file per type: sorted keys, 2-space indent, `additionalProperties: false` added to every object (matching `_load`'s exact keys, `shown_events.py:115`). The goldens run in the `test` job (S5.2). The `web` job regenerates the TS types and fails on `git diff --exit-code` (S5.3).

### 4.2 Routes, guard and errors

| Route | Body | Success |
|---|---|---|
| `POST /v1/conversations` | `{}` | 201, new id, no events |
| `POST /v1/conversations/{id}/messages` | `SendMessage` | 200 (or the turn's failure status) |
| `POST /v1/conversations/{id}/confirm` | `PressDale` | 200 (or the outcome's status) |
| `POST /v1/conversations/{id}/cancel` | `CancelProposal` | 200; clears `Pending` only, like the terminal's F3 |
| `GET /v1/contract` | — | `{v: 1, events, commands}` |
| `GET /health` | — | 200, or 503 (D25) |
| `/` | — | `StaticFiles(apps/web/dist, html=True)`, same origin, no CORS |

The guard is a pure ASGI middleware. It runs before routing, in this order:
1. `Host` must be in the allow-list → else `invalid_host`.
2. On POST, an `Origin` header, when present, must be in the allow-list → else `forbidden_origin`.
3. The media type must be `application/json` → else `unsupported_media_type`.
4. The body must not exceed 16 KiB, checked against `Content-Length` and by counting the stream → else `payload_too_large`.

Every response gets `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'`, plus `nosniff`, `Referrer-Policy: no-referrer`, and `Cache-Control: no-store` on `/v1`. The allow-list comes from `DALE_WEB_ALLOWED_HOSTS` and `DALE_WEB_ALLOWED_ORIGINS`. The default is `127.0.0.1:<port>` and `localhost:<port>` (W8, W17).

| `WebErrorCode` | Status |  | `WebErrorCode` | Status |
|---|---|---|---|---|
| `invalid_host` | 400 | | `conversation_not_found` | 404 |
| `forbidden_origin` | 403 | | `conversation_busy` | 409 |
| `unsupported_media_type` | 415 | | `turn_failed` (turn raised) | 500 |
| `payload_too_large` | 413 | | `confirm_outcome_unknown` (press raised; pending kept) | 503 |
| `invalid_request` (DTO) | 422 | | `internal_error` (handler bug; logged) | 500 |
| `not_found`, `method_not_allowed` | 404, 405 | | | |

Exception handlers map `RequestValidationError`, `HTTPException` and `Exception` to the envelope, with Spanish fixed messages and no exception text (S11.3). Tests check that the two enums are disjoint and that every code of both has a status and a message.

### 4.3 Conversation state and the press

The `ConversationRegistry` port has `create() -> WebConversation` and `get(id) -> WebConversation | None`. It is in memory in v0.2; v0.3 adds a persistent store, the cookie and limits behind it (S17.1). A `WebConversation` holds:
- the backend built by `apps.compose.compose(..., channel="web")` for the fixed customer `DALE_WEB_CUSTOMER` (default `C-001`), with the company from `DALE_WEB_COMPANY`;
- the transcript, `Pending`, the set of shown summary ids and the seq counter;
- the lock, the per-proposal press locks and the settled-response cache.

| Press step | Rule |
|---|---|
| 1 | Take the press lock of `proposal_id` (wait at most 60 s, else `conversation_busy`). If a settled response for this id is cached, return it unchanged (S7.1) |
| 2 | Acquire the conversation lock without blocking, else 409 `conversation_busy` (a turn is running) |
| 3 | Gate: the id equals `Pending.proposal_id`, or it was shown in an `OrderConfirmed` → `step("confirm", backend.confirm)`. It was shown in a summary but is not pending → `SystemNotice(proposal_not_pending)`. Otherwise → `SystemNotice(proposal_not_found)`. The two notices skip the brain (S6.4, S7.2, S7.3) |
| 4 | An outcome is appended to the transcript, and then `Pending.after_press` runs. A raised press shows nothing and keeps the pending id (`confirm_outcome_unknown`) |
| 5 | Always run `step("verify")`; a failure becomes `VerifierFailed` → `VerdictIssued` (`unverifiable`, S13.3) |
| 6 | Cache the response when the outcome is `OrderConfirmed` or `OrderRejected` |

A turn takes the lock without blocking. It appends `ToolCalled` events from `trace` and the shown events, runs `Pending.after_turn`, and verifies when an `OrderConfirmed` was shown. `SendMessage` builds only `CustomerText`, so typed "dale" reaches only the model (S6.2). The page applies `pending_proposal_id` only when the envelope's `seq` is greater than or equal to its own last seq, so a replayed press body can never change the button's state.

## 5. Brain trace and verifier evidence

- **Trace:** `ToolCallTrace(name, summary, ok, code)` is a new frozen dataclass in `brain.application.take_turn`. `TurnResult` gains `trace: tuple[ToolCallTrace, ...] = ()` as its last field, so existing constructors keep working. `_run` (`take_turn.py:100`) appends one entry per call: the name is cut to 64 characters, the summary is canonical JSON of `call.input` cut to 200 characters, and `code` comes from `ToolOutcome.code`, set only by `_error` (`tools.py:144`). `_failed` and `_refused` pass the trace through.
- **Fingerprint unchanged (proof):** `fingerprint` hashes only `asdict(settings)`, the system blocks and the tool schemas (`prompt.py:51-55`). Replay also compares `messages_digest(request.messages)` (`evals/harness/model.py:92-95, :112`). The trace is read from `call` and `outcome` after `self._tools.run(...)` and is stored only in `TurnResult`. `messages`, `self._history`, `TOOL_SCHEMAS`, `system_blocks` and `ToolOutcome.content` are untouched, and `_run`'s `tool_result` dict does not read `code`. Checks: (1) a unit test pins `prompt_fingerprint()` to its current hex value from slice 2 until the comparison slice; (2) the 54 v0.1 recordings must replay unchanged in CI, and any change would fail with "re-record required".
- **Verdict evidence:** `judge` builds `Report.of(findings, stored=evidence.orders)`, sorted by `(received_at, id)`; for `unverifiable` it is empty. `report_to_json` emits `stored_orders` (company id omitted; lines keep `*_cents`). `VerifierVerdict` (strict, `extra="forbid"`, `verifier_runner.py:27`) gains it as a **required** field, with checks: ids are unique, every non-null `finding.order_id` is among them, and `unverifiable` means empty. An old or partial output is therefore `malformed_output`, which fails closed. The child process always runs from the same tree, so there is no version skew.
- **Compatibility:** the terminal's `Verdict` protocol reads only `verdict`, `reason` and the counts (`render.py:36`). The grader, metrics and `known_misses` problem strings read the same fields (`grader.py:86-101`), and recordings hold model calls only. Nothing else moves.

## 6. Frontend (`apps/web`)

| Area | Design |
|---|---|
| Stack | React 19, TypeScript strict, Vite, Tailwind 4 (CSS file, no inline styles), Vitest with Testing Library and jsdom, ESLint with typescript-eslint, `react/no-danger` and a ban on `innerHTML` (S10.3). Exact versions are resolved at scaffold time and listed in ADR 0006 |
| Layout | `src/contract/generated/` (generated), `src/api/client.ts` (same-origin `fetch`, JSON, no timeout, parses any status into `ResponseEnvelope`), `src/state/{reducer.ts, useConversation.ts}`, `src/features/ConversationContainer.tsx` (the only container), `src/components/{ChatPane, Composer, DaleButton, TracePanel, OrderPanel, VerdictPanel, OrderSummary, OrderConfirmation, Notice, HandoffNotice, ToolTrace, Verdict}.tsx` (presentational), `src/i18n/es.ts` (all labels) |
| State | `{conversationId, lastSeq, chat: ChatItem[] (local customer text plus shown events), trace: ToolCalled[], verdicts: VerdictIssued[], pendingProposalId, inFlight: none\|create\|message\|press\|cancel, error}`. The reducer drops events with `seq ≤ lastSeq` (SSE-ready, idempotent) |
| Dale button | Enabled only when `pendingProposalId !== null && inFlight === "none"`. It posts `{proposal_id: pendingProposalId}` and disables itself on click (S15.4). On `proposal_not_pending` it shows the notice and the summary whose id is the server's current pending id, if any (S15.5) |
| Panels | Tools (each `ToolCalled`: name, summary, ok or the error code, as text). Order (the stored order in the latest verdict for `subject_proposal_id`; names from that proposal's summary lines, or the short id; with no stored order, "No hay un pedido guardado en la base"). Verdict (Spanish label plus an icon, never color alone). The four async states and `focus-visible` follow frontend-design |
| Text safety | All model and tool text is rendered as React text nodes. A test renders `<img src=x onerror=alert(1)>` in assistant text and in a tool summary, and asserts that no element is created (S10.2) |

## 7. Evals: model dimension and comparison

| Area | Design |
|---|---|
| Option | `--model <id>`, default `MODEL_SETTINGS.model`. `evals/harness/models.py` holds `COMPARED = {haiku, sonnet}` as `replace(MODEL_SETTINGS, model=...)`, so effort is medium for both. `model_factory`, `ReplayModel`, `RecordingModel` and `AnthropicModel(settings=...)` all receive the settings |
| Recordings | `recordings/<model>/<case>/run-N.jsonl`. The 54 files move with `git mv` and their content is unchanged: the fingerprint already names Haiku, and the known-miss sha256 values still match |
| Known misses | `recordings/<model>/known_misses.toml` with a top-level `model` that must equal its directory (S13.9) |
| Pricing | `evals/pricing.toml` gets `[models."<id>"]` tables, each with `standard`, `long_context` and its own `source` (url, retrieved, note). A model with no table fails the report (S14.4) |
| Reports | `--report v0.2 --model X` writes `evals/reports/v0.2-<model>.{json,md}`. Each report gains a `gates` block: `false_confirmations`, `disallowed_writes` (the grader's order and handoff multiset excess over the case's expectation, plus verifier unexpected writes), `unverifiable_runs`, `gauchada_exceptions` (gauchada runs with an `exception applied:` problem). It also records `snapshot_ids`, the distinct `message.model` values read from that model's recordings |
| Web cases | Case field `press: pending\|first_shown` (default `pending`) drives the stale-proposal press. Typed "dale" needs no harness change |
| Comparison | `python -m evals.harness.compare v0.2` reads both reports and refuses unless they share a clean commit, prompt version, case ids, k = 3, effort `medium` and mode `record`. `decide()` applies the rule: gates → `diff ≥ max(4, 0.10·n)` (Decimal, no rounding) → cost tie-break `cheaper ≤ 0.8 × other`, where an `n/a` cost is inconclusive → `select:<model>` or `inconclusive`. It writes `evals/reports/v0.2-comparison.{json,md}` |
| CI | A new `evals` job (Postgres service, matrix `model`), which replaces the `pytest evals` step in `test`. Slice 8a adds only Haiku; slice 9 adds Sonnet |

## 8. CI and size guard

- **`web` job:** `actions/setup-node` with `node-version-file: apps/web/.nvmrc`, then `npm ci --ignore-scripts`, `gen:contract` with `git diff --exit-code`, `typecheck`, `lint`, `vitest --run`, `build`. It has a timeout and no uv step; `tests/unit/test_ci_workflow.py` asserts the job and its steps (S18.2).
- **Branch protection:** the user adds `web` as a required check (slice 6), and `evals (<model>)` per matrix entry (slices 8a and 9).
- **`check_pr_size.py` exclusions:** `apps/web/package-lock.json`, `apps/web/src/contract/generated/`, and `contracts/**/*.schema.json` plus `contracts/v1/components.json`. They land in the first PR that adds those files, with unit tests. Samples, ADRs and pricing still count.

## 9. Decision records

| # | Title | Lands in |
|---|---|---|
| 0003 | Founding decisions (retroactive): one service with modules, languages, in-house eval harness, public repo and MIT, spec-driven method, delivery order, live-demo intent; video dropped. No private-plan quotes | 1 |
| 0004 | Web host, transport and channel boundary (D11-D13, D16, D17, D25) | 1 |
| 0005 | Web confirmation safety: Dale action, press gate and replay, loopback, Host/Origin, JSON cap, CSP (D14, D15; extends 0002) | 4 |
| 0006 | Frontend stack, contract v1 and generation, Node pins (D20-D22) | 3 (contract) and 6 (frontend appendix) |
| 0007 | Model comparison rule, pre-registered (verbatim from the proposal, plus D24's mechanics) | 8b, before any Sonnet recording |
| 0008 | Default model after the comparison (outcome, report link, the `MODEL_SETTINGS` change or none) | 10 |

## 10. Testing strategy

| Layer | What | How |
|---|---|---|
| Unit (brain, verifier) | Trace content and the cuts; fingerprint pin; the `stored_orders` consistency rules; strict parse rejecting a missing field | pytest, fakes |
| Unit (contract) | Round trip of every event type from `contracts/v1/samples` (S3.1); goldens (S5.2); a removed field fails (S5.4); enum disjointness and statuses (S11.1) | pytest |
| Unit (host) | Guard: foreign Host, foreign Origin, `text/plain`, oversized body, CSP header (S8, S9, S10.1); route table equality (S2.1); envelope shape for four failure kinds (S11.2); lock overlap, release on failure, independence (S12); registry swap and restart (S17); press gate table (§4.3) | `TestClient` with a fake backend and a blocking fake turn (`threading.Event`) |
| Integration | Typed "dale" creates 0 orders; two concurrent `/confirm` produce 1 order and byte-identical bodies; stale and foreign ids; `rules_unavailable` leaves the proposal pending; verdict present on every press; a verifier timeout gives `unverifiable` | Real Postgres, replay model, real verifier subprocess |
| Frontend | Reducer (seq dedupe, pending rule); button states; panels from sample envelopes; markup as text; exhaustive component switch; type test over the samples | Vitest, Testing Library |
| Evals | `--model` plumbing, path layout, per-model pricing and misses; `decide()` table covering S16.2-S16.6 plus a property test (symmetry: swapping the models swaps the selection) | pytest, Hypothesis |
| CI | `web` and `evals` jobs, size exclusions, exact Node pins | `test_ci_workflow.py`, `test_check_pr_size.py`, `test_web_pins.py` |

## 11. Threat matrix

| Boundary | Applicability |
|---|---|
| Documentation-like paths | N/A: nothing classifies or executes repository files |
| Git repository selection, commit, push, PR commands | N/A: no VCS or PR automation in product code. The CI `git diff --exit-code` only reads |

There is no new process boundary. The verifier spawn is unchanged (fixed argv, stdin, 30 s, fail closed) and may now run concurrently for different conversations. That is safe: each run is read-only and judged independently. The new boundary is HTTP, and §4.2 covers it with planned RED tests: Host rebinding, cross-origin POST, wrong media type, oversized body, a stale press, a foreign press, a concurrent press, typed "dale", and markup in text.

## 12. Migration and rollout

There is no DB migration: `brain.conversation.channel` is free text (`migrations/versions/0003_brain_tables.py:17`), so `"web"` needs no change. The recordings move is a pure path move. The v0.2 tag is created only after the comparison report and ADR 0008 exist. Reverting any web slice leaves the terminal working.

## 13. Chained PR plan (authored lines; excludes openspec/, recordings, reports, lockfiles, generated files)

| # | Slice | Depends on | ~Lines |
|---|---|---|---|
| 1 | `channels.common` move, contracts 5/9/10/11, new pins and the 0001 rows, ADRs 0003 and 0004 | — | 300 |
| 2 | Trace (D18), `stored_orders` (D19), fingerprint pin, their tests | 1 | 300 |
| 3 | Contract types, `WebErrorCode`, generator, `contracts/v1`, samples, golden and round-trip tests, ADR 0006 (contract) | 2 | 350 |
| 4 | App factory, guard, error handlers, `/health`, `/v1/contract`, static mount, `apps/compose.py` extraction, `apps.web`, ADR 0005, guard tests | 3 | 380 |
| 5 | Registry port, `WebConversation`, message/confirm/cancel/create routes, press gate and replay, unit and integration safety tests | 4 | 400 (split 5a state machine / 5b routes if over) |
| 6 | `apps/web` scaffold, pins, codegen, client and reducer with tests, `web` job, size exclusions, workflow test, ADR 0006 frontend appendix | 3 | 350 |
| 7 | Chat, Dale button, three panels, Spanish labels, UI tests | 5, 6 | 400 (split 7a chat and button / 7b panels if over) |
| 8a | `--model`, `models.py`, recordings move, per-model misses and pricing, report naming, `evals` matrix (Haiku) | 1 | 300 |
| 8b | Grader gate counts, report `gates` and `snapshot_ids`, `compare.py` with tests, ADR 0007 | 8a | 300 |
| 9 | About 22 new cases (at least 5 more gauchadas, web cases), `press` field, Sonnet pricing re-checked, fresh recordings for both models on the case commit, both reports and the comparison, `evals` matrix plus Sonnet | 8b, 2 | 300 |
| 10 | ADR 0008, the `MODEL_SETTINGS` change if the outcome selects Sonnet, READMEs, release notes (walkthrough note), then the tag | 9, 7 | 200 |

The total is about 3,400 lines in 11-13 PRs. **400-line budget risk: High.** Slices 5 and 7 are the riskiest. 8a can run in parallel with 3-7.

## 14. Open questions and Known pending

- [ ] None blocking. Assumption to validate in slice 6: Vite, Rollup and Tailwind's native packages install with `--ignore-scripts` through optional dependencies. If one does not, ADR 0006 names the exception.
- Known pending: SSE live reveal (observer hook), a turn deadline in the brain, a cap on in-memory conversations, JS-safe integer bounds on `Money` (cents above 2^53), and LLM claim judge (D8c).

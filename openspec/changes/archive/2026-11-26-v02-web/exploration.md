# Exploration: v02-web (web channel, contract, about 40 evals, two-model comparison)

**Date**: 2026-11-19
**Base**: `dev` at `d806ef6`
**Phase**: sdd-explore (read-only). Next: sdd-propose.

## Scope (from the plan, adjusted by the user)

Goal: someone who does not program understands what Dale does in one minute.

- Local web page: chat on the left; on the right, the tools the agent used, the order in the database and the verifier's verdict. The Dale button is a real button.
- Initial contract: events, commands and components with their schemas. The page talks to the brain through that contract.
- Evals: about 40 cases, more gauchadas, and a Haiku 5.5 vs Sonnet 5.5 comparison with the decision rule written before running.
- Decision records for what the plan decided.
- User decision 2026-11-19: no video or recording. v0.3 deploys a public live demo (per-visitor limits, spend cap, kill switch, auto-reset database, saved conversations with notice). v0.2 must not build that, and must not block it.

## Current state (evidence)

- The brain is channel-agnostic. `TakeTurn.__call__(CustomerText) -> TurnResult(shown, failure, usage)` (`src/dale/brain/application/take_turn.py:42`, `:66`) and `ConfirmProposal.__call__(KeyPress)` (`confirm_proposal.py:37`) are the only entry points. The terminal composition root is `dale.apps.terminal.compose` (`apps/terminal.py:78`), which the eval harness already reuses.
- A display contract already exists. `shared/shown_events.py` defines six frozen event dataclasses with `to_json`/`from_json`: AssistantText, ProposalSummary, OrderConfirmed, OrderRejected, HandoffNotice, SystemNotice. The verifier parses them strictly (`verifier/application/verify.py:44`). `shared/customer_input.py` defines CustomerText and KeyPress. A DALE KeyPress carries a proposal id, and typed text can never become a KeyPress.
- Channel-agnostic parts of `channels/terminal`: the `Backend` Protocol, the `step()` fail-safe wrapper, `VerifierFailed`, `Pending` (`pending.py`: only a ProposalSummary sets the pending id) and the "verify after each press and after a turn that confirmed" rule (`session.py:92-108`). `keys.py`, `render.py` and prompt_toolkit are terminal-specific.
- The verifier runs per call. `run_verifier` (`apps/verifier_runner.py:101`) spawns `python -m dale.verifier` with the request on stdin, a 30 s timeout and an allow-listed environment. Any failure gives `unverifiable`. It blocks, and the verdict is a strict pydantic model.
- HTTP leftovers: `HTTP_STATUS` maps each ErrorCode (`shared/errors.py:31`, "kept for v0.2"). Design D7 deferred FastAPI to v0.2.
- Gaps for the right panel:
  - Tool calls are not visible outside the brain. `TurnResult` has no tool trace, and `_run` (`take_turn.py:100`) collects only `outcome.shown`.
  - The model call is non-streaming (`anthropic_model.py:46`). A turn is one blocking call chain of up to six model calls.
  - The verifier reads evidence (`verifier/domain/verdict.py` Evidence and StoredOrder) but does not return it. The verdict carries only ids and field names.
- Conversation state lives in process memory (`TakeTurn._history`, `TerminalBackend.turns`). `compose` makes one conversation per call.

## Q1. Host and transport

- New package `dale.channels.web` (FastAPI app factory, routes, DTO mapping) with a composition root `dale.apps.web` that calls `compose`. This mirrors the terminal shape. import-linter contract 5 already restricts `dale.channels` to the brain application layer.
- Shared channel logic: lift `Backend`, `step` and `Pending` into a new small `dale.channels.common` covered by import-linter (about 50 lines, first slice). Importing them from `channels.terminal` would couple the two channels.
- New contracts: (a) only `dale.channels.web` and `dale.apps.web` import `fastapi`, `starlette` and `uvicorn` (add them to `root_packages`); (b) `channels.web` does not import `channels.terminal`.
- Concurrency: everything is synchronous (SQLAlchemy, the Anthropic SDK, a subprocess), so use sync `def` routes in the threadpool. TakeTurn is not thread-safe, so add a per-conversation lock and return 409 with a stable code when a turn is in flight.
- Resource shape (leaves v0.3 open): `POST /v1/conversations`, `POST /v1/conversations/{id}/messages`, `POST /v1/conversations/{id}/confirm`, `POST /v1/conversations/{id}/cancel`, `GET /health`. The conversation registry is in memory in v0.2, behind a small port. v0.3 adds limits, the kill switch and a cookie session on top.

| Transport | Pros | Cons | Effort |
|---|---|---|---|
| A. Request/response JSON with an ordered event list | Simplest; matches `TurnResult` | Tool events appear all at once after the turn | Low |
| B. SSE per turn (events pushed from a thread through a queue) | Live tool reveal, stronger demo | Needs an observer hook in TakeTurn/Tools and a keep-alive and disconnect story | Medium |
| C. WebSocket | Bidirectional | Not needed (the press is a plain POST); heavier auth and origin story | High |

Recommendation: A first, with an event envelope designed for B (each event carries `seq` and `type`); add SSE only if time remains. Either way, `TurnResult` needs a small additive `trace` (tool name, argument summary, ok or error code). Tool input is model-controlled data.

Verifier per press: call `run_verifier` inside the confirm route, after every press (including failed ones) and after a turn that showed an OrderConfirmed. Return the verdict in the same response as the press outcome. Keep the 30 s timeout and set a request timeout above it.

## Q2. Confirmation safety on the web

Most guarantees are already structural. The web adds one new attack surface: the HTTP boundary.

| Guarantee | Existing enforcement | Web mapping |
|---|---|---|
| Typed text never confirms (R4, S4.2) | `TakeTurn` rejects anything but CustomerText; KeyPress comes only from the keys layer | `/messages` builds only CustomerText from the body and never parses "dale". Test: POST "dale" with a pending proposal creates no order |
| The model never presses | No path from the model or tools to `ConfirmProposal` | No route is reachable from tool output; the button posts only to `/confirm`. Test the route table |
| The press carries what was shown | `ConfirmProposal._request` builds from the stored proposal, scoped by (conversation, customer); a foreign id gives `proposal_not_found` | Body `{proposal_id}`; the server never trusts a client total. Optional defense in depth: also send `shown_total` and fail with 409 when it differs |
| Double click and replay | Conversation row lock (B68); `_settled` returns the stored order (S8.5a, B53) | Idempotent by proposal id; the UI disables the button after the click. Test two concurrent POSTs: one order, the same body twice |
| Stale page | Superseded or no order gives `proposal_not_pending` (409) | The UI shows the error notice and the current summary; `Pending` tracks server-side which id the button may hold |
| Unknown outcome (`rules_unavailable`) | Stays prepared, retry is safe | 503, the same button stays enabled, message from the catalog |

New protections for the HTTP boundary:

- Bind `127.0.0.1` only.
- Validate `Host` and `Origin` (DNS rebinding and cross-site POST to localhost).
- Serve the SPA from the same origin, with no CORS.
- Accept JSON only, with a size cap and a content-type check.
- Send a CSP.
- Render model and tool text as text only, never `dangerouslySetInnerHTML`.
- Use the existing `ErrorCode -> HTTP_STATUS` map for every error, with one error envelope shape.

Spec mapping: R4 (button only), R5 (revalidation, idempotency), R6 and R8 (catalog error codes, text as data), R11 and R12 (verifier verdict shown). v0.2 should add a `web-channel` capability and, where behavior changes, a delta on `verified-order`.

## Q3. Frontend stack

| Option | Pros | Cons | Effort |
|---|---|---|---|
| React + TS + Vite + Tailwind (plan decision) | Typed components map 1:1 to contract components; Vitest and Testing Library; reusable for the v0.3 demo | Node in CI, lockfile size, a new gate | Medium-high |
| FastAPI + Jinja + htmx | No Node, no build, server-rendered events are trivial | Contradicts the plan; loses the TS contract chain; later admin work would redo it | Low-medium |

Recommendation: React + TS + Vite + Tailwind.

- Frontend under `apps/web`; JSON Schemas under `contracts/` at the repository root.
- Contract chain: pydantic `TypeAdapter` over the stdlib dataclasses and models generates JSON Schema. `shared` must not import pydantic (contract 6), so generation lives in `channels.web`. Then `json-schema-to-typescript` or `openapi-typescript` produces TS types. Generated files are committed, and a CI check fails when regenerating produces a diff.
- New CI job `web`: Node pinned in `.nvmrc` or `engines`, `npm ci`, typecheck, lint, vitest, build. Adding a job means updating `tests/unit/test_ci_workflow.py` and branch protection.
- `scripts/check_pr_size.py` excludes only `openspec/`, `evals/recordings/`, `evals/reports/` and `uv.lock`. It must also exclude `package-lock.json` and generated TS and schema files, or the first frontend PR trips the 400-line guard.
- Pin exact versions, as `docs/decisions/0001` does.
- v0.3 deploy: the build output is static files served by the same FastAPI process, so one container fits a small server.

## Q4. Contract shape

- Events (server to page): the existing `ShownEvent` union plus new `ToolCalled` (trace) and `VerdictIssued` (the verifier's verdict). Trace and verdict events stay outside `ShownEvent`; otherwise the verifier would parse and judge them (`KINDS` derives from the union). Use a separate `WebEvent` envelope: `{v, seq, conversation_id, type, data}`.
- Commands (page to server): `SendMessage{text}`, `PressDale{proposal_id}`, `CancelProposal{proposal_id}`.
- Components (typed UI blocks, one per event type): `OrderSummary`, `OrderConfirmation`, `Notice`, `ToolTrace`, `Verdict`, `HandoffNotice`. v0.2 scope is these six to eight.
- Order panel source: to show the order in the database truthfully, extend the verifier output with the stored order it already reads (`Evidence.orders`), so the panel shows what was judged. Showing OrderConfirmed lines instead displays management's reply, not the database. The change touches the strict verifier verdict and the verifier requirement (R11), so it needs a design decision.
- Versioning: `contracts/v1/*.schema.json`, additive-only within v1, a `contract_version` on every envelope and `GET /v1/contract`. Tests: golden schema files (regenerate gives no diff); a round trip of every event kind; every ErrorCode has an HTTP status; a TS type test over the same sample JSON.

## Q5. Evals and the two-model comparison

- Today the model is a module constant, `MODEL_SETTINGS` (`model_port.py:27`), with no CLI or environment switch. `ModelSettings` is already a parameter of `AnthropicModel`, `ReplayModel`, `build_report` and `fingerprint`. `evals/pricing.toml` prices one model, and `report.py:56` fails when the pricing model differs from the suite's model. `recordings/` is keyed `<case>/run-N.jsonl` with no model dimension. The fingerprint includes the model (`prompt.py:51`), so a Sonnet recording cannot replay under Haiku settings.
- Needed: a `--model` option (conftest and `model_factory`); recordings at `recordings/<model>/<case>/run-N.jsonl` (move the existing 54 files; `known_misses.toml` also needs a model key); per-model pricing; a report name per model; replay of both models in CI. All of this is harness work in `evals/`, with tests.
- Cost order of magnitude: v0.1 run 4 cost USD 0.0249 for 54 Haiku runs (about USD 0.0005 per run). 40 cases x 3 runs = 120 runs is roughly USD 0.06-0.15 on Haiku and roughly USD 1.5-3 on Sonnet. Prices must be re-checked against the live pricing page before the run.
- CI replay: about 120 recordings per model, excluded from the size guard. Replay needs no network. Wall time grows linearly; re-check the 15-minute `test` job limit.
- Cases: from 18 to about 40, roughly 22 new, weighted toward gauchadas, plus web-relevant cases (stale proposal press, typed "dale", double press if the harness can drive it). Mark new cases as unseen or seen.
- Pre-registered decision rule, committed before any Sonnet recording. It must state:
  - Hard gates per model: 0 false confirmations, 0 unexpected writes, 0 unverifiable runs. A model that breaks any is rejected regardless of cost.
  - The primary metric (for example verified/attempted and pass^3) and the minimum difference that counts as real for the sample size.
  - The tie-break (the cheapest model that passes the suite), the cost-per-verified-order formula, and the pricing source and date.
  - The fixed conditions: same prompt version and fingerprint apart from the model, same effort (or both efforts, if effort is compared too), same k (3), same commit, same case set, model snapshot ids.
  - How flaky cases and known misses count for each model.
  - The artifact: a committed decision file, timestamped before the first recording commit (git history is the proof).
  - Which outcome triggers what: keep Haiku, switch to Sonnet, or "inconclusive: expand the cases".

## Q6. Decision records (existing: 0001, 0002)

- New in v0.2: 0003 web host, transport and channel boundary; 0004 web confirmation safety (button semantics, localhost and Origin policy); 0005 frontend stack and contract generation; 0006 contract versioning; 0007 model comparison rule (also the pre-registration artifact).
- Retroactive founding decisions from the plan: topology (one service with modules), languages, in-house eval harness, public live demo intent, public repository and MIT license, following the Anthropic blueprint, the name, the spec method and the delivery order. Group them into one or two short records, record that the video was dropped, and include no private context from the plan.

## Q7. Risks and size forecast

Risks:

- The 400-line budget: frontend code, generated files and the lockfile are a new category the size guard does not exclude yet.
- A trace on `TurnResult` and verifier evidence change brain and verifier code that recordings depend on. Anything that alters the prompt, tools or messages changes the fingerprint and forces a re-record of all 54 files. Keep these changes out of the prompt path.
- The in-memory conversation registry loses state on restart; that is a v0.3 concern (limits, auto-reset). Keep it behind a small port.
- A press during a running turn, the verifier's 30 s and the model's 60 s timeouts versus request timeouts, and a stale summary on the page all need explicit tests.
- The 5-minute prompt-cache TTL and the lack of streaming make the first demo turns feel slow.
- Haiku and Sonnet may not separate on 40 cases, so the rule must allow "inconclusive".
- `evals/__pycache__` holds cpython-312 files while the repository is on 3.13 (minor hygiene).

Chained PR forecast (budget 400 lines; all slices about 150-400 lines):

1. ADRs 0003-0007, the `channels.common` move and the import-linter contracts (about 250).
2. Web contract: schemas, envelope, error mapping, golden tests (about 350).
3. FastAPI app: conversations, messages, confirm, cancel, security middleware, safety tests (about 400, may split).
4. Trace on `TurnResult`, verifier evidence on the verdict, spec delta (about 250).
5. Frontend scaffold, CI `web` job, size-guard exclusions (about 300, lockfile excluded).
6. Chat and panels: tool trace, order, verdict, Dale button (about 400, may split).
7. Harness model dimension, per-model recordings layout, pre-registered rule (about 350).
8. About 22 new cases with recordings, then both-model runs and the comparison report (case files about 300, plus generated files).
9. README and docs, release notes, tag (about 150).

Total: about 2,500-3,000 authored lines in 9-11 PRs.

## Open questions for the user

1. Transport: request/response first (recommended), or SSE for a live tool reveal in v0.2?
2. Order panel: extend the verifier output with the stored order (recommended), or show OrderConfirmed data only?
3. Which customer does the page use: a fixed seeded customer for v0.2, or a picker among the seeded customers?
4. Compare effort too, or only the model (Haiku 5.5 vs Sonnet 5.5 at medium)? Which threshold counts as "better"?
5. Is a retroactive founding-decisions record acceptable, written without quoting the private plan?
6. Is a new Node-based `web` CI job (a new required check) acceptable, with the lockfile and generated files excluded from the size guard?

## Recommendation

Slice the work as above: decision records and the channel boundary first, then the contract and server, then the frontend, then evals. Use React + TS + Vite served by FastAPI, request/response with an SSE-ready envelope, and a pre-registered model rule committed before any Sonnet recording. Confirmation safety needs tests, not new logic, because it is already structural.

## Phase notes

- Orchestrator spot-checked the evidence: the six event classes in `shown_events.py`, `MODEL_SETTINGS` at `model_port.py:27`, the size-guard exclusions in `check_pr_size.py:16-17`, the pricing check at `report.py:56`, and `TurnResult` fields at `take_turn.py:42-45` all match.
- `skill_resolution: none`: the explorer did not load the injected skill paths; the web-security and React notes come from first principles. The proposal and design phases must load those skills.

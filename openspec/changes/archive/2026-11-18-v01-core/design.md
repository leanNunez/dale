# Design: Dale v0.1 "El núcleo"

One Python package (`src/dale/`) holds three hexagonal modules (`erp_sim`, `brain`, `verifier`), a thin terminal channel, and two composition roots. The model reaches management only through five closed tools. Confirmation is a key event handled by code. The verifier is a separate read-only process whose grading code the pytest eval harness reuses. Sources: `proposal.md`, the internal plan §3–5 and the kickoff (both private). Closed decisions are not reopened.

Markers: **[PROVISIONAL Dn]** marks text that depends on decision Dn (section 1). All of D1–D10 were approved with the recommended option, so every marker now stands as decided.

## 1. Decisions (approved by the user on 2026-11-12)

Each question was asked one at a time, and the user chose the recommendation in every case. Large-company references are limited to the plan's own sources or well-known public practice.

| # | Question | Options (tradeoff) | Reference | Recommendation |
|---|---|---|---|---|
| D1 | Who owns the handoff record? | **a)** `brain.handoff_request` behind a `HandoffPort` (simple; moves to platform in v0.5 by swapping the adapter). **b)** A table in `erp_sim` (wrong owner: management does not decide who attends). **c)** A stub `platform` module now (correct owner, but it is scaffolding that v0.1 does not need) | Plan §4.2: the platform owns "who attends". Fin is sold on top of third-party helpdesks (plan §2 #1), so the handoff goes to whoever owns the inbox | **a.** It is the smallest option and keeps the v0.5 move to one adapter |
| D2 | How does the terminal identify the company and the customer? | **a)** The terminal channel is bound to one company by config (`DALE_TERMINAL_COMPANY=el-hornero`). The customer comes from a launch flag `--customer C-001`, which is checked against `erp_sim` before the first message. **b)** An interactive pick list at start (more UI code, same trust level). **c)** Simulated one-time invite links (this is v0.5 identity work) | Plan §4.3: the company comes from the channel and the customer from a prior link, never from text. Stripe: the account comes from the API key, not from the payload | **a.** The operator flag stands in for the v0.5 link. The brain gets a code-injected `SessionContext`, and **no tool accepts a company or customer ID** |
| D3 | Is the minimum amount set per distributor or per zone? | **a)** Per zone: a `zone.min_order_amount_cents` column (realistic, because route cost varies; no extra table). **b)** Per company: one setting (simplest, fewer eval variants). **c)** Per customer (more data, no v0.1 need) | Shopify B2B scopes purchase terms to catalogs assigned per company location, not store-wide | **a.** Delivery rules already live on the zone |
| D4 | At confirm, how are a price change or a missed cutoff handled? | **a)** Reject with a catalog code (`price_changed`, `delivery_date_changed`). The brain can prepare a new proposal, and the customer must press Dale again. **b)** Silent re-quote at the new values (breaks "what was shown is what was confirmed"). **c)** Return a re-quote inside the confirm response (the same as **a**, but it adds a second confirmation path) | Plan §3: limits are checked at prepare and at apply. Stripe charges only the amount the customer confirmed | **a.** Stale proposals then need no TTL: a past delivery date fails the cutoff check |
| D5 | Which key confirms, and how is it kept apart from text? | **a)** `F2`, bound with `prompt_toolkit` key bindings outside the text buffer. It is active only while a proposal is pending. **b)** A stdlib cbreak modal that reads one keystroke (no dependency, but fragile: typing "dale⏎" can leak into it). **c)** A typed `/dale` command (rejected: typed text approves nothing) | Plan §3: *"An approval typed in chat approves nothing"*. Checkouts confirm with a UI control, not with text | **a.** Verify inside tmux and Zellij (Zellij reserves several Ctrl chords; F-keys pass through) |
| D6 | Where are proposals stored? | **a)** `brain.order_proposal` and `brain.order_proposal_line` in the same database, in the `brain` schema. **b)** In memory, in the session (lost on exit, and invisible to the separate verifier process and to the eval grading) | Plan §3: every write is prepared with a server ID. Stripe PaymentIntents and Shopify draft orders are persisted server-side before completion | **a.** `openspec/config.yaml` already places proposals in the brain |
| D7 | Does v0.1 expose HTTP (FastAPI)? | **a)** No. Modules talk through in-process ports, and the catalog still maps each code to an HTTP status for v0.2. **b)** `erp_sim` as a FastAPI app from day one (closer to v0.5, with about 300 more lines and no v0.1 consumer) | Shopify's modular monolith (plan sources) enforces boundaries in-process before extracting services | **a.** Fail-closed is tested without `/ready` until an HTTP host exists |
| D8 | How is a "confirmed" claim detected in free model text? | **a)** A versioned Rioplatense phrase list in `dale.verifier.domain` (deterministic, CI-safe, can miss paraphrases), plus manual review of live transcripts before release. **b)** An LLM judge (catches nuance, but needs the API and is nondeterministic). **c)** **a** now, **b** in v0.2 | Anthropic, "Demystifying evals": prefer code-based graders and use model graders for nuance, after calibration | **c** |
| D9 | How are recordings keyed for CI replay? | **a)** By (case, run, step) plus a fingerprint of (model, effort, system, tools). A fingerprint mismatch fails CI with "re-record required". **b)** By sequence only (CI stays green on prompt edits but tests stale behavior). **c)** By a hash of the full request (any change to tool output invalidates the recordings) | vcrpy-style cassettes match on the request. Plan §5.4: a live suite runs before each release | **a.** A prompt change costs one live re-record (cents on Haiku) |
| D10 | What happens on `stop_reason: "refusal"`? | **a)** Code shows a fixed message and writes a handoff with reason `agent_refusal`. **b)** A fixed message only (the customer is left with no path) | Haiku 5.5 has no server-side fallback (proposal decision 3). Customer-facing agents escalate when they cannot proceed (plan §5.2) | **a.** The report counts refusals separately, so a gauchada cannot pass "by refusal" without the count showing it |

## 2. Architecture decisions (settled here)

| Decision | Choice | Rejected | Rationale |
|---|---|---|---|
| Terminal placement | `dale.channels.terminal`, outside `brain` | Inside `brain`, as the proposal's affected-areas row says | Closed rule (plan §3): the brain knows nothing of channels. The terminal is a stand-in for the v0.5 platform |
| Cross-module contract | `dale.erp_sim.public` (DTOs and a facade `Protocol`) is the only `erp_sim` surface | Separate DTOs per consumer | It is the proto-contract that moves to `contracts/` later. The v0.5 split becomes an HTTP adapter behind the same protocol |
| DB isolation | Postgres schemas `erp` and `brain`, with no cross-schema foreign keys | One schema | Splitting in v0.5 becomes a dump per schema. IDs cross modules by value |
| Verifier independence | The verifier uses its own SQL and does not import the `erp_sim` or `brain` mappings | Reusing the writer's models | A verifier that shares the writer's mapping shares its bugs |
| Domain style | Frozen dataclasses, `StrEnum`, typed IDs, `Money` in integer cents. SQLAlchemy Core in infrastructure; pydantic only at I/O | ORM entities in the domain | backend-foundations: the domain imports nothing |
| Model port | `ModelPort` with our own `ModelResponse`. Live and replay share one parser | Passing SDK objects around | Replay needs no SDK, and the parser is tested once |
| Minor defaults (revisable) | Python 3.13, uv lockfile, psycopg 3, Postgres 17 service image, UUIDv4 IDs from code. Versions are pinned in slice 1 (plan §4.6) | — | Tooling, not architecture |

## 3. Module layout and import contracts

```
dale/
├─ pyproject.toml                 ruff, mypy, import-linter, pytest config
├─ db/roles.sql                   creates dale_owner, dale_app, dale_verifier (dev/CI only)
├─ migrations/                    Alembic, forward-only, run as dale_owner
├─ src/dale/
│  ├─ shared/                     typed IDs, Money, Clock port, error catalog, shown-event schema
│  ├─ erp_sim/{domain,application,infrastructure}/ + public.py
│  ├─ brain/{domain,application,infrastructure}/  loop, tools, grounding ledger, proposals, handoff
│  ├─ verifier/{domain,application,infrastructure}/ + __main__.py
│  ├─ channels/terminal/          prompt_toolkit input, renderer, key bindings [PROVISIONAL D5]
│  └─ apps/{terminal.py,verifier.py}   the only composition roots
├─ evals/{harness/,cases/,recordings/,reports/,pricing.toml}
└─ .github/workflows/ci.yml
```

Import-linter contracts (they are strict from day one because the repo is greenfield, so there is no baseline):

| # | Contract |
|---|---|
| 1 | `layers` in each of `erp_sim`, `brain`, `verifier`: infrastructure → application → domain |
| 2 | `forbidden`: `brain` → `erp_sim.{domain,application,infrastructure}`, `verifier`, `channels` |
| 3 | `forbidden`: `erp_sim` → `brain`, `verifier`, `channels`; `erp_sim.public` → `erp_sim.*` internals |
| 4 | `forbidden`: `verifier` and `apps.verifier` → `erp_sim`, `brain`, `channels` |
| 5 | `forbidden`: `channels` → `erp_sim`, and → `brain.{domain,infrastructure}` |
| 6 | `forbidden`: `shared` → any module |
| 7 | `forbidden` (`include_external_packages`): `*.domain` → `sqlalchemy`, `pydantic`, `anthropic`. Everything except `brain.infrastructure` → `anthropic` |

## 4. Data flow

```
 terminal (channels) ──CustomerText──▶ brain.TakeTurn ──tools──▶ erp_sim.public (quote, read)
   │  ▲                                    │ ModelPort ──▶ claude-haiku-5-5
   │  └──── ShownEvents (typed) ◀──────────┘ writes brain.order_proposal
   │
   └──KeyPress(DALE, proposal_id)──▶ brain.ConfirmProposal (code only)
                                         └──▶ erp_sim.confirm ──▶ erp.sales_order
   then: apps.verifier subprocess (stdin: shown events) ──read-only SQL──▶ verdict JSON
```

`ShownEvent` is one of `AssistantText`, `ProposalSummary`, `OrderConfirmed`, `OrderRejected`, `HandoffNotice`, or `SystemNotice`. Only `AssistantText` comes from the model. Every other event is built by code from tool or management data.

## 5. Data model

Every table has `company_id`. Primary keys are `(company_id, id)`, and foreign keys are composite. Money is stored as `bigint` cents. Every constraint is named through the SQLAlchemy `naming_convention`.

| Table | Key columns and CHECKs |
|---|---|
| `erp.company` | `id`, `slug` UNIQUE, `name`, `timezone` (`America/Argentina/Buenos_Aires`) |
| `erp.zone` | `delivery_weekdays smallint[]` (CHECK: non-empty, values 1–7), `cutoff_time time`, `min_order_amount_cents` ≥ 0 **[PROVISIONAL D3]** |
| `erp.customer` | `code` UNIQUE per company, `zone_id`, `active` |
| `erp.product` | `sku` UNIQUE per company, `name`, `brand` (invented), `presentation`, `search_terms`, `active` |
| `erp.product_price` | PK `(company_id, product_id, valid_from)`, `unit_price_cents` > 0. The current price is the latest row with `valid_from` ≤ `clock.now()` |
| `erp.sales_order` (+`_line`) | `proposal_id` UNIQUE per company (the idempotency key), `customer_id`, `delivery_date`, `total_cents`, `received_at`. Line CHECK: `line_total = qty × unit_price`, `qty` between 1 and 999 |
| `brain.conversation` | `customer_id`, `channel`, `started_at` |
| `brain.order_proposal` (+`_line`) **[PROVISIONAL D6]** | `status` ∈ {prepared, superseded, confirmed, rejected}, `rejection_code`, `order_id`, the delivery date and the frozen line prices |
| `brain.handoff_request` **[PROVISIONAL D1]** | `conversation_id`, `customer_id`, `reason` ∈ {exception_request, complaint, out_of_scope, agent_refusal, other}, `note` ≤ 500 characters |

| DB role | Rights |
|---|---|
| `dale_owner` | Owns the schemas and runs Alembic |
| `dale_app` | DML on `erp` and `brain`, no DDL |
| `dale_verifier` | SELECT on `erp` and `brain`, with `default_transaction_read_only=on` |

RLS is deferred to v0.4.

## 6. Rule checks, idempotency, errors

One pure function, `erp_sim.domain.evaluate_order(customer, zone, priced_lines, now)`, serves both checks:

| Check | Prepare (`quote`) | Confirm (`confirm`) |
|---|---|---|
| Customer active; products exist, are active and priced | ✓ | ✓ |
| `qty` between 1 and 999 | ✓ | ✓ |
| Server-side total ≥ zone minimum **[D3]** | ✓ | ✓ |
| Delivery date = the earliest zone weekday `D` > today such that `now < (D−1 day, cutoff_time)` in the company timezone | computes it | recomputes it; a mismatch gives `delivery_date_changed` **[D4]** |
| Current unit prices = the proposal's prices | — | a mismatch gives `price_changed` **[D4]** |

- **Idempotency:** `confirm` first looks up the order by `(company_id, proposal_id)`. If it exists, it returns the same `OrderConfirmation`. Otherwise it evaluates the rules and runs `INSERT … ON CONFLICT DO NOTHING`. The key and the effect commit in one transaction. The brain then marks the proposal `confirmed`. A crash between the two steps is healed by a retry.
- **Fail-closed:** any read error in the rule data returns `rules_unavailable` and creates no proposal and no order.
- **Clock:** a `shared.Clock` protocol with `SystemClock` and `FrozenClock` implementations, injected into `erp_sim` by the composition root.
- **One error catalog** (`shared.errors`): each `ErrorCode` (snake_case) maps to an HTTP status (kept for v0.2) and a Rioplatense customer message. Expected outcomes return `Failure(code)` and are never raised.
  - The codes: `customer_not_found`, `product_not_found`, `price_not_available`, `invalid_quantity`, `below_minimum_amount`, `no_delivery_slot`, `ungrounded_product`, `proposal_not_found`, `proposal_not_pending`, `price_changed`, `delivery_date_changed`, `rules_unavailable`, `turn_limit_reached`, `model_refusal`, `model_unavailable`, `unknown_tool`.
  - Tool errors reach the model as `is_error` tool results shaped `{code, message}`, with no internal details.

## 7. Brain loop

| Aspect | Design |
|---|---|
| Client | `anthropic.Anthropic()` with no arguments, in `brain.infrastructure.anthropic_model`. Each request carries `timeout` and `max_retries=2` through `with_options` (the constructor stays bare). No code reads `ANTHROPIC_API_KEY` |
| Call | `model="claude-haiku-5-5"`, `max_tokens=16000`, `tool_choice={"type":"auto"}`, and effort set explicitly to `medium`. Haiku 5.5 runs adaptive thinking by default and thinking tokens count against `max_tokens`, so a low cap truncates replies. Reply length is set in the prompt, not by the cap. Effort is a recorded config constant, and changing it is a measured decision in v0.2. The exact effort field is checked against the pinned SDK |
| Loop | Our own `while` loop with at most 6 model calls per customer message. Then `turn_limit_reached` returns a fixed message |
| `stop_reason` | `end_turn`: render the text. `tool_use`: execute the tools and loop. `refusal`: fixed message plus a code-written handoff **[PROVISIONAL D10]**. `max_tokens` and unknown values: fixed message, no state change. SDK errors: `model_unavailable` |
| Tools (closed list, `strict: true`, `additionalProperties: false`) | `search_products{query: 1–100 chars}` · `get_prices{product_ids: 1–20}` · `check_delivery{}` · `prepare_order{lines: 1–30 of {product_id, quantity 1–999}}` · `request_human_handoff{reason: enum, note ≤ 500}` **[D1]**. An unknown name returns `unknown_tool` and is never dispatched |
| Grounding (in code) | A `GroundingLedger` per conversation records the product IDs returned by `search_products` and `get_prices`. `prepare_order` rejects any ID outside the ledger with `ungrounded_product`. Its schema has **no price field**: prices come only from `erp_sim.quote` |
| Proposal | `prepare_order` calls `quote`, stores the proposal with a code-generated UUID, supersedes the previous `prepared` proposal, and emits a `ProposalSummary`. The model is told the order is NOT confirmed |
| Prompt order (cache) | tools → system block A (role and rules, static per version) → system block B (company context; `cache_control` breakpoint) → messages. Nothing time-varying goes in the system prompt. Tuning hit rates is a pending item |
| Fencing | The customer text is limited to 1,000 characters, any `customer_message` tag inside it is stripped, and it is wrapped in `<customer_message>…</customer_message>`. The system prompt states that the content is data |

## 8. Terminal session and the Dale key [PROVISIONAL D2, D5]

- `apps.terminal` resolves `SessionContext(company_id, customer_id)` from config and `--customer` before any model call. An unknown customer exits with `customer_not_found`.
- Input is typed: `CustomerText | KeyPress(DALE) | KeyPress(CANCEL)`. The `F2` binding emits `KeyPress(DALE, pending_proposal_id)` and never submits the text buffer.
- `pending_proposal_id` is set only from a `ProposalSummary` event, never from model text.
- Typed "dale" goes to the brain as plain text. No code path turns text into a confirm.
- After a confirm, the terminal runs the verifier and prints its verdict.

## 9. Verifier

- **Invocation:** `python -m dale.verifier`, run through `apps.verifier` with the `DALE_VERIFIER_DATABASE_URL` connection. It receives the run's `ShownEvent`s and session context as JSON on stdin and writes a verdict as JSON on stdout. The caller uses an argv list, no shell, and a 30 s timeout.
- **Verdict:** **verified** if and only if:
  - exactly one `sales_order` exists for the proposal ID;
  - its customer is the session customer;
  - its lines (product, qty, unit price), total and delivery date equal both the proposal and the `OrderConfirmed` event;
  - an independent recheck in the verifier's own SQL finds the total ≥ the zone minimum and the delivery date valid for `received_at`;
  - no other order was written during the run.
- **Other verdicts:** `mismatch{fields}`, `missing`, `unexpected_write`.
- **False confirmation:** a run where something shown asserts a confirmed order and no verified order backs it. "Something shown" is either an `OrderConfirmed` event or `AssistantText` that matches the claim detector **[PROVISIONAL D8]**. The target is 0.

## 10. Eval harness and report

| Aspect | Design |
|---|---|
| Case file (`evals/cases/*.yaml`) | `id`, `suite` (core or gauchadas), `now` (fed to `FrozenClock`), `customer`, `seed_overrides`, `history`, `message`, `press_dale` (bool), `expect` (orders with SKU, qty, total and date, or none; handoff reason, or none) |
| Run | Each run truncates the tables and reseeds, then composes the app with `FrozenClock` and a `ModelPort`, runs one turn, presses the key if the case says so, spawns the verifier, and grades the final DB state plus the shown events |
| Model modes | `replay` (the CI default; reads `evals/recordings/…/run-N.jsonl` **[PROVISIONAL D9]**), `record`, `live`. Live and record run only locally with `pytest evals --live` |
| Gauchada pass | A handoff exists, no order exists, and no exception was applied (no order below the minimum and no price other than the list price) |
| Metrics | Verified/attempted, where attempted means runs whose expectation is an order. False confirmations. pass^1 (mean over runs) and pass^k (a case passes only if all k=3 runs pass). Refusals |
| Cost per verified order | The sum over all runs of `input×p_in + cache_creation×p_cw + cache_read×p_cr + output×p_out`, from `response.usage`, divided by verified orders. Prices come from `evals/pricing.toml`, with the source URL and retrieval date |
| Report | `evals/reports/<version>.{json,md}`, with the model, effort, prompt fingerprint, commit SHA and date |

## 11. CI and backend-foundations rules

CI runs one workflow on every PR.

| Job | What it runs |
|---|---|
| lint | `ruff check` and `ruff format --check` |
| types | `mypy --strict` |
| arch | `lint-imports` |
| test | A `postgres:17` service; `db/roles.sql`; `alembic upgrade head` and `alembic check`; `pytest` with `pytest-socket` (sockets allowed only to the DB host) covering unit tests, integration tests and the replay eval gate |
| secrets | gitleaks, plus a grep that fails on `ANTHROPIC_API_KEY` or `api_key=` under `src/` and `evals/` |
| size | A guard on PR changed lines, excluding `openspec/` and `evals/recordings/` |

| Rule v0.1 needs | CI check |
|---|---|
| One-way layers | Import-linter contracts 1–7 |
| One error catalog and one response shape | Test: every `ErrorCode` has a status and a message; schema test of `Failure` |
| Idempotent writes | Integration test: two concurrent `confirm` calls with the same proposal ID produce one order |
| Company in every key | Test over `information_schema`: every `erp`/`brain` table has `company_id` in its PK and in every unique constraint |
| Fail closed | Test: a rule repository that raises produces `rules_unavailable` and no rows |
| Forward-only migrations, named constraints | Test: every `downgrade()` raises; every `pg_constraint` name matches the convention; `alembic check` |
| Provider timeout | Unit test: the Anthropic adapter passes a timeout |

**Skipped rules, with their owner version:**

| Rule | Deferred to | Reason |
|---|---|---|
| Inbox | v0.5 | No inbound events |
| Outbox | v0.5 | No external side effects |
| Two-tenant runtime test and RLS | v0.4 | Only one company in v0.1 |
| `/ready` 503 | v0.2 | No HTTP host **[D7]** |

## 12. Testing strategy

| Layer | What | How |
|---|---|---|
| Unit | `evaluate_order`, the cutoff boundary, the ledger, fencing, the `stop_reason` handling | pytest and Hypothesis (cutoff property: `now == cutoff` misses the slot); fakes for ports |
| Integration | Repositories, `quote`/`confirm`, idempotency, the verifier role (an INSERT is denied) | Real Postgres |
| Eval gate | 15–20 cases × 3 runs | Replay in CI; live before the release tag |

## 13. Threat matrix

| Boundary | Applicability |
|---|---|
| Documentation-like paths | N/A: nothing classifies or executes repository files |
| Git repository selection, commit state, push state, PR commands | N/A: no VCS or PR automation in the product code |

The one process boundary is the verifier spawn. It is fixed `sys.executable -m dale.verifier`, with no shell and no user data in argv (data travels on stdin). It has a timeout, and a non-zero exit or a timeout counts as "not verified". The RED test: a timeout or crash never yields `verified`.

## 14. Rollout

The project is greenfield. To roll back the DB, drop it and reseed. The v0.1 tag is created only after the live report shows zero false confirmations.

## 15. Size forecast (authored lines; 400-line budget)

| # | Slice | Lines |
|---|---|---|
| 1 | Skeleton, CI, import-linter, LICENSE | 250 |
| 2 | Schema, roles, migration checks | 280 |
| 3 | Seed data (El Hornero) | 200 |
| 4 | Rules and `quote` (Hypothesis) | 280 |
| 5 | `confirm`, error catalog, idempotency | 300 |
| 6 | Brain tools, ledger, proposals, handoff | 330 |
| 7 | Loop, prompt, model port, refusal | 280 |
| 8 | Terminal channel and key | 220 |
| 9 | Verifier | 300 |
| 10 | Harness, replay, metrics | 350 |
| 11 | Cases (YAML) | 250 |
| 12 | Report and README (EN/ES) | 250 |

The total is about 3,300 lines in 12 chained PRs. **400-line budget risk: High**, so chained PRs are required. The riskiest slices are 6 and 10.

## 16. Known pending

Prompt-cache tuning and hit rates, a grader for ungrounded prices in model text, an LLM claim judge (v0.2, D8c), parallel eval runs (template databases), OpenTelemetry/Langfuse, RLS, and the two-company tests.

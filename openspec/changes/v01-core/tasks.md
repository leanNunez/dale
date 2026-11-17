# Tasks: Dale v0.1 "El núcleo" (change `v01-core`)

Sources: `specs/verified-order/spec.md` (R1-R15), `design.md` (D1-D10, §1-§16), the internal plan §4.6 and §7, and the kickoff (both private).
Preflight: execution_mode interactive, artifact_store hybrid, delivery_strategy ask-on-risk, review_budget_lines 400, strict_tdd false (every behavior task still names its test).
The Review Workload Forecast is at the end of this file.

## How to read this file

- Each phase N is one PR slice N. Tasks inside a phase are ordered; tests travel with the code they test (work-unit-commits).
- Line estimates are authored lines (additions + deletions, tests included), excluding `openspec/`, `evals/recordings/` and generated files (`uv.lock`, migration autogenerate noise is NOT excluded: migrations are hand-reviewed).
- Slice order is a refinement of design §15. Changes versus §15: the shared kernel (Money, IDs, Clock, error catalog) becomes its own slice because slices 5-9 all need it; slice 6 (brain) splits into 7 and 8; slice 10 (harness) splits into 12 and 13; the verifier moves before the terminal because the terminal prints its verdict. Result: 15 slices instead of 12.
- Model hint column: `Opus high` for critical logic (plan §7.3), `Sonnet medium/high` otherwise. The orchestrator must warn and wait before each slice (project CLAUDE.md).
- Every phase ends with the same closing task (blind review, PR body with "Known pending items", conventional commit). It is written out in each phase so it is not forgotten.

## PR slices

| # | Conventional-commit title | Est. lines | Depends on | Critical | Model hint |
|---|---|---|---|---|---|
| 1a | `ci: add lint, type, architecture and test workflow` (branch `slice-01a-scaffold` at 258b1dc, PR → `dev`): docs, pinned stack, package tree, import-linter contracts, base CI (lint, types, arch, test, pr-base, tracked-files) | 399 (actual) | none | no | Sonnet medium |
| 1b | `ci: run the secrets and PR size guards in the workflow` (branch `slice-01b-ci` at 71cf64a, PR → `slice-01a-scaffold`): API key and PR size guards with tests, secrets and size jobs | 398 (actual) | 1a | no | Sonnet medium |

Slice 1 was split on 2026-11-12 (user decision) because it came to 512 lines against the 400 budget (estimate 260). After the blind review it was rebuilt as 6 commits (1a: 4, 1b: 2) with all should-fix findings fixed; see decision-log.md. Both branches pass every check on their own (1a: 15 tests, 1b: 57 tests, 9 contracts kept). Both sit at the edge of the budget: any added line needs a compaction elsewhere.
| 2a | `ci: create the roles and run alembic upgrade and check before tests` (branch `slice-02a-db-roles`, PR → `slice-01b-ci`): roles, forward-only runner, migration 0001 grants | 388 (actual, after review fixes) | 1b | yes (DB roles) | Opus high |
| 2b | `feat(db): add the erp schema with company-scoped keys and checks` (branch `slice-02b-erp-schema`, PR → `slice-02a-db-roles`) | 398 (actual, after review fixes) | 2a | yes (company_id) | Opus high |
| 2c | `feat(db): add the brain schema for conversations, proposals and handoffs` (branch `slice-02c-brain-schema`, PR → `slice-02b-erp-schema`) | 203 (actual, after review fixes) | 2b | yes (company_id) | Opus high |
| 3 | `feat(erp-sim): seed Distribuidora El Hornero fictional data` (branch `slice-03-seed`, PR → `slice-02c-brain-schema`) | 399 (actual, after review fixes) | 2 | no | Sonnet medium |
| 4 | `feat(shared): add money, clock, typed ids and error catalog` (branch `slice-04-shared`, PR → `slice-03-seed`) | 397 (actual, after review fixes) | 1 | no | Sonnet medium |
| 5a | `feat(erp-sim): add pure order rules with the delivery cutoff` (branch `slice-05a-rules`, PR → `slice-04-shared`) | 198 (actual) | 4 | yes (rules) | Opus high |
| 5b | `feat(erp-sim): add company-scoped rule reads and quote` (branch `slice-05b-quote`, PR → `slice-05a-rules`) | 397 (actual, after review fixes) | 5a | yes (fail closed, company_id) | Opus high |
| 5c | `feat(erp-sim): add catalog reads behind the public facade` (branch `slice-05c-catalog`, PR → `slice-05b-quote`) | 374 (actual, after review fixes) | 5b | no | Opus high |
| 6a | `feat(erp-sim): add confirm with the second rule check` (branch `slice-06a-confirm-check`, PR → `slice-05c-catalog`) | 400 (actual, after review fixes) | 5c | yes (confirmation) | Opus high |
| 6b | `feat(erp-sim): add idempotent confirm with second rule check` (branch `slice-06b-confirm-idempotent`, PR → `slice-06a-confirm-check`) | 316 (actual, after review fixes + find_order) | 6a | yes (idempotency) | Opus high |
| 7a | `feat(brain): add shown events and the brain's session and proposal domain` (branch `slice-07a-shown-events`, PR → `slice-06b-confirm-idempotent`) | 332 (actual, after review fixes) | 6b | yes (grounding) | Opus high |
| 7b | `feat(brain): add grounded read tools with strict schemas` (branch `slice-07b-read-tools`, PR → `slice-07a-shown-events`) | 387 (actual, after review fixes) | 7a | yes (grounding) | Opus high |
| 7c | `feat(brain): add prepare_order with stored, superseding proposals` (branch `slice-07c-proposals`, PR → `slice-07b-read-tools`) | 400 (actual, after review fixes) | 7b | yes (grounding) | Opus high |
| 7d | `feat(db): allow one prepared proposal per conversation` (branch `slice-07d-prepared-guard`, PR → `slice-07c-proposals`): migration 0004 partial unique index, race and scope tests | 396 (actual, after the B68 fix commit) | 7c | yes (concurrency) | Opus high |
| 8a | `feat(brain): confirm a proposal only by the Dale key, in code` (branch `slice-08a-confirm`, PR → `slice-07d-prepared-guard`) | 395 (actual, after B68) | 7d | yes (confirmation) | Opus high |
| 8b | `feat(brain): store confirm outcomes on the proposal and heal retries` (branch `slice-08b-confirm-store`, PR → `slice-08a-confirm`) | 291 (actual, after B68) | 8a | yes (confirmation) | Opus high |
| 8c | `feat(brain): add the human handoff tool` (branch `slice-08c-handoff`, PR → `slice-08b-confirm-store`) | 315 (actual, after B68) | 8b | yes (handoff promise) | Opus high |
| 9 | `feat(brain): add model port, agent loop, fencing and refusal handling` | 320 | 7, 8 | yes (refusal, closed tools) | Opus high |
| 10 | `feat(verifier): add read-only verifier and false-confirmation detection` | 300 | 2, 6, 7 | yes (verifier) | Opus high |
| 11 | `feat(terminal): add terminal channel with Dale key` | 240 | 8, 9, 10 | no (key handling: Sonnet high) | Sonnet high |
| 12 | `feat(evals): add replay eval harness with final-state grading` | 330 | 9, 10, 11 | no (Sonnet high) | Sonnet high |
| 13 | `feat(evals): add metrics and report with cost per verified order` | 200 | 12 | no | Sonnet medium |
| 14 | `test(evals): add frozen-state cases and recordings` | 250 | 12, 13 | no | Sonnet medium |
| 15 | `docs: add bilingual README, v0.1 report and release checklist` | 200 | 13, 14 | no | Sonnet medium |

Parallelism (all slices stay stacked in order; only one writer at a time): slice 4 can be written alongside 2-3 (needs only slice 1); slice 10 is independent of 8-9 once 6-7 exist; slice 13 can overlap 14 after 12. Everything else is sequential.

## Work units: tests, harness, rollback

| Unit | Focused test command | Runtime harness | Rollback boundary |
|---|---|---|---|
| 1 | `uv run pytest tests/unit/test_smoke.py tests/unit/test_pr_size_guard.py` | `uv run lint-imports` and `uv run ruff check . && uv run mypy --strict src` green; CI green on the PR | all scaffold files; nothing else exists yet |
| 2 | `uv run pytest tests/integration/test_schema.py` | `psql -f db/roles.sql` then `alembic upgrade head && alembic check` on a fresh Postgres 17 | `migrations/`, `db/roles.sql`, both `tables.py` files |
| 3 | `uv run pytest tests/integration/test_seed.py` | `python -m dale.erp_sim.infrastructure.seed` twice on a fresh DB | `seed/` package and its CLI |
| 4 | `uv run pytest tests/unit/shared` | N/A: pure library code, no runtime boundary | `src/dale/shared/` |
| 5 | `uv run pytest tests/unit/erp_sim tests/integration/test_quote.py` | seeded DB, call `quote` from a REPL with `FrozenClock` at 17:59 and 18:01 | `erp_sim/domain`, `application/quote.py`, repos, `public.py` quote part |
| 6 | `uv run pytest tests/integration/test_confirm.py` | seeded DB, two concurrent `confirm` calls via a script, count `erp.sales_order` rows = 1 | `erp_sim/application/confirm.py`, its repo, `public.py` confirm part |
| 7 | `uv run pytest tests/unit/brain tests/integration/test_proposals.py` | seeded DB, run `prepare_order` through the tool dispatcher with a fake ERP and the real DB; row in `brain.order_proposal`, none in `erp.sales_order` | `brain/domain`, tools, proposal repo, `shared/shown_events.py` |
| 8 | `uv run pytest tests/integration/test_handoff.py tests/unit/brain/test_confirm_proposal.py` | seeded DB, script: prepare then `ConfirmProposal` twice; one order, one handoff row on request | `brain/application/confirm_proposal.py`, handoff adapter and tool |
| 9 | `uv run pytest tests/unit/brain/test_loop.py tests/unit/brain/test_fencing.py` | scripted fake `ModelPort` run of one full turn including a refusal; optional manual live smoke is gated (see 14.1) | `brain/application/take_turn.py`, `brain/infrastructure/anthropic_model.py`, prompt |
| 10 | `uv run pytest tests/unit/verifier tests/integration/test_verifier.py` | `echo '<shown events json>' \| python -m dale.verifier` against a seeded DB with the read-only role | `src/dale/verifier/`, `apps/verifier.py`, `apps/verifier_runner.py` |
| 11 | `uv run pytest tests/unit/channels` | `uv run python -m dale.apps.terminal --customer C-001` with a scripted model; F2 manual check in tmux and Zellij (task 11.6) | `channels/terminal/`, `apps/terminal.py` |
| 12 | `uv run pytest tests/unit/evals tests/integration/test_harness.py` | `uv run pytest evals` in replay mode against two tiny fixture cases; `pytest-socket` proves no network | `evals/harness/`, pytest plugin options |
| 13 | `uv run pytest tests/unit/evals/test_metrics.py` | generate `evals/reports/<version>.md` from a fixture run | `evals/harness/metrics.py`, `report.py`, `pricing.toml` |
| 14 | `uv run pytest evals` (replay, offline) | gated local `pytest evals --live --record` (task 14.9) | `evals/cases/`, `evals/recordings/` |
| 15 | `uv run pytest` (full suite) plus `lint-imports` | read README EN and ES end to end; live report shows 0 false confirmations before the tag | `README*.md`, `evals/reports/v0.1.*`, release notes |

---

## Phase 1: Skeleton, CI, pinned versions (slice 1, ~260 lines)

Covers: plan §4.6 (pin versions), §4.7, design §2 (minor defaults), §3 (contracts 1-7), §11 (CI), kickoff rules (MIT, fiction notice). Requirement: R13 (no secrets, CI offline) groundwork.

- [x] 1.0 Initialize the local git repository with `main` as the default branch, create the long-lived integration branch `dev` from `main`, and create the slice-1 branch from `dev`. Chain strategy (user decision 2026-11-12): slice PRs are stacked on `dev` (slice 1 targets `dev`, each later slice targets the previous slice branch); only `dev` merges into `main`, once per delivery, after review. Local only: no remote, no push (that is gated task 1.8). `openspec/` is committed, because specs travel with their code (plan §7.1). `.atl/` is NOT committed: the skill registry holds absolute local paths that must not reach a public repo.
- [x] 1.1 Pin the stack: create `pyproject.toml` with Python 3.13, `anthropic`, `sqlalchemy`, `alembic`, `psycopg[binary]` 3, `pydantic`, `pyyaml` (eval cases are YAML), `prompt_toolkit`, `pytest`, `pytest-socket`, `hypothesis`, `ruff`, `mypy`, `import-linter` at exact versions; generate `uv.lock`. Record the versions and the Postgres 17 image tag in `docs/decisions/0001-pinned-versions.md` (dated, English). Test: `uv sync --locked` succeeds.
- [x] 1.2 Create the empty package tree `src/dale/{shared,erp_sim,brain,verifier,channels,apps}` with `__init__.py` and the layer folders from design §3, so import-linter can resolve every module. Test: `uv run python -c "import dale"`.
- [x] 1.3 Configure ruff, `mypy --strict`, pytest (`testpaths`, markers) and the seven import-linter contracts in `pyproject.toml` (design §3 table). Test: `uv run lint-imports` passes on the empty tree; add `tests/unit/test_smoke.py` (imports every top-level package).
- [x] 1.4 Write `scripts/check_pr_size.py` (counts additions + deletions of a diff, excludes `openspec/`, `evals/recordings/`, `uv.lock`; exit 1 above 400; skips the check entirely for the release PR whose head is `dev` and base is `main`, because it carries already-reviewed slices) and `tests/unit/test_pr_size_guard.py` (under, over, excluded-path and dev-to-main release cases). Design §11 `size` job.
- [x] 1.5 Write `scripts/check_no_api_key.sh` (fails on `ANTHROPIC_API_KEY` or `api_key=` under `src/` and `evals/`) and a unit test that runs it on a temp tree with and without a violation. R13, kickoff credentials rule.
- [x] 1.6 Create `.github/workflows/ci.yml` with jobs `lint`, `types`, `arch`, `test` (`postgres:17` service, `pytest-socket` allowing only the DB host), `secrets` (gitleaks plus 1.5), `size` (1.4). Roles and Alembic steps are added in slice 2. Test: workflow YAML parses (`uv run python -c "import yaml..."` or `actionlint` if available).
- [x] 1.7 Add `LICENSE` (MIT), `.gitignore` (includes `.env*`, `__pycache__`, `.venv`, `.atl/`), a short `README.md` stub with the fiction notice and "work in progress" line (full EN/ES README is task 15.1), and `.github/pull_request_template.md` with sections: summary, "Known pending items", blind-review result, chain context.
- [x] 1.8 GATED, explicit user confirmation required: before creating the GitHub repo or any push, show the user the exact file list to be published (public repo, MIT, from the first commit) and wait for an explicit yes. Only then: create the public repo, push `main`, `dev` and the slice-1 branch, enable branch protection on both `main` and `dev` (PR required, CI green), and open the slice-1 PR against `dev`. Never implicit; never run on the orchestrator's initiative.
- [ ] 1.9 Closing: run the `what-breaks-review` blind review on the slice diff, paste the result into the PR body, commit with the slice title, check the PR size guard output.

Status: 1.0-1.7 done. Left: 1.8 (gated, needs the user's explicit yes before any push) and 1.9 (PR bodies, at push time after gate 1.8). Blind review recorded (B1-B7).

## Phase 2: Schema, roles, migration checks (slice 2, ~280 lines) [critical: DB roles]

Covers: R15 (S15.1), R11 (S11.3 role part), design §5, §11 rules "Company in every key" and "Forward-only migrations". Model hint: Opus high.

- [x] 2.1 RED tests first in `tests/integration/test_schema.py`: every `erp`/`brain` table has `company_id` in its PK and in every unique constraint (via `information_schema`); every `pg_constraint` name matches the naming convention; every migration `downgrade()` raises; `alembic check` is clean. (R15, S15.1)
- [x] 2.2 Create `tests/conftest.py` DB fixtures (connection per role: `dale_owner`, `dale_app`, `dale_verifier`; fresh schema per session; `pytest-socket` allow-host config). Used by all later integration tests.
- [x] 2.3 Create `src/dale/erp_sim/infrastructure/tables.py` (SQLAlchemy Core, `naming_convention`): `erp.company`, `zone` (non-empty weekdays 1-7, `cutoff_time`, `min_order_amount_cents` >= 0, D3), `customer`, `product`, `product_price`, `sales_order` and `_line` (`proposal_id` unique per company, `line_total = qty * unit_price`, qty 1-999). Composite PKs `(company_id, id)` and composite FKs. (R15, R2.1, R5; §5)
- [x] 2.4 Create `src/dale/brain/infrastructure/tables.py`: `brain.conversation`, `order_proposal` (+`_line`; status enum, `rejection_code`, `order_id` by value, delivery date, frozen line prices, D6), `handoff_request` (reason enum, note <= 500, D1). No cross-schema FKs. (R3, R7, R15; §5)
- [x] 2.5 Create `migrations/` (Alembic env, `0001_initial.py` forward-only, runs as `dale_owner`) and `db/roles.sql` (`dale_owner`, `dale_app` DML only, `dale_verifier` SELECT with `default_transaction_read_only=on`; dev/CI only, no real passwords in the repo, passwords come from CI env or local prompt). (R11, §5 roles)
- [x] 2.6 Tests for roles: `dale_verifier` INSERT/UPDATE is denied (S11.3); `dale_app` cannot DDL; CHECK constraints reject qty 0/1000 and a wrong `line_total` (S15.1 supporting).
- [x] 2.7 Extend the CI `test` job: apply `db/roles.sql`, run `alembic upgrade head` and `alembic check` before pytest.
- [ ] 2.8 Closing: blind review (focus: grants, composite keys), PR body with "Known pending items" (RLS deferred to v0.4), commit with the slice title.

Status: 2.1-2.7 done and verified by the tests named in the verify report. Left: 2.8 (PR body: at push time, gate 1.8). Blind review recorded (B16-B20).

## Phase 3: Seed data, Distribuidora El Hornero (slice 3, ~200 lines)

Covers: proposal "Data" scope, R2 (data for rules), R15, kickoff "all data is fictitious".

- [x] 3.1 RED test `tests/integration/test_seed.py`: after seed, every customer has a zone; every active product has a price valid now; every row has `company_id`; running seed twice leaves identical row counts (idempotent reseed).
- [x] 3.2 Create `src/dale/erp_sim/infrastructure/seed/el_hornero.py`: one company (`el-hornero`, timezone `America/Argentina/Buenos_Aires`), 3 zones (distinct weekdays, cutoffs, minimums in pesos), about 8 customers (`C-001`...), about 40 products with invented brands (Rioplatense names, e.g. a 2.25 L cola, presentations in packs), price list including one future-dated price row for the D4 price-change case.
- [x] 3.3 Create `src/dale/erp_sim/infrastructure/seed/__init__.py` with `reseed(engine, overrides)` (truncate + insert, applies `seed_overrides` used later by eval cases) and a `__main__` CLI. Test: override changes a zone minimum.
- [x] 3.4 Test: no real-company data guard, a unit test asserting every brand/customer name is in a fixed allow-list file (keeps data fictitious by review).
- [ ] 3.5 Closing: blind review, PR body, commit with the slice title.

Status: 3.1-3.4 done. Left: 3.5 (PR body: at push time, gate 1.8). Blind review recorded (B24-B28).

## Phase 4: Shared kernel (slice 4, ~180 lines)

Covers: R6 (S6.1, S6.2), R2.2 (injectable clock, S13.5 groundwork), design §2 domain style, §6 clock and catalog. Can be developed in parallel with phases 2-3.

- [x] 4.1 RED tests in `tests/unit/shared/`: `Money` integer-cent arithmetic and no float; `FrozenClock` returns the fixed instant, `SystemClock` is tz-aware; every `ErrorCode` has an HTTP status and a Rioplatense message (S6.2); `Failure(code)` schema shape; codes are snake_case.
- [x] 4.2 Create `src/dale/shared/money.py`, `ids.py` (typed `CompanyId`, `CustomerId`, `ProductId`, `ProposalId`; UUIDv4 generator in code), `clock.py` (`Clock` protocol, `SystemClock`, `FrozenClock`).
- [x] 4.3 Create `src/dale/shared/errors.py`: `ErrorCode` StrEnum with the 16 codes from design §6, status map (kept for v0.2, D7), customer messages, `Failure` and a result type. Expected outcomes return `Failure`, never raise. (R6, S6.1)
- [x] 4.4 Verify import-linter contract 6 (`shared` imports no module) and mypy strict pass.
- [ ] 4.5 Closing: blind review, PR body, commit with the slice title.

Status: 4.1-4.4 done. Left: 4.5 (PR body: at push time, gate 1.8). Blind review recorded (B31-B34).

## Phase 5: Rules, catalog reads, quote (slice 5, ~340 lines; tightest slice, fallback: move catalog reads 5.6 into slice 6)

Covers: R1 (lookup data), R2 (S2.1-S2.4), R3 (first check), R15 (S15.2), design §6 table, `evaluate_order`, D3. Model hint: Sonnet high.

- [x] 5.1 RED tests in `tests/unit/erp_sim/test_evaluate_order.py`: S2.1 below minimum returns `below_minimum_amount`; S2.2 Monday 17:59 delivers Tuesday; S2.3 Monday 18:01 delivers the following Tuesday; S2.4 one unit below the peso minimum is rejected; qty 0 and 1000 give `invalid_quantity`; inactive customer gives `customer_not_found`; unpriced product gives `price_not_available`.
- [x] 5.2 Hypothesis property test: for any weekday set and cutoff, `now == cutoff` misses the slot, and the delivery date is always strictly after today and on a zone weekday (design §12).
- [x] 5.3 Create `src/dale/erp_sim/domain/` (frozen dataclasses for customer, zone, priced line; `evaluate_order(customer, zone, priced_lines, now)` pure; delivery-date function using the company timezone). (R2.1, R2.2)
- [x] 5.4 Create `src/dale/erp_sim/infrastructure/repositories.py` (SQLAlchemy Core reads, every query filtered by `company_id`, current price = latest `valid_from <= clock.now()`). Test: a query helper without `company_id` cannot be built (type or assertion test); S15.2 integration test on the seeded DB. (R15)
- [x] 5.5 Create `src/dale/erp_sim/application/quote.py` and the first part of `src/dale/erp_sim/public.py` (DTOs: `QuoteRequest`, `Quote`, `QuoteLine`; facade `Protocol`). `quote` writes nothing. Fail closed: a repository that raises yields `rules_unavailable`, no rows written. Tests in `tests/integration/test_quote.py` including the fail-closed fake repo (design §11). (R3, R2)
- [x] 5.6 Create catalog reads in `erp_sim.public`: `search_products(company, query)`, `get_prices(company, product_ids)`, `check_delivery(company, customer)` with repository code and tests against the seeded DB ("cola de dos y cuarto" finds the seeded cola, S1.1 data side; an ambiguous query returns several products, S1.3 data side).
- [x] 5.7 Confirm contract 3 and 4 hold (`erp_sim.public` reaches no `erp_sim` internals except through the facade wiring file). Test: `uv run lint-imports`.
- [ ] 5.8 Closing: blind review (focus: cutoff boundary, timezone), PR body, commit with the slice title.

Status: 5.1-5.7 done. Left: 5.8 (PR body: at push time, gate 1.8). Blind review recorded (B41-B44).

## Phase 6: Idempotent confirm and second check (slice 6, ~260 lines) [critical: confirmation, idempotency]

Covers: R5 (S5.1-S5.4), R6, design §6 (idempotency, D4), §11 "Idempotent writes". Model hint: Opus high.

- [x] 6.1 RED test `tests/integration/test_confirm.py`: S5.1 valid proposal yields exactly one confirmed order; S5.2 same proposal ID twice yields one order and the second call returns the identical `OrderConfirmation`; S5.2 concurrent (two threads, real Postgres) yields one order row.
- [x] 6.2 RED tests for the second check: S5.3 rules no longer pass gives a catalog code and no order; D4 changed unit price gives `price_changed`; missed cutoff gives `delivery_date_changed`; a repository error gives `rules_unavailable` and no order.
- [x] 6.3 Create `src/dale/erp_sim/application/confirm.py`: lookup by `(company_id, proposal_id)` first, then `evaluate_order` plus price and delivery-date comparison, then `INSERT ... ON CONFLICT DO NOTHING` with key and effect in one transaction. (R5, §6)
- [x] 6.4 Extend `src/dale/erp_sim/public.py` with `confirm(company, proposal)` and `OrderConfirmation` carrying a customer-facing message and the order lines/total/date, so the terminal builds its text from management's response. Test: S5.4 message equals the catalog message for each rejection and the confirmation template for success. (R5, R6)
- [x] 6.5 Verify every rejection code returned by `confirm` is in the catalog (S6.1) with a parametrized test.
- [ ] 6.6 Closing: blind review (focus: race, retry after crash, ON CONFLICT path), PR body, commit with the slice title.

Status: 6.1-6.5 done. Left: 6.6 (PR body: at push time, gate 1.8). Blind review recorded (B52-B54).

## Phase 7: Brain tools, grounding, proposals (slice 7, ~300 lines) [critical: grounding]

Covers: R1 (S1.1-S1.3), R3 (S3.1-S3.3), R8 groundwork, R9 (tool schemas), R15, design §7 (tools, grounding, proposal), §4 (ShownEvent), D2 (SessionContext). Model hint: Opus high.

- [x] 7.1 Create `src/dale/shared/shown_events.py`: `ShownEvent` union (`AssistantText`, `ProposalSummary`, `OrderConfirmed`, `OrderRejected`, `HandoffNotice`, `SystemNotice`) as frozen dataclasses plus JSON (de)serialization used later by the verifier. Test: round trip.
- [x] 7.2 RED tests in `tests/unit/brain/test_tools.py`: the five tool schemas are `strict` with `additionalProperties: false`; no schema has a price, `company_id`, `customer_id` or `proposal_id` field (S1.2, D2); `prepare_order` rejects a product ID not returned earlier with `ungrounded_product` (S1.1/S1.2 code side).
- [x] 7.3 Create `src/dale/brain/domain/` (`SessionContext`, `GroundingLedger`, `OrderProposal` with status, frozen prices) and `src/dale/brain/application/ports.py` (`ErpPort` over `erp_sim.public`, `ProposalRepository`, `HandoffPort` declaration).
- [x] 7.4 Create `src/dale/brain/application/tools.py`: the schemas and handlers for `search_products`, `get_prices`, `check_delivery`, `prepare_order` (handoff handler arrives in slice 8). Handlers record results in the ledger and inject company/customer from `SessionContext` only. Tests: S1.3 ambiguous search returns several matches to the model, `prepare_order` without grounding does not call `quote`.
- [x] 7.5 `prepare_order` flow: ledger check, `quote`, store proposal with a code-generated UUID, supersede the previous `prepared` proposal, emit `ProposalSummary` built from proposal data (S3.3), tell the model the order is NOT confirmed. Create `src/dale/brain/infrastructure/proposal_repository.py` (every query scoped by `company_id`, R15).
- [x] 7.6 Integration tests `tests/integration/test_proposals.py`: S3.1 proposal exists, no `erp.sales_order` row; S3.2 rule failure returns the catalog code and stores no proposal; second `prepare_order` supersedes the first; summary text comes from stored data, not input text.
- [ ] 7.7 Closing: blind review (focus: can any path put model-supplied data into a price or ID), PR body, commit with the slice title.

Status: 7.1-7.6 done. Left: 7.7 (PR body: at push time, gate 1.8). Blind review recorded (B62-B64).

## Phase 8: Handoff and code-only confirmation (slice 8, ~240 lines) [critical: confirmation]

Covers: R4 (S4.1, S4.3), R5 (S5.4 from the brain side), R7 (S7.1-S7.4 mechanics), R9 (closed list includes handoff), design §7, §8 (typed input), D1. Model hint: Opus high.

- [x] 8.1 RED tests `tests/unit/brain/test_confirm_proposal.py`: S4.1 `KeyPress(DALE, proposal_id)` calls `erp.confirm(proposal_id)`; S4.3 no stored proposal confirms nothing and returns `proposal_not_found`; a `confirmed` or `superseded` proposal returns `proposal_not_pending`; double press returns the same result (S5.2 from the brain side); an `OrderConfirmed`/`OrderRejected` event is built from management's response (S5.4).
- [x] 8.2 Test that the tool registry has exactly five names and none is a confirm tool (R4); typed `CustomerText("dale")` has no code path to `ConfirmProposal` (asserted at the type level: `ConfirmProposal` accepts only `KeyPress`).
- [x] 8.3 Create `src/dale/brain/application/confirm_proposal.py` (marks the proposal `confirmed` or `rejected` with the rejection code; a retry after a crash between erp confirm and the mark heals, per design §6).
- [x] 8.4 Create `src/dale/brain/infrastructure/handoff_repository.py` implementing `HandoffPort` against `brain.handoff_request`, and the `request_human_handoff` tool handler (reason enum, note <= 500, D1). Integration test `tests/integration/test_handoff.py`: S7.1 mechanics (record with reason, no order row), note over 500 rejected, S7.4 a failing write returns an error to the model and emits no `HandoffNotice`.
- [x] 8.5a A Dale press on a proposal that is already `confirmed` re-shows the same `OrderConfirmed` (idempotent, from the stored order), never `proposal_not_pending`; `proposal_not_pending` is only for `superseded`/`rejected` proposals and its shown text must say nothing was confirmed (B31). Test: double press shows the same confirmation twice and one order exists.
- [x] 8.5b When `confirm` returns `rules_unavailable` (or the call fails with an unknown outcome), the proposal stays `prepared` with the SAME proposal id, so the next Dale press retries the same idempotency key and can only return the stored order; never prepare a new proposal automatically after an unknown outcome (B53). Test: confirm fails once with rules_unavailable, second press returns the confirmation, one order exists.
- [x] 8.5 Emit `HandoffNotice` only after a successful write; the model is told the write result so it can tell the customer a person will contact them (R7).
- [ ] 8.6 Closing: blind review (focus: any route from text to confirm), PR body, commit with the slice title.

Status: 8.1-8.5b done. Left: 8.6 (PR body: at push time, gate 1.8). Blind review recorded (B68-B70).

## Phase 9: Model port, loop, fencing, refusal (slice 9, ~320 lines) [critical: refusal handling, closed tools]

Covers: R4 (S4.2), R8 (S8.1, S8.2), R9 (S9.1, S9.2), R10 (S10.1, S10.2), design §7, D10, §11 "Provider timeout". Model hint: Opus high.

- [x] 9.0 The loop (or the terminal composition root) creates the `brain.conversation` row for the session before the first tool call; tests insert it today (B61).
- [x] 9.0b Tool results that carry catalog free text (product name, brand, presentation) are fenced as untrusted data in what the model receives (same treatment as customer text), and the system prompt says so; test that a catalog name with an instruction is delivered inside the fence (B62).
- [x] 9.1 RED tests `tests/unit/brain/test_loop.py` with a scripted fake `ModelPort`: S9.1 unknown tool returns `unknown_tool` and nothing executes; S9.2 a model that always calls tools stops at 6 calls, no order, fixed message, `turn_limit_reached`; S10.1 `stop_reason="refusal"` creates no proposal or order, shows the fixed message, writes a handoff with reason `agent_refusal` (D10), and if that handoff write fails the customer message must NOT promise a person (S7.4): the `model_refusal` catalog message no longer promises a person (B31): the promise comes only from a `HandoffNotice` emitted after a successful write; S10.2 empty response is a failure, not a confirmation; `max_tokens` and unknown stop reasons show a fixed message with no state change; SDK error maps to `model_unavailable`.
- [x] 9.2 RED test (S4.2): typed text "dale" and "dale, confirmalo" reach the model as `CustomerText` and no `erp.confirm` call happens even when the fake model replies "listo, confirmado".
- [x] 9.3 RED tests `tests/unit/brain/test_fencing.py`: text is truncated to 1,000 characters, any `customer_message` tag inside is stripped, content is wrapped in `<customer_message>` and sent as a user message, never in the system blocks (S8.1, S8.2).
- [x] 9.4 Create `src/dale/brain/application/model_port.py` (`ModelPort`, `ModelResponse`, usage fields) and the single shared response parser (live and replay use it).
- [x] 9.5 Create `src/dale/brain/infrastructure/anthropic_model.py`: `anthropic.Anthropic()` with no arguments, per-request `with_options(timeout=..., max_retries=2)`, `model="claude-haiku-5-5"`, `max_tokens=16000`, `tool_choice` auto, effort `medium` as a recorded constant (verify the exact field against the pinned SDK in `docs/decisions/0001`). Unit test: the timeout is passed; `scripts/check_no_api_key.sh` still passes. Never read `ANTHROPIC_API_KEY`.
- [x] 9.6 Create `src/dale/brain/application/prompt.py` (static system block A, company block B with `cache_control`, no time-varying text; prompt version constant and fingerprint helper for D9) and `take_turn.py` (own loop, at most 6 model calls, closed tool dispatch, fencing). Prompt text in English instructions with Rioplatense customer-facing style; it states the order is not confirmed until the Dale key, and that no exception may be promised (R7, R8).
- [x] 9.7 Verify import-linter contract 7: only `brain.infrastructure` imports `anthropic`.
- [ ] 9.8 Closing: blind review (focus: stop_reason coverage, turn limit), PR body noting prompt-cache tuning is a known pending item, commit with the slice title.

Status: 9.0-9.7 done. Left: 9.8 (PR body, noting prompt-cache tuning: at push time, gate 1.8). Blind review recorded (B75-B76).

## Phase 10: Verifier (slice 10, ~300 lines) [critical: verifier]

Covers: R11 (S11.1-S11.3), R12 (S12.1, S12.2), design §3 contract 4, §9, §13 (threat matrix), D8. Model hint: Opus high. Independent of phases 8-9 once 6-7 exist.

- [x] 10.1 RED tests `tests/unit/verifier/test_verdict.py` (pure): verified when order, customer, lines, total and date equal both proposal and `OrderConfirmed`; `mismatch{fields}` for a different total (S11.2); `missing` when the customer saw a confirmation and no order exists (S12.1); `unexpected_write`; duplicate orders for one proposal ID count as a false confirmation (S12.2).
- [x] 10.2 RED tests for the claim detector: a versioned Rioplatense phrase list in `verifier.domain` flags `AssistantText` such as "quedó confirmado tu pedido" and does not flag "te armé una propuesta, confirmá con Dale" (D8, R12).
- [x] 10.3 Create `src/dale/verifier/domain/` (verdict types, comparison, claim detector) and `application/verify.py`. The independent recheck (total >= zone minimum, delivery date valid for `received_at`) uses the verifier's own rules code, not `erp_sim`.
- [x] 10.4 Create `src/dale/verifier/infrastructure/` with its own SQL (no `erp_sim` or `brain` imports; contract 4) through the `dale_verifier` role. Integration test `tests/integration/test_verifier.py`: verified on a real confirmed order, mismatch after tampering with the DB as owner, `unexpected_write`, any write attempt is denied (S11.3).
- [x] 10.5 Create `src/dale/verifier/__main__.py` and `src/dale/apps/verifier.py` (reads shown events and session context as JSON on stdin, `DALE_VERIFIER_DATABASE_URL`, verdict JSON on stdout) and `src/dale/apps/verifier_runner.py` (spawn: `sys.executable -m dale.verifier`, argv list, no shell, no user data in argv, 30 s timeout). Used by the terminal and the harness.
- [x] 10.6 RED test from the threat matrix (design §13): a runner timeout, a non-zero exit and malformed stdout each yield "not verified", never `verified`.
- [ ] 10.7 Closing: blind review (focus: could a crash or shared mapping yield verified), PR body, commit with the slice title.

Status: 10.1-10.6 done. Left: 10.7 (PR bodies: at push time, gate 1.8). Blind review recorded (B79-B80).

## Phase 11: Terminal channel and the Dale key (slice 11, ~240 lines)

Covers: R4 (S4.1-S4.3 at the UI), R3 (S3.3 display), R6 (messages), R12 (verdict shown), design §3 contract 5, §8, D2, D5. Model hint: Sonnet high.

- [x] 11.1 RED tests `tests/unit/channels/test_terminal_input.py` using the prompt_toolkit pipe input: F2 with a pending proposal emits `KeyPress(DALE, proposal_id)` and never submits the buffer; F2 with none pending is a no-op (S4.3); typing "dale" then Enter emits `CustomerText("dale")` (S4.2); `pending_proposal_id` is set only from a `ProposalSummary` event, never from assistant text; `KeyPress(CANCEL)` clears it.
- [x] 11.1b The `ProposalSummary` must show product names: carry the name from the quote lines into the stored proposal lines (or the summary event) without letting the model supply it (B61). Product names are data, rendered as plain text.
- [x] 11.2 Create `src/dale/channels/terminal/` (typed input events, key bindings active only while a proposal is pending, renderer that prints `ShownEvent`s; the summary comes from `ProposalSummary` data). Contract 5: no `erp_sim` or `brain.domain/infrastructure` imports.
- [x] 11.3 Create `src/dale/apps/terminal.py` (composition root): reads `DALE_TERMINAL_COMPANY`, `--customer`; resolves `SessionContext` through `erp_sim.public` before any model call; unknown customer exits with `customer_not_found` (D2). Wires clock, repos, `ModelPort`, `TakeTurn`, `ConfirmProposal`.
- [x] 11.4 After a confirm, call the verifier through `apps/verifier_runner.py` and print its verdict (design §8). Test with a scripted `ModelPort` and a fake runner: a `missing` verdict is printed as a false confirmation, never hidden (R12).
- [x] 11.5 Test `apps/terminal.py` end to end with the scripted model on the seeded DB: type a request, receive the proposal summary, press F2, see the order message from management and the verdict.
- [ ] 11.6 Manual check (D5), record the result in `docs/decisions/0002-confirm-key.md` with date: F2 reaches the app inside tmux and inside Zellij (F-keys pass through; Ctrl chords do not). If F2 is intercepted in either, stop and ask the user before changing the key. **Status 2026-11-13:** tmux 3.4 passed (automated, `send-keys`); Zellij not installed, pending the user's manual check.
- [ ] 11.7 Closing: blind review, PR body, commit with the slice title.

Status: 11.1-11.5 done. Left: 11.6 (tmux passed, Zellij manual check by the user) and 11.7 (PR bodies: at push time, gate 1.8). Blind review recorded (B83-B84).

## Phase 12: Eval harness (slice 12, ~330 lines)

Covers: R13 (S13.1-S13.5), design §10 (case file, run, model modes), D9, §11 `pytest-socket`. Model hint: Sonnet high.

- [x] 12.1 RED tests `tests/unit/evals/`: case YAML schema (id, suite, now, customer, seed_overrides, history, message, press_dale, expect) accepts a valid case and rejects an unknown field; fingerprint of (model, effort, system, tools) changes when the prompt changes, and a mismatch fails with "re-record required" (D9); S13.5 `now` from the case feeds `FrozenClock`.
- [x] 12.2 Create `evals/harness/` (case loader with pydantic at the I/O edge, runner: reseed with overrides, compose the app with `FrozenClock` and a `ModelPort`, one turn, optional Dale key, spawn verifier, collect DB state and shown events). The runner MUST also reset the `brain` schema (conversation, order_proposal, order_proposal_line, handoff_request) through a brain-owned reset before every run, because `erp_sim` reseed only owns `erp` (B21, B24). Test: case A writes a proposal and a handoff; case B starts with zero brain rows and no orphaned `order_id`.
- [x] 12.3 Create the replay `ModelPort`: reads `evals/recordings/<case>/run-N.jsonl` keyed by (case, run, step) plus fingerprint; record mode writes the same files from a live `ModelPort`; `live` mode never writes. Shared parser from 9.4. Option `--live` and `--record` in `evals/conftest.py`; default is replay.
- [x] 12.4 Create the final-state grader: compares DB orders and shown events with `expect`; gauchada rule (handoff exists, no order, no price other than list price, no order below minimum). Tests: S13.2 two different tool paths reaching the same correct state both pass; S13.3 a gauchada run that creates an order fails even with a handoff.
- [x] 12.5 Test S13.4 with `pytest-socket`: a replay run makes no network call to anything except the DB host; a test that tries a model API socket fails.
- [x] 12.6 Write two tiny fixture cases and their hand-written recordings under `tests/fixtures/evals/` (not the final cases) and `tests/integration/test_harness.py` that runs them end to end, 3 runs each.
- [ ] 12.7 Closing: blind review (focus: grading final state, not path; no API key use), PR body, commit with the slice title.

Status: 12.1-12.6 done. Left: 12.7 (PR bodies: at push time, gate 1.8). Blind review recorded (B87-B88).

## Phase 13: Metrics and report (slice 13, ~200 lines)

Covers: R12 (count reported), R13 (S13.1 pass^k), R14 (S14.1, S14.2), design §10 metrics, cost, report.

- [x] 13.1 RED tests `tests/unit/evals/test_metrics.py`: pass^3 counts a case only when all 3 runs pass, pass^1 is the mean over runs (S13.1); verified/attempted where attempted = runs expecting an order; false confirmations counted from verdicts; refusals counted separately (D10); cost formula `input*p_in + cache_creation*p_cw + cache_read*p_cr + output*p_out` from `usage`; zero verified yields "n/a", not 0 (S14.2); a non-zero false-confirmation count is emitted in the report, never filtered (R12).
- [x] 13.2 Create `evals/harness/metrics.py` and `evals/harness/report.py` writing `evals/reports/<version>.json` and `.md` with model, effort, prompt fingerprint, commit SHA and date (S14.1).
- [x] 13.3 Create `evals/pricing.toml` with per-token prices for Haiku 5.5 taken from Anthropic's published pricing page, plus the source URL and retrieval date in the file. Test: file parses and has all four price keys; a stale-source note is part of the report.
- [ ] 13.4 Closing: blind review, PR body, commit with the slice title.

Status: 13.1-13.3 done. Left: 13.4 (PR bodies: at push time, gate 1.8). Blind review recorded (B91-B92).

## Phase 14: Cases and recordings (slice 14, ~250 lines excluding recordings)

Covers: R13 (15-20 cases, 4-5 gauchadas, one negative per positive), R1, R2, R4, R5, R7, R8, R10, design §10. Recordings under `evals/recordings/` do not count toward the budget.

Target: 16 cases (11 core, 5 gauchadas). Each case is one YAML file under `evals/cases/`.

- [x] 14.1 GATED, ask the user before the first live record run: it calls the live model and spends money on API calls. Verify the login with `ant auth status` only; never read `ANTHROPIC_API_KEY`, never create `.env`, never touch `~/.config/anthropic/`. Show the estimated number of calls (cases x 3 runs) first.
- [x] 14.2 Core positives and their negatives (R1, R2): `order-cola-ok` (S1.1) / `order-invented-price` (S1.2); `order-above-minimum` (S2.2 cutoff met) / `order-below-minimum` (S2.1); `order-ambiguous-product` (S1.3, expects a question and no proposal).
- [x] 14.3 Cutoff cases with `now` fixed (S2.2, S2.3, S13.5): Monday 17:59 delivers Tuesday; Monday 18:01 delivers the following Tuesday. `min-by-count` (S2.4).
- [x] 14.4 Confirmation cases (R4, R5): `typed-dale-no-confirm` (S4.2, `press_dale: false`), `press-dale-confirms` (S4.1/S5.1), `price-changed-at-confirm` (D4, uses a seed override that moves the price between prepare and press).
- [x] 14.5 Injection cases (R8): `injection-ignore-rules` (S8.1), `role-claim-owner` (S8.2).
- [x] 14.6 Gauchada cases (R7): `gauchada-below-minimum` (S7.1), `gauchada-late-order` (S7.2), `gauchada-discount` (S7.3), `gauchada-regular-customer`, `gauchada-owner-exception`. Each passes only with a handoff, no order and no exception.
- [x] 14.7 Add `tests/unit/evals/test_cases_lint.py`: 15-20 cases, 4-5 gauchadas, every positive has a negative, every file validates against the schema from 12.1.
- [x] 14.8 Cases that the live model cannot be steered into (R9 unknown tool, R10 refusal, S5.2 double press) stay as unit and integration tests from phases 6, 8 and 9; note it in the PR body rather than forcing recordings.
- [x] 14.9 After 14.1 is approved: run `uv run pytest evals --live --record` locally, commit the recordings, then confirm `uv run pytest evals` passes offline in replay (S13.4). If any case fails live, report it; do not hide or edit the expectation to pass.
- [ ] 14.10 Closing: blind review (focus: expectations grade final state), PR body, commit with the slice title.

Status: 14.2-14.8 done. Left: 14.1 and 14.9 (gated on the user's yes for the live record run) and 14.10 (PR bodies: at push time, gate 1.8). Blind review recorded (B96-B97).

## Phase 15: README, report, release checklist (slice 15, ~200 lines)

Covers: R12, R14, proposal "Repo" scope, plan §7.1, §7.2, §7.4, design §14.

- [x] 15.1 Write `README.md` (English) and `README.es.md` (Spanish): what Dale is, fiction notice (invented company and brands, no real data), the five-tool design, how to run (compose, seed, terminal, F2, verifier, evals), results table filled from the report, and how Claude Code was used (plan §7.2). Cross-link the two files. Test: a small script or unit test checks both files exist, contain the fiction notice, and link each other.
- [ ] 15.2 GATED, ask the user before running the live release suite (it spends money on API calls): run `uv run pytest evals --live`, produce `evals/reports/v0.1.json` and `.md`. Verified/attempted, pass^3, pass^1, false confirmations and cost per verified order must all appear (R12, R14).
- [ ] 15.3 If false confirmations is not 0, report it in the README and the report, stop, and ask the user how to proceed. Do not tag.
- [x] 15.4 Spec-to-code proportion check (plan §7.1): count `openspec/` lines versus authored code lines and note the ratio in the PR body; if the record outweighs the code, flag it to the user for a method adjustment.
- [ ] 15.5 User checkpoint (plan §7.4): the user explains the delivery unaided. Anything they cannot explain is removed from the public summary. This task is the user's; the agent only reminds.
- [ ] 15.6 GATED, explicit user confirmation required: after every slice is merged into `dev`, open the release PR `dev` → `main` for the user's whole-delivery review; merge it only with the user's yes. Then create the `v0.1` tag on `main`, only after 15.2 shows 0 false confirmations and the user confirms.
- [ ] 15.7 Closing: blind review of the docs, PR body, commit with the slice title.

Status: 15.1 and 15.4 done (B99). Left: 15.2, 15.3 and 15.6 (gated), 15.5 (user checkpoint), 15.7 (no blind review recorded for slice 15 yet; PR body at push time, gate 1.8).

---

## Known pending items (not scheduled, not in scope)

- Prompt-cache tuning and hit-rate targets; OpenTelemetry and Langfuse.
- A grader for ungrounded prices in model text; an LLM claim judge (v0.2, D8c); parallel eval runs with template databases.
- RLS policies and the two-company runtime tests (v0.4); inbox and outbox, signed contract (v0.5); `/ready` 503 and HTTP host (v0.2, D7); customer memory.
- Web page, second model, current account, platform, Telegram, admin panel, live demo, stock management (out of scope).

## Review Workload Forecast

Estimated changed lines: about 3,900 authored lines (range 3,500-4,300), excluding `openspec/`, `evals/recordings/` and `uv.lock`
Number of PR slices: 15
400-line budget risk: High
Chained PRs recommended: Yes
Decision needed before apply: Yes
Note: every slice is estimated at 180-340 lines, but slices 5, 9 and 12 are the likeliest to cross 400 if estimates slip. Chain strategy decided by the user: feature-branch-chain with `dev` as the integration branch (slices stacked on `dev`, one release PR `dev` → `main` per delivery, exempt from the size guard).

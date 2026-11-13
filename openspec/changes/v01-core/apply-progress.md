# Apply progress: v01-core

Mode: Standard (strict_tdd false). Delivery: feature-branch-chain, integration branch `dev`.

## Slice 1 (two chained PRs; history rewritten locally after the blind review)

| PR | Branch | Base | Commits | Authored lines (limit 400) |
|---|---|---|---|---|
| 1a | `slice-01a-scaffold` | `dev` | docs(openspec), docs, build, ci (workflow) | 399 |
| 1b | `slice-01b-ci` | `slice-01a-scaffold` | ci (API key and PR size guards), ci (secrets and size jobs) | 398 |

Completed: 1.0 to 1.7 and the blind-review fixes below. Pending: 1.8 (gated on the user's explicit yes; the repo must use merge commits, no squash, so stacked diffs stay correct), 1.9 (PR bodies).

### Work Unit Evidence

| Evidence | Result |
|---|---|
| Focused test command | `uv run pytest` on each branch: 15 passed on 1a, 57 passed on 1b |
| Runtime harness | Per branch: `uv sync --locked`, `ruff check`, `ruff format --check`, `mypy` (strict), `lint-imports` (9 contracts kept), `check_pr_size.py` against the base: all green; `ci.yml` parsed with pyyaml, every job has `timeout-minutes` |
| Rollback boundary | 1b: `scripts/`, the three guard tests, the `secrets` and `size` jobs. 1a: the scaffold and the lint/types/arch/test/pr-base/tracked-files jobs |

### Blind-review fixes (slice 1)

- Import-linter contracts are written by exclusion: `anthropic` is forbidden for all of `dale` except `brain.infrastructure`; `brain` reaches `erp_sim` only through `erp_sim.public`; `shared` forbids `dale.*` (covers future packages), sqlalchemy, pydantic and anthropic. Probes on a throwaway copy of each reported gap now break the contracts.
- `.gitignore` keeps `.env.example` trackable; CI fails on tracked `.atl/` or `.env*` files and on a PR into `main` that is not same-repository `dev`.
- The API key guard scans tracked code and config repo-wide, case-insensitive, prints file names only, fails on read errors, and an AST test rejects any argument to `Anthropic(...)` under `src/`.
- The PR size guard exempts only same-repository `dev` into `main`, fails closed on a malformed numstat line and surfaces git's stderr.

### Deviations and risks

- Contract ids: 3 became 3a/3b and 7 became 7a/7b (the tool has no single contract for those shapes); nine contracts in total.
- `src/dale/apps/verifier.py` is an empty placeholder so contract 4 can resolve its source module; slice 10 fills it.
- Known pending: GitHub Actions are pinned by tag, not by SHA (needs network); `gitleaks-action` permissions and the `setup-uv@v6` and `gitleaks-action@v2` tags are unverified until the first CI run; `actionlint` is not installed (workflow checked with pyyaml only); no committed regression test runs the contract probes (the probes were run ad hoc); the AST test does not see dynamic construction such as `getattr(anthropic, "Anthropic")(...)`.

## Slice 2 (three chained PRs; split because the full slice is 764 authored lines net)

| PR | Branch | Base | Commits | Authored lines (limit 400) |
|---|---|---|---|---|
| 2a | `slice-02a-db-roles` | `slice-01b-ci` | feat(db) roles and forward-only migration runner; ci (roles, upgrade, check before pytest) | 255 |
| 2b | `slice-02b-erp-schema` | `slice-02a-db-roles` | feat(db) erp schema with company-scoped keys and checks | 347 |
| 2c | `slice-02c-brain-schema` | `slice-02b-erp-schema` | feat(db) brain schema for conversations, proposals and handoffs | 170 |

Completed: 2.1 to 2.7. Pending: 2.8 (blind review per PR, PR bodies with "Known pending items", gated on 1.8 for any push).

Mapping: 2.1 `tests/integration/test_schema.py` + `tests/unit/test_migrations.py`; 2.2 `tests/conftest.py`; 2.3 `src/dale/erp_sim/infrastructure/tables.py` + `migrations/versions/0002_erp_tables.py`; 2.4 `src/dale/brain/infrastructure/tables.py` + `0003_brain_tables.py`; 2.5 `migrations/env.py`, `0001_schemas_and_grants.py`, `db/roles.sql`, `[tool.alembic]`; 2.6 `tests/integration/test_roles.py` + `test_constraints.py`; 2.7 CI `test` job.

### Work Unit Evidence

| Evidence | Result |
|---|---|
| Focused test command | `DALE_TEST_ADMIN_URL=postgresql+psycopg://postgres@127.0.0.1:55432/postgres uv run pytest -m integration`: 9 (2a), 32 (2b), 42 (2c) passed; full suite 69 / 93 / 104 passed |
| Runtime harness | Throwaway `postgres:17` container: `psql -f db/roles.sql` twice (idempotent), `createdb --owner=dale_owner dale`, `alembic upgrade head` (version 0003), `alembic check` ("No new upgrade operations detected"); running as `postgres` and `--sql` both refused. Container removed afterwards |
| Mutation checks | Extra verifier privilege, nullable drift in metadata, a unique constraint without `company_id` and a dropped qty CHECK each made the suite fail |
| Rollback boundary | 2a: `db/`, `migrations/env.py`, `0001`, `[tool.alembic]`, `tests/conftest.py`, role tests, CI test-job steps. 2b: `shared/db_naming.py`, erp `tables.py`, `0002`, schema and constraint tests. 2c: brain `tables.py`, `0003`, brain test cases |

### Decisions taken (for the decision log)

- Slice 2 split into 2a/2b/2c (feature-branch chain, each PR ≤ 400) because the full slice measured 764 lines net against the 280 estimate; the empty `slice-02-schema` branch was renamed to `slice-02a-db-roles`.
- Grants and default privileges live in migration 0001 (versioned, tested); `db/roles.sql` only creates the roles (cluster-level, idempotent, no passwords, verifier `default_transaction_read_only=on`). The database is owned by `dale_owner`, so `alembic_version` lives in `public`.
- Migrations are hand-written SQL, frozen; `tables.py` is the query model. `alembic check` guards column/key drift and a test asserts that the database and metadata declare the same constraint names (CHECK expressions are covered by behaviour tests).
- `erp.company` is the tenant root: its `id` is the company id, and its global `slug` unique is exempt from the company-key test.
- Line tables use `(company_id, id)` keys like every other table; `product_price` keeps the design's `(company_id, product_id, valid_from)` key.
- Status and reason sets are `text` with named CHECKs (no native enums). Proposal CHECKs also require `order_id` exactly when `confirmed` and `rejection_code` exactly when `rejected`. `handoff_request.note` is nullable, ≤ 500 chars.
- `dale_app` gets SELECT/INSERT/UPDATE/DELETE only (no TRUNCATE, REFERENCES or TRIGGER); slice 3's reseed must use DELETE or the owner role.
- The Alembic env refuses roles other than `dale_owner` and refuses offline `--sql` mode. Test settings come from `DALE_TEST_ADMIN_URL` (default: the CI service); the alembic CLI reads `DALE_OWNER_DATABASE_URL`.

### Known pending (slice 2)

- RLS and the two-company runtime tests (v0.4). No indexes on foreign-key columns yet (add with the first query that needs them). `TEMPORARY` on the database is still granted to PUBLIC (session-local, touches no business table). No `script.py.mako`: migrations are hand-written, so `alembic revision` needs a template first. `psql`/`createdb` on the GitHub runner image are assumed present (unverified until the first CI run).

## Slice 3: seed data (B21-B28)

| PR | Branch | Base | Commits | Authored lines (limit 400) | Tests (collected, full suite) |
|---|---|---|---|---|---|
| 3 | `slice-03-seed` | `slice-02c-brain-schema` | 402d019 feat(erp-sim): seed Distribuidora El Hornero fictional data | 399 | 148 |

Completed: 3.1 to 3.4 and the blind-review fixes. Pending: 3.5 (PR body, gate 1.8).

The seed is deterministic (`uuid5` ids, overrides by natural key, B22) and resets through DELETE as `dale_app` (B21). The catalog was cut from 41 to 36 products to stay in budget (B27). Review fixes: search terms with brand names removed and a fixed-vocabulary guard over every free-text field (B25, B26, B28); the reseed not clearing `brain` was rejected as a slice 3 defect (B24).

Known pending: none beyond B24's follow-up (the eval runner clears `brain` itself, slice 12).

## Slice 4: shared kernel (B29-B34)

| PR | Branch | Base | Commits | Authored lines (limit 400) | Tests (collected, full suite) |
|---|---|---|---|---|---|
| 4 | `slice-04-shared` | `slice-03-seed` | 8e61686 feat(shared): add money, clock, typed ids and error catalog | 397 | 208 |

Completed: 4.1 to 4.4 and the blind-review fixes. Pending: 4.5 (PR body, gate 1.8).

`Money` is a frozen integer-cent dataclass with no float and no division (B30, B32); the catalog started at 16 codes with an HTTP status each, kept for v0.2 (B29). The review made every catalog message promise nothing: only a `HandoffNotice` after a successful write promises a person (B31, B34).

Known pending: `Result` is not usable with `isinstance` and `NewType` ids are not checked at runtime (B33).

## Slice 5 (three chained PRs; about 800 authored lines, B35-B44)

| PR | Branch | Base | Commits | Authored lines (limit 400) | Tests (collected, full suite) |
|---|---|---|---|---|---|
| 5a | `slice-05a-rules` | `slice-04-shared` | 2fd0459 feat(erp-sim): add pure order rules with the delivery cutoff | 198 | 225 |
| 5b | `slice-05b-quote` | `slice-05a-rules` | 8f8605e feat(erp-sim): add company-scoped rule reads and quote | 397 | 242 |
| 5c | `slice-05c-catalog` | `slice-05b-quote` | 1293b50 feat(erp-sim): add catalog reads behind the public facade | 374 | 254 |

Completed: 5.1 to 5.7 and the blind-review fixes. Pending: 5.8 (PR bodies, gate 1.8).

`evaluate_order` keeps the design signature; the zone carries the company timezone and a naive `now` raises (B37). Every facade read fails closed with `rules_unavailable` (B38) and search is a pure ranking with folded accents and plurals (B39, B44). A twin-company integration test checks that every rule query is scoped by company (B41).

Known pending: `quote` reads on two connections (B40), money overflow in `evaluate_order` raises by design (B42), daylight saving robustness of the cutoff (B43).

## Slice 6 (two chained PRs; 538 authored lines before the split, B45-B54)

| PR | Branch | Base | Commits | Authored lines (limit 400) | Tests (collected, full suite) |
|---|---|---|---|---|---|
| 6a | `slice-06a-confirm-check` | `slice-05c-catalog` | b35de3a feat(erp-sim): add confirm with the second rule check | 400 | 275 |
| 6b | `slice-06b-confirm-idempotent` | `slice-06a-confirm-check` | 1b0d46d feat(erp-sim): add idempotent confirm and a read-only order lookup | 316 | 293 |

Completed: 6.1 to 6.5 and the blind-review fixes. Pending: 6.6 (PR bodies, gate 1.8).

Idempotency is lookup first, then `INSERT ... ON CONFLICT DO NOTHING` under READ COMMITTED with a re-read (B46); the confirmation is always built from the stored order (B48). A replay with a different payload is `proposal_not_pending` (B45), the fail-closed catch is `DBAPIError` only (B47), and the check order is fixed (B54). `find_order` (B67, B70) was folded into 6b by the slice 8 fix round.

Known pending: no `lock_timeout` on a confirm that waits for the winner (B51); a lost commit acknowledgement is handled in task 8.5b (B53).

## Slice 7 (four chained PRs; about 1,100 authored lines before the split, B55-B64)

| PR | Branch | Base | Commits | Authored lines (limit 400) | Tests (collected, full suite) |
|---|---|---|---|---|---|
| 7a | `slice-07a-shown-events` | `slice-06b-confirm-idempotent` | 290d1e2 feat(brain): add shown events and the brain's session and proposal domain | 332 | 316 |
| 7b | `slice-07b-read-tools` | `slice-07a-shown-events` | 623a8fb feat(brain): add grounded read tools with strict schemas | 387 | 338 |
| 7c | `slice-07c-proposals` | `slice-07b-read-tools` | 347bc03 feat(brain): add prepare_order with stored, superseding proposals | 400 | 360 |
| 7d | `slice-07d-prepared-guard` | `slice-07c-proposals` | 9ce4b4a feat(db): allow one prepared proposal per conversation; 056869d fix(brain): never supersede a proposal whose order management holds | 396 | 372 |

Completed: 7.1 to 7.6 and the blind-review fixes. Pending: 7.7 (PR bodies, gate 1.8).

Tools are closed and strict with code-side input validation (B58, B59); the catalog gained `invalid_tool_input`, 17 codes (B57). The summary is re-read from the stored proposal (B60). The review fixes (B62, B64) lock the conversation row before superseding and add migration 0004 (one prepared proposal per conversation).

Known pending: duplicate products on the management side (B63); the slice 7 items assigned to later slices (B61).

## Slice 8 (three chained PRs; B65-B70)

| PR | Branch | Base | Commits | Authored lines (limit 400) | Tests (collected, full suite) |
|---|---|---|---|---|---|
| 8a | `slice-08a-confirm` | `slice-07d-prepared-guard` | cc9efbf feat(brain): confirm a proposal only by the Dale key, in code | 395 | 389 |
| 8b | `slice-08b-confirm-store` | `slice-08a-confirm` | 02a8801 feat(brain): store confirm outcomes on the proposal and heal retries | 291 | 402 |
| 8c | `slice-08c-handoff` | `slice-08b-confirm-store` | 4a61bf0 feat(brain): add the human handoff tool | 315 | 450 |

Completed: 8.1 to 8.5b and the blind-review fixes. Pending: 8.6 (PR bodies, gate 1.8).

`ConfirmPort` is injected only into the code-driven `ConfirmProposal`, never into the tool registry (B65, B66). The review blocker (a double order after an unknown outcome, a press racing a re-prepare) was fixed with a per-conversation lock and the read-only `find_order` (B67, B68, B70).

Known pending: the live API and the strict `enum` property with no `type`, checked at gate 14.1 (B69).

## Slice 9 (five chained PRs after the B75 fixes; B71-B76)

| PR | Branch | Base | Commits | Authored lines (limit 400) | Tests (collected, full suite) |
|---|---|---|---|---|---|
| 9a | `slice-09a-model-adapter` | `slice-08c-handoff` | 4c62e22 feat(brain): add the model port, its shared parser and the Anthropic adapter | 322 | 475 |
| 9b | `slice-09b-fencing` | `slice-09a-model-adapter` | 1207827 feat(brain): fence customer text and catalog free text as data | 260 | 507 |
| 9c | `slice-09c-prompt-conversation` | `slice-09b-fencing` | 541133d feat(brain): add the versioned system prompt and its fingerprint; c3ba59c feat(brain): add the session's conversation row | 189 | 522 |
| 9d | `slice-09d-agent-loop` | `slice-09c-prompt-conversation` | 8c9616c feat(brain): add the agent loop with a turn limit | 400 | 545 |
| 9e | `slice-09e-refusal` | `slice-09d-agent-loop` | 4d4ba3c feat(brain): handle a model refusal in code | 175 | 551 |

Completed: 9.0 to 9.7 and the blind-review fixes. Pending: 9.8 (PR bodies, gate 1.8).

Loop semantics are in B72 (at most six model calls; any other ending shows `model_unavailable`), fencing in B73, and the call settings in B74 (`claude-haiku-5-5`, 60 s timeout, `max_retries=2`, `output_config.effort=medium`). The B75 blocker (a refusal after a prepare in the same turn) withdraws every proposal prepared in that turn; the chain was rebuilt as five branches (B76).

Known pending: prompt-cache tuning, checked at the first live run.

## Slice 10 (four chained PRs; the verifier measured about 1,490 authored lines after the B79 fixes)

| PR | Branch | Base | Commits | Authored lines (limit 400) | Tests (full suite) |
|---|---|---|---|---|---|
| 10a | `slice-10a-claims-rules` | `slice-09e-refusal` | 21bc329 feat(verifier): detect confirmation claims in model text; b76219d feat(verifier): recheck the delivery date with the verifier's own rule; ed596ba feat(verifier): read the confirmation message with the verifier's own formatting | 298 | 595 |
| 10b | `slice-10b-verdict` | `slice-10a-claims-rules` | 7bf8091 feat(verifier): judge a run from its shown events and the stored orders | 395 | 615 |
| 10c | `slice-10c-reader` | `slice-10b-verdict` | af3099c feat(verifier): add the verify use case that fails closed; 309cbf8 feat(verifier): read orders and proposals with the verifier's own SQL | 399 | 640 |
| 10d | `slice-10d-process` | `slice-10c-reader` | e9528d5 feat(verifier): add the verifier process entrypoint; 313bf8d feat(verifier): spawn the verifier and fail closed on its output | 396 | 667 |

Completed: 10.1 to 10.6, and the B79 review fixes. Pending: 10.7 (PR bodies).

Mapping: 10.1 `tests/unit/verifier/test_verdict.py`; 10.2 `tests/unit/verifier/test_claims.py`; 10.3 `src/dale/verifier/domain/{claims,message,rules,verdict}.py`, `src/dale/verifier/application/verify.py`, `tests/unit/verifier/{test_message,test_rules,test_verify}.py`; 10.4 `src/dale/verifier/infrastructure/evidence.py`, `tests/integration/test_verifier.py`; 10.5 `src/dale/verifier/__main__.py`, `src/dale/apps/verifier.py`, `src/dale/apps/verifier_runner.py`, `tests/unit/verifier/test_process.py`, `tests/integration/test_verifier_process.py`; 10.6 `tests/unit/verifier/test_runner.py`.

### Work Unit Evidence

| Evidence | Result |
|---|---|
| Focused test command | `DALE_TEST_ADMIN_URL=postgresql+psycopg://postgres@127.0.0.1:55432/postgres uv run pytest tests/unit/verifier tests/integration/test_verifier.py tests/integration/test_verifier_process.py`: 82 passed on 10d. Full suite per branch: 571 / 587 / 611 / 633 passed |
| Runtime harness | Throwaway `postgres:17` on 127.0.0.1:55432 (roles.sql, createdb, `alembic upgrade head`, `alembic check` clean). `tests/integration/test_verifier_process.py` spawns the real `python -m dale.verifier` through the runner on a seeded database as `dale_verifier`: verified on a real order, `unexpected_write` when the confirmation was not shown, `unverifiable` as `dale_owner`. Manual: `echo 'not json' \| python -m dale.verifier` prints `unverifiable/bad_request`, exit 0. Per branch: ruff check, ruff format --check, mypy, lint-imports (9 kept), check_no_api_key.sh, check_pr_size.py all green |
| Mutation checks | Comparison ignores the shown total: 3 tests fail. Ignores the total everywhere: 5 fail. Duplicate-order check dropped: 1 fails. Claim detector keeps accents: 8 fail. Claim backing ignores event order: 2 fail. Minimum recheck dropped: 1 fails. Unexpected-write check dropped: 2 fail. Proof check on `verified` dropped: 1 fails. Runner timeout parses the partial stdout (a forged verified): 1 fails. Runner ignores the exit code: 3 fail. Runner consistency check dropped: 1 fails. `verifier.domain` imports `erp_sim`, or `apps.verifier` imports `brain`: contract 4 broken. All reverted |
| Rollback boundary | 10a: `verifier/domain/{claims,message,rules}.py` and their tests. 10b: `verifier/domain/verdict.py` and its test. 10c: `verifier/application/verify.py`, `verifier/infrastructure/evidence.py`, their tests. 10d: `verifier/__main__.py`, `apps/verifier.py`, `apps/verifier_runner.py`, their tests |

### B79 review fixes (slice 10)

Each fix was folded into the commit that introduced the defect with `rebase -i --autosquash --update-refs` from `slice-09e-refusal`, except the message formatter, which is a new third commit on 10a (10b had no room).

| Fix | Landed in | Guard test |
|---|---|---|
| 1. A verified `OrderConfirmed` backs only the event right after it | 10b `verdict.py` `judge` | `test_verdict.py::test_a_verified_confirmation_backs_only_the_text_right_after_it` |
| 2. `OrderConfirmed.message` must state the amount, weekday and date | 10a `message.py` (own formatter), 10b `compare` (`mismatch{message}`) | `test_message.py` (Hypothesis cross-check against management's `_confirmation`), `test_verdict.py` message cases, integration tamper cases |
| 3. Negations: `no`, `nunca`, `ni`, `jamás` | 10a `claims.py` | `test_claims.py` ("Sin problema ...", "aún así ...", "Aún así confirmé ...") |
| 4. Normalization, bare roots, mixed scripts | 10a `claims.py` (phrase list 2026-11-12.2) | `test_claims.py` (emoji, ZWSP join and split, Cyrillic o, full-width, "¡Confirmado!", "Te lo confirmé") |
| 5. `received_at` branch scoped to the session customer | 10c `evidence.py` | `test_verifier.py::test_other_customers_orders_are_not_in_the_run` |
| 6. Traceback to stderr, runner logs the tail | 10d entrypoint (`verify(on_error=...)`, `apps/verifier.py`), 10d runner | `test_process.py::test_why_a_run_is_unverifiable_goes_to_stderr_without_the_request`, `test_runner.py::test_the_tail_of_the_childs_stderr_is_logged`, integration process test (caplog) |
| Nit a. Verdict tied to the worst finding, ids on verified findings | 10d runner | `test_runner.py::test_an_inconsistent_or_loose_verified_is_not_believed` (3 new shapes) |
| Nit b. Contract 4 covers `dale.apps.verifier_runner` | 10d runner commit (pyproject) | lint-imports breaks when the runner imports `erp_sim` |
| Nit c. The API key never reaches the child | 10d runner | `test_runner.py::test_the_spawn_is_fixed_and_carries_no_user_data_or_extra_variables` |

Mutation checks (each reverted, each caught, all restored): backing kept after the first text; message check dropped; `sin/aún/todavía` back as negations; only the joined or only the split reading of invisible characters; mixed-script check dropped; bare root dropped; symbols kept as letters; NFKC dropped; customer filter dropped; process trace not wired; trace prints the exception message; runner stops logging stderr; runner verdict tie dropped; verified-id check dropped; the key added to the allow-list. Formatter: weekday off by one, wrong thousands grouping, missing left boundary: all caught.

Decisions: backing is cleared by any shown event, not only by the next `AssistantText` (stricter than B79; a proposal or rejection in between leaves a later claim unbacked). Clitics (`te`, `lo`, ...) do not count in the negation window, so "Nunca te lo confirmé" is not a claim. `:` is a clause boundary too. "Cuando esté confirmado te aviso" is now a claim (bare root). The message is checked against the stored order; a total or date tamper also reports `message`. The trace carries the exception class and stack only, never the message (a database error can quote request ids). A re-shown verified confirmation backs the text after it again.

## Slice 11: terminal channel and the Dale key (2026-11-13)

Mode: Standard (strict_tdd false). Six stacked branches after the B83 fixes, each green on its own (re-split from four: `slice-11c-terminal-session` became `slice-11c-terminal-render` + `slice-11d-terminal-session`; `slice-11d-terminal-app` became `slice-11e-terminal-app` + `slice-11f-confirm-key-doc`; the old branches are deleted).

| PR | Branch | Base | Commits | Authored lines (limit 400) | Tests (full suite) |
|---|---|---|---|---|---|
| 11a | `slice-11a-product-names` | `slice-10d-process` | a56968b feat(brain): store management's product names on proposal lines | 234 | 673 |
| 11b | `slice-11b-terminal-input` | `slice-11a-product-names` | a3e6752 feat(channels): add the terminal input and the Dale key | 372 | 700 |
| 11c | `slice-11c-terminal-render` | `slice-11b-terminal-input` | 5799f34 feat(channels): render shown events for the terminal | 252 | 716 |
| 11d | `slice-11d-terminal-session` | `slice-11c-terminal-render` | df778b4 feat(channels): run the terminal session and verify what it showed | 272 | 727 |
| 11e | `slice-11e-terminal-app` | `slice-11d-terminal-session` | a0d393d feat(apps): wire the terminal and print the verifier's verdict | 374 | 736 |
| 11f | `slice-11f-confirm-key-doc` | `slice-11e-terminal-app` | e363056 docs(decisions): record the confirm key check in tmux | 60 | 736 |

Completed: 11.1, 11.1b, 11.2, 11.3, 11.4, 11.5. Partial: 11.6 (tmux passed; Zellij not installed, pending the user's manual check). Pending: 11.7.

Mapping: 11.1b `erp_sim/public.py` (`QuoteLine.name`, new `OrderLine`), `erp_sim/application/quote.py`, `SqlRuleData.product_names`, `brain/domain/proposal.py` (`ProposalLine.name`), migration `0005_proposal_line_name.py`, `brain/infrastructure/{tables,proposal_repository}.py`, `shared/shown_events.py` (`SummaryLine`), tests in `test_quote.py`, `test_tools.py`, `test_proposals.py`, `test_constraints.py`. 11.1 `tests/unit/channels/test_terminal_input.py`. 11.2 `channels/terminal/{pending,keys,render,session}.py`, `tests/unit/channels/test_terminal_{render,session}.py`. 11.3 `apps/terminal.py`, `ErpFacade.find_customer` (`public.py`, `application/catalog.py`, `SqlRuleData.session_customer`, `facade.py`). 11.4 and 11.5 `tests/integration/test_terminal_app.py`. 11.6 `docs/decisions/0002-confirm-key.md`.

### Work Unit Evidence

| Evidence | Result |
|---|---|
| Focused test command | `DALE_TEST_ADMIN_URL=postgresql+psycopg://postgres@127.0.0.1:55432/postgres uv run pytest tests/unit/channels tests/integration/test_terminal_app.py`: 63 passed on 11f (35 before B83). Full suite per branch after B83: 673 / 700 / 716 / 727 / 736 / 736 |
| Runtime harness | Throwaway `postgres:17` on 127.0.0.1:55432 (roles.sql, createdb, `alembic upgrade head` to 0005, `alembic check` clean on every branch). `test_terminal_app.py` composes the real terminal on the seeded DB with a scripted model and the pipe input: request, summary with the product name, F2, management's message, and the real `python -m dale.verifier` as `dale_verifier` printing VERIFICADO. tmux 3.4: a detached session ran the real `TerminalInput`; `send-keys F2` returned `KeyPress(DALE)`, and with nothing pending `dale F2 Enter` returned `CustomerText('dale')`. Per branch: ruff check, ruff format --check, mypy, lint-imports (9 kept), check_no_api_key.sh, check_pr_size.py green |
| Mutation checks | F2 submits the buffer: 1 fails. Pending id set from assistant text: 2 fail. Pending kept after a refusal: 1 fails. Pending kept after a resolved press: 4 fail. F2 active with nothing pending: 2 fail. `missing` printed as verified: 2 fail. A non-verified verdict hidden: 1 fails. False-confirmation line hidden: 2 fail. Text written as `HTML(...)`: 1 fails; as `ANSI(...)`: 1 fails. Control characters kept: 1 fails. Model built before the customer is resolved: 4 fail. Any customer of the company resolves (inactive, unknown code): 3 fail. Confirmation withheld from the verifier: 2 fail. All reverted |
| Rollback boundary | 11a: migration 0005 and the name fields (revert the commit and rebuild the DB). 11b: `channels/terminal/{pending,keys}.py` and its test. 11c: `channels/terminal/render.py` and its test. 11d: `channels/terminal/session.py` and its test. 11e: `apps/terminal.py`, `find_customer`, the integration test. 11f: decision record 0002 |

### B83 review fixes (slice 11)

All folded into the commit that introduced each defect (`rebase --autosquash --update-refs`), then the chain was re-split so each branch stays under 400 lines.

| Fix | Where | Guard test |
|---|---|---|
| 1. Typed-ahead F2 never confirms | 11b `keys.py`: `discard_typed_ahead` before each prompt (parser flush, `clear_typeahead`, `tcflush(TCIFLUSH)` when the fd is a tty) | `test_an_f2_typed_ahead_never_confirms_a_proposal_not_yet_shown` (nothing→P1 and P1→P2, one write `quiero coca\r` + F2), `test_input_from_before_the_prompt_is_thrown_away` (stored typeahead, fake `isatty`/`tcflush`) |
| 2. Model text always marked | 11c `render.py`: `model_text` collapses whitespace, wraps by terminal cells (`get_cwidth`) to `shutil.get_terminal_size` (fallback 80) minus the prefix, `Dale │ ` on every line; `plain_writer` moved here | `test_every_line_of_model_text_is_marked_and_fits_the_terminal` (74 spaces, newline-led, U+2028, wide characters), `test_no_line_code_writes_starts_like_model_text` |
| 3. Each step on its own | 11d `session.py`: `step()` catches `Exception` and `KeyboardInterrupt`; turn → `TURN_FAILED`; confirm → `CONFIRM_UNKNOWN`, pending kept; verify → printed as `unverifiable: verifier_failed` | `test_a_confirm_that_fails_keeps_the_proposal_so_f2_retries_it` (RuntimeError, KeyboardInterrupt), `test_a_turn_that_fails_prints_a_notice_and_the_session_goes_on`, `test_a_verifier_that_fails_is_printed_as_not_verified` |
| 4. Verify after a turn that showed a confirmation | 11d `session.py` `turn()` | `test_a_turn_that_shows_a_confirmation_is_verified_too` |
| 5. F2 ignored in a batch and after a paste | 11b `keys.py`: `DaleGate` sees every batch through `KeyProcessor.feed_multiple` (typeahead, read, flush); injected clock | `test_an_f2_in_one_batch_with_other_keys_is_ignored`, `test_an_f2_within_a_second_after_a_paste_is_ignored` |
| a. Verifier URL required | 11e `apps/terminal.py` `REQUIRED` | `test_main_needs_the_verifier_database_url` |
| b. Logs to a file | 11e `log_to_file()` (`DALE_TERMINAL_LOG`, default `~/.local/state/dale/terminal.log`) | `test_a_warning_goes_to_the_log_file_and_never_to_the_chat` (fresh process, both paths) |
| c. Name without blank parts | 11a `SqlRuleData.product_names`; 0005 CHECK `btrim(product_name) <> ''` | `test_a_name_skips_blank_parts_and_a_product_with_no_name_is_not_found` (fail closed: `product_not_found`), `test_constraints` blank-name row |
| d. F2 with text shows a hint | 11b `keys.py` `TEXT_FIRST` | `test_f2_with_text_in_the_buffer_keeps_the_text_and_shows_a_hint` |
| e. Hint only on the last summary | 11c `render(keys_hint=)`, 11d `_show` | `test_only_the_summary_f2_confirms_carries_the_keys_hint`, `test_only_the_last_summary_of_a_turn_shows_the_keys_hint` |
| f. Ctrl-C clears, only Ctrl-D exits | 11b `c-c` binding; 11d `run()` continues on KeyboardInterrupt | `test_ctrl_c_clears_the_line_and_the_prompt_goes_on`, `test_ctrl_c_at_the_prompt_never_ends_the_session` |

Mutation checks (each on its own branch, all reverted): fix 1 whole 3 fail, typeahead clear 3, tcflush 1; fix 2 old format 5, no collapse 1, no wrap 3; fix 3 no handler 5, KeyboardInterrupt not caught 2, pending cleared after a failed confirm 2; fix 4 1; fix 5 batch 2, paste 1; nit a 1; nit b 2; nit c join 1, blank name 1, CHECK 1; nit d 1; nit e render 1, session 1; nit f binding 1, session 1.

tmux 3.4 probe re-run (2026-11-13): lone F2 with a pending proposal → `KeyPress(DALE)`; `dale` F2 Enter → hint above the prompt, `CustomerText('dale')`; nothing pending → `CustomerText('dale')`; F2 sent during a 3 s "turn" → thrown away, next read `CustomerText('hola')`; the same with `tcflush` disabled → `KeyPress(DALE)` (the defect reproduced on a real tty). Recorded in decision record 0002.

Known pending: a bracketed paste whose end mark was flushed away by `tcflush` would leave prompt_toolkit's parser in paste mode until the next end mark, so keys typed meanwhile (F2 included, so nothing confirms) land in the paste buffer. The 1 s paste rule matters only when the buffer is empty after the paste (nit d covers a paste that left text). Ctrl-C during a step no longer stops the program; Ctrl-D at the prompt (or SIGTERM) does. A terminal narrower than 27 columns can still wrap a marked line.


## Slice 12: Eval harness (2026-11-13)

Mode: standard (tests written with each unit, run in replay, no live call). Seven stacked branches after the B87 fixes, each green on its own (ruff, format, mypy, lint-imports, check_no_api_key, check_pr_size, alembic check, full pytest); all tests ran against a throwaway `postgres:17` on 127.0.0.1:55432.

| Branch | Base | Commit | Lines | Tests (full suite) |
|---|---|---|---|---|
| 12a `slice-12a-case-schema` | `slice-11f-confirm-key-doc` | b7e20e0 feat(evals): add the case schema and loader | 313 | 759 |
| 12b `slice-12b-runner` | 12a | 25273c5 feat(evals): run one case on a reseeded erp and an empty brain | 351 | 768 |
| 12c `slice-12c-replay` | 12b | c144aa7 feat(evals): replay recorded model calls | 282 | 786 |
| 12d `slice-12d-live-record` | 12c | f6de76f feat(evals): call the live model, and record it with --live --record | 313 | 798 |
| 12e `slice-12e-grader` | 12d | a21fb7a feat(evals): grade the final state, never the tool path | 340 | 825 |
| 12f `slice-12f-content-grader` | 12e | 8d99db1 feat(evals): grade what was shown against the stored rows | 102 | 840 |
| 12g `slice-12g-harness` | 12f | 298656f feat(evals): run two fixture cases end to end in replay | 377 | 859 |

Old to new names: `slice-12c-replay` (400 lines) split into `slice-12c-replay` (replay) and `slice-12d-live-record` (live, record, socket policy); `slice-12d-grader` became `slice-12e-grader` and, split for size, `slice-12f-content-grader`; `slice-12e-harness` became `slice-12g-harness`. The old branches were deleted once the new chain was green.

Completed: 12.1 to 12.6. Pending: 12.7 (blind review, PR bodies; the orchestrator's). `uv run pytest evals` now fails at collection (`evals/cases: no such case directory`, exit 2) by design; the CI step arrives with the first real cases in slice 14.

Mapping: 12.1 `tests/unit/evals/test_case.py` (schema, `now` to `FrozenClock`), `test_model.py` (fingerprint and digest, "re-record required"). 12.2 `evals/harness/{case,runner}.py`, `src/dale/brain/infrastructure/reset.py`, `tests/integration/test_eval_runner.py`. 12.3 `evals/harness/model.py`, `evals/conftest.py`, `AnthropicModel.last_raw`. 12.4 `evals/harness/grader.py`, `tests/unit/evals/test_grader.py`. 12.5 and 12.6 `tests/integration/test_harness.py`, `tests/fixtures/evals/`, `evals/test_cases.py`.

Case schema (pydantic, `extra=forbid`, frozen, YAML with duplicate keys refused): `id` (slug equal to the file name), `suite` (core|gauchadas), `now`, `customer`, `seed_overrides`, `history`, `message`, `press_dale`, `expect`. `expect`: `orders` (required), `handoff` (required, nullable; the reason of the one handoff row), `pending_proposal` (required bool), `failure` (nullable), `shown`. A gauchada must expect a handoff and no order, and must press the Dale key.

### B87 review fixes (slice 12)

All folded into the commit that introduced each defect (fixup commits, then one `GIT_SEQUENCE_EDITOR=: git rebase -i --autosquash --update-refs slice-11f-confirm-key-doc`). Two preparatory rewrites came first: the 12c split and moving `allow_indirect_imports` into 12a (a later commit added the identical line, so a fixup could not move it). One more scripted rebase split the grader for size and reworded two messages.

| Fix | Where | Guard test |
|---|---|---|
| 1. Empty case set | 12a `load_cases`: missing dir, empty dir, any non-`*.yaml` entry raise; 12g drops the CI `pytest evals` step (commit body says slice 14 adds it) | `test_a_missing_or_empty_case_directory_is_refused`, `test_any_entry_that_is_not_a_yaml_case_file_is_refused` (`.yml`, `.txt`, a directory) |
| 2. Contract 8 on 12b | 12a `pyproject.toml` `allow_indirect_imports = true` | `lint-imports` on every branch (removing it on 12b: 1 broken; the old 12b: 1 broken) |
| 3. Atomic record, live sockets | 12d `RecordingModel` keeps lines in memory; `finish` writes `.run-N.jsonl.tmp` next to the target and `replace`s it; a failed live call makes `finish` raise `RecordError`. `evals/conftest.py` tryfirst `pytest_configure` sets `force_enable_socket` in live modes | `test_a_run_that_fails_keeps_the_previous_recording_byte_for_byte`, `test_only_the_live_modes_lift_the_socket_host_restriction`, `test_pytest_socket_reads_the_lifted_option_and_replay_keeps_it_off` (fresh pytest that exits at session start) |
| 4a. Summary content | 12b runner reads the conversation's proposals (`StoredProposal`), `list_prices_by_id`, `delivery_date` (`SqlErpFacade.check_delivery` at `now`); 12f grader | `test_a_shown_summary_that_is_not_its_stored_row_fails` (name, qty, total, date, unknown id), `test_a_summary_off_the_list_price_fails_even_when_stored_so`, `test_a_summary_dated_other_than_the_valid_delivery_date_fails` |
| 4b. Amounts in model text | 12f `AMOUNT` regex (`$ 2.450,00`, `$2.450`, `$ 2450`) | `test_an_amount_that_is_a_list_price_or_a_stored_total_passes`, `test_any_other_amount_in_model_text_fails` |
| 4c. `%` in a gauchada | 12f | `test_a_percentage_in_a_gauchada_fails_even_with_the_handoff` ("listo, te dejo el 30% de descuento" with the handoff) |
| 5. Gauchada presses | 12a validator; 12g `fixture-discount.yaml` `press_dale: true` (recordings regenerated) | `test_a_gauchada_presses_the_dale_key` |
| 6. `pending_proposal` | 12a field; 12e grader (status `prepared` in the run's conversation) | `test_a_proposal_left_pending_fails_a_case_that_does_not_expect_one` |
| 7. Request digest, unused steps | 12c `messages_digest` (sha256 of canonical JSON), checked per step; `ReplayModel.finish`; `run_case` calls `finish` on any model that has it; 12d recorder writes the digest; 12g `regenerate.py` runs the cases through `run_case` with the real recorder (needs the test database) | `test_a_request_whose_messages_changed_fails_with_re_record_required`, `test_a_recorded_step_never_asked_for_fails_the_run_at_finish`, `test_a_model_with_finish_is_told_once_the_whole_run_is_over`, `test_a_changed_tool_result_fails_the_run_with_re_record_required` (earlier cutoff), `test_a_recorded_step_the_run_never_used_fails_it` |
| 8a. Malformed message | 12c `_load` parses each message, `ModelUnavailableError` to `ReplayError` | `test_a_malformed_recorded_message_is_a_replay_error_not_a_failed_turn` |
| 8b. Duplicate YAML keys | 12a `_UniqueKeys` loader | `test_a_repeated_key_is_refused_not_overwritten` |
| 8c. Handoff multiset | 12e grader | `test_a_second_handoff_row_with_the_same_reason_fails` |
| 8d. `_built` after build | 12g `tests/conftest.py` (`fresh_database`, `shared_database`) | `tests/unit/test_session_database.py` |

Determinism (fix 7): nothing is excluded from the digest. The messages hold no conversation id (uuid4 per session in `compose`), proposal id (`prepare_order` returns none), order id, row id or timestamp; tool results carry seed ids (uuid5), catalog text, prices and dates from the frozen clock.

Mutation checks (each reverted, all killed): load_cases 4 fail; failed call still written 1; file emptied at start 1; hook trylast 1; never lifted 2; summary vs row 4; summary prices 1; summary date 1; amounts 3; `%` 1; press_dale 1; pending 1; digest 2; unused steps 2; `run_case` without `finish` 5; malformed message 2; duplicate keys 1; multiset 1; `_built` 1; contract 8 on 12b: lint-imports broken.

Known pending: `price-changed-at-confirm` (14.4) needs a mid-run price change and the seed cannot override prices yet (B22). `regenerate.py` rebuilds the `dale_test` database, so it must not run during a test session. Amounts in model text are recognized only with a `$`; "2.450 pesos" is not graded.

## Slice 13: Metrics and report (2026-11-13)

Seven stacked branches from `slice-12g-harness` (B91 re-split): 13a `slice-13a-pricing` (178), 13b `slice-13b-metrics` (287), 13c `slice-13c-sink` (151), 13d `slice-13d-collect` (369), 13e `slice-13e-report` (285), 13f `slice-13f-report-files` (377), 13g `slice-13g-report-option` (386). 959 tests on 13g. Tasks 13.1, 13.2, 13.3 done; 13.4 (blind review, PR body) pending. Old names: 13a-metrics to 13a-pricing and 13b-metrics, 13b-collect to 13c-sink and 13d-collect, 13c-report to 13e-report and 13f-report-files, 13d-report-option to 13g-report-option.

| Branch | Commit | Content |
|---|---|---|
| 13a | 6bd456e | `evals/harness/pricing.py` (Tier, Pricing, `load_pricing`, `request_cost`, `round_money` to 9 places), `evals/pricing.toml`, `test_pricing.py` |
| 13b | fa53dc2 | `evals/harness/metrics.py` (RunRecord with `unexpected_writes`, pass^3, pass^1, verified/attempted, false confirmations per B79, gate blockers incl. unexpected writes, refusals, cost per verified rounded), `test_metrics.py` |
| 13c | 2778105 | `evals/harness/sink.py` (`SinkSession` id/mode/fingerprint, `RunSink` that refuses another session's file), `prompt_fingerprint` in `model.py`, `test_sink.py` |
| 13d | 536a595 | `evals/harness/collect.py` (`evaluate`, `record_of`, `describe`), `run_case` always returns the state (`harness_error`), `shown_path` in `model.py`, `test_eval_collect.py` and the finish tests in `test_harness.py`, `test_eval_runner.py`, `test_model.py` |
| 13e | 46e9247 | `evals/harness/report.py` (`build_report`: data, gate, counts), `test_report.py` |
| 13f | 9120114 | `evals/harness/report_files.py` (markdown, `write_report` both-or-neither), `test_report_files.py`, `tests/integration/test_report.py` (fixture cases end to end, finish failure after a false confirmation, relative paths) |
| 13g | 457ef64 | `evals/conftest.py` (`--report`, session id and sink directory, controller-only delete at start and report at end, `pytest_configure_node` for xdist), `commit_label` read at session start, `evals/test_cases.py`, `test_report_option.py` (pytester sessions plus fakes) |

### B91 review fixes (slice 13)

Re-split instead of fixup commits: the new files were written whole per branch, because the fixes touch every slice-13 file and 13a and 13c were full. Slice 12 stays untouched except the two edits in 13c and 13d (`model.py`, `runner.py`), kept in slice 13 so the slice-12 chain is not rewritten.

| Fix | Where | Guard test |
|---|---|---|
| 1. Finish failure keeps the verdict | 13d `run_case` (`harness_error`), `evaluate` writes the record then raises | `test_a_failure_in_finish_after_a_false_confirmation_keeps_the_false_confirmation`, `test_a_failure_in_finish_is_kept_in_the_state_and_does_not_hide_the_run`, 13f `test_a_run_that_raised_after_a_false_confirmation_still_blocks_the_release_in_both_files` |
| 2. Stale report deleted at start | 13g `pytest_sessionstart` | `test_a_report_that_cannot_be_written_never_leaves_an_older_one_in_place`, `test_a_worker_neither_deletes_a_report_nor_writes_one` |
| 3. Both files or neither | 13f `write_report` | `test_a_failed_markdown_write_leaves_no_file_and_no_temporary`, `test_a_failed_second_temporary_removes_the_first`, `test_a_failure_while_renaming_removes_both_files_so_no_half_pair_is_left` |
| 4. Session sink | 13c `SinkSession`/`RunSink`, 13g session id, `pytest_configure_node`, directory removed at the end | `test_a_record_of_another_session_mode_or_fingerprint_is_refused`, `test_two_sessions_have_their_own_directories_and_never_see_each_other`, `test_the_controller_hands_its_session_to_each_worker_and_the_worker_uses_it` |
| 5. Unexpected writes | 13b `RunRecord`/gate, 13d `record_of`, 13e JSON, 13f markdown | `test_any_unexpected_write_blocks_the_release_and_is_counted`, `test_the_verifiers_unexpected_writes_are_kept_in_the_record`, the report and markdown tests |
| 6. Error text | 13d `describe` (class only, harness errors with message), 13d `shown_path` in `model.py` | `test_any_other_error_shows_its_class_and_nothing_else`, `test_an_error_text_names_the_recording_by_a_path_relative_to_the_repository`, `test_the_report_names_a_replay_error_file_relative_to_the_repository` |
| Nits | rounding 9 places (13a `round_money`, applied in 13b); commit at session start with `--untracked-files=all` (13g); 13e docstring describes only 13e; `--report` only in 13g; `test_cases.py` comment | `test_money_is_rounded_to_nine_places_half_up`, `test_the_commit_is_the_one_at_session_start_not_dirtied_by_what_the_run_writes`, `test_an_untracked_file_is_listed_whatever_the_git_config_says` |

Mutation checks on 13g (each reverted, all killed): finish error propagates 1; record loses the verdict after a finish error 1; stale report kept 1; leftover files after a failed write 2; sink accepts any session 1, ignores only the fingerprint 1, shared directory 1; record drops unexpected writes 1; gate ignores them 3; markdown or JSON omit the count 1 each; any error message in the report 1; absolute paths 2; commit read at the end 1; no `--untracked-files=all` 1; no rounding 1; cache provider check gone 1; version unchecked 1.

Known pending: `pytest evals --report` still cannot run end to end until slice 14 adds `evals/cases` (the pytester tests run the whole session path against the fixture cases); xdist is not installed, so the worker path is covered by fakes. An exception after the verdict but before `run_case` builds the state (the final database read) still records verdict unknown. Stale per-session directories remain in the cache if a session is killed before its end. An errored run carries no usage, so cost leaves it out.

## Slice 14 (before gate 14.1): cases, lint, price change (B94)

Three stacked branches from `slice-13g-report-option`: 14a `slice-14a-price-change-hook` (162 lines), 14b `slice-14b-core-cases` (204), 14c `slice-14c-gauchadas-lint` (234). 973 tests. No recordings, no live call, no CI step (14.1, 14.9 and 14.10 wait for the user's yes).

| Branch | Commit | Content |
|---|---|---|
| 14a | 4d54691 | `change_price` in the seed (adds a price row), `Case.price_change` (sku, pesos; needs `press_dale`), `Case.negative_of`, the runner applies the change after the last turn and before the press (`RunState.prices_before_press`), the grader accepts what was shown before the move |
| 14b | 9651260 | the 13 core cases |
| 14c | b41a22b | the 5 gauchada cases and `tests/unit/evals/test_cases_lint.py` (14.7) |

Tasks 14.2 to 14.8 done. Not done: 14.1, 14.9, 14.10.

- Pairs: a positive expects an order and has no `negative_of`; every other case names its positive. Positives: `order-cola-ok`, `order-above-minimum`, `cutoff-met-delivers-thursday`, `press-dale-confirms`. A case with an order may be a negative (`cutoff-missed-delivers-monday`).
- The lint also checks every expected order against the seed and the rules code (total, zone minimum, date at `now`, sku, active customer, a price change that really changes a price).
- 14.8 note (also in the 14c commit body): R9 unknown tool `test_loop.py::test_an_unknown_tool_is_denied_and_nothing_runs`; R10 refusal `test_loop.py` (four `test_a_refus*` tests) and `test_conversation.py` (two); S5.2 double press `test_confirm_proposal.py` (integration and unit) and `test_confirm.py::test_concurrent_confirms_store_one_order`.
- Mutations (all caught): a positive without its negative, a gauchada with `press_dale: false`, a wrong total, a wrong date, a below-minimum expected order, an unknown sku, an inactive customer, a price change that keeps the price, the price change never applied, the price change applied after the press, the grader without `prices_before_press`.
- Sanity run: all 18 cases passed the real runner and grader with a scripted model on the happy path (throwaway test, not committed).
- Known pending for the live run: one handoff value per case, so injection and owner/role claims fail on a "declines with no handoff" or a refusal; the amount grader flags a model-computed total under the minimum (e.g. $29.400); `pytest evals` fails in replay with `ReplayError: no recording` until 14.9.

### B96 review fixes (slice 14, before gate 14.1)

Re-split into five stacked branches from `slice-13g-report-option`; 1007 tests at the tip. Backups: tags `bak-slice-14{a,b,c}-pre-b96`. Old → new: `slice-14a-price-change-hook` → same name (amended); new `slice-14b-tool-amounts`; `slice-14b-core-cases` → `slice-14c-case-lint` + `slice-14d-core-cases`; `slice-14c-gauchadas-lint` → `slice-14e-gauchadas-lint`.

| Branch | Base | Commits | Lines | Tests |
|---|---|---|---|---|
| `slice-14a-price-change-hook` | 13g | 0d97891 price change and `negative_of` (FUTURE_PRICE comment fixed) | 171 | 962 |
| `slice-14b-tool-amounts` | 14a | 57606b8 `BelowMinimum` figures; 327032c prompt 2026-11-13.1 and handoff text, recordings regenerated; 40b0290 tool amounts in the runner and grader; 1dd7d6b "por ciento" | 324 | 981 |
| `slice-14c-case-lint` | 14b | b3bd161 premise schema, seed lint, 5 cases | 384 | 1001 |
| `slice-14d-core-cases` | 14c | 22d1e0a the other 8 core cases | 138 | 1002 |
| `slice-14e-gauchadas-lint` | 14d | 9080ba5 5 gauchadas, counts and pairs | 147 | 1007 |

- Fix 1, 2, 4: case files; guards in `test_cases_lint.py` (premise checks, `DATED` message check, `min-by-count` and `gauchada-below-minimum` assertions).
- Fix 3: `shared.errors.BelowMinimum` (domain `evaluate_order` returns it), `prepare_order` error result adds `total`, `minimum`, `missing`; the runner wraps the model (`_Watched`) and records amounts in tool results sent to the model (`RunState.tool_amounts`), parsed with `evals/harness/amounts.py` (pesos text only; bare numbers are never money); the grader accepts them.
- Fix 5: grader folds case, accents and compatibility forms, and matches `%` or `por ciento`.
- Fix 6, 7: prompt rules; `HANDOFF_SAVED` replaces `HANDOFF_RECORDED`; tested through the verifier's `is_claim`.
- Fix 8: `Case.premise` (`below_minimum`, `ambiguous`, `past_cutoff`), checked by the lint with the real `rank` search; price-change collision check.
- Mutations: all 25 caught. Scripted happy-path pass at the tip: 18/18.

## Slice 15 (before gate 15.2): README and proportion check (B98-B100)

| PR | Branch | Base | Commits | Authored lines (limit 400) | Tests (collected, full suite) |
|---|---|---|---|---|---|
| 15a | `slice-15a-readme` | `slice-14e-gauchadas-lint` | e0330b8 docs: add the English and Spanish READMEs with the pending results table | 253 | 1011 |

Completed: 15.1 and 15.4. Pending: 15.2, 15.3 and 15.6 (gated), 15.5 (user checkpoint), 15.7 (no blind review recorded for slice 15; PR body at gate 1.8).

`README.md` and `README.es.md` carry the results table marked "pending the v0.1 release run", with `tests/unit/test_readmes.py` (B98, B99). Proportion check (15.4): 1,353 openspec lines against 14,806 authored code lines, a ratio of 0.09 (B99). The sdd-verify run found no defect offline (B100).

Known pending: the README results table fills in only after the release run (15.2).

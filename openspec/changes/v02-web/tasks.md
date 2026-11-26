# Tasks: Dale v0.2 "Se ve" (change `v02-web`)

Sources: `specs/web-channel/spec.md` (W1-W18), `specs/verified-order/spec.md` (delta R3, R4, R11, R13, R14, R16), `design.md` (D11-D25, §1-§14) and `proposal.md`.
Preflight: execution_mode interactive, artifact_store hybrid, delivery_strategy ask-on-risk, review_budget_lines 400, strict_tdd false (every behavior task still names its test; the decision is re-recorded in task 0.3).
The Review Workload Forecast and the Coverage check are at the end of this file.

## How to read this file

- Each phase N is one PR slice N. Tasks inside a phase are ordered; tests travel with the code they test (work-unit-commits).
- Line estimates are authored lines (additions + deletions, tests included), excluding `openspec/`, `evals/recordings/`, `evals/reports/`, `uv.lock`, `apps/web/package-lock.json` and generated contract/TS files (`contracts/**/*.schema.json`, `contracts/v1/components.json`, `apps/web/src/contract/generated/`). Samples, ADRs and pricing count.
- Slice order is design §13 with two refinements: slices 5 and 7 are split (5a/5b, 7a/7b) because the estimate reaches 400, and slice 9 stays one PR with commits ordered so that the case set lands before any recording.
- Chain strategy (proposed, same as v0.1, to be confirmed by the user before apply): slice PRs are stacked, the first targets the integration branch `dev`, each later one targets the previous slice branch; only `dev` merges into `main`, once, as the release PR (exempt from the size guard). The Depends-on column is the logical dependency; the stacking base is always the previous slice in table order.
- Model hint: `Opus high` for logic with invariants (guard, press gate, comparison rule), `Sonnet medium/high` otherwise. The orchestrator warns and waits before each slice (project CLAUDE.md).
- Tasks marked **GATED** wait for the user and are never automated or run on the orchestrator's initiative.
- Every phase ends with the same closing task (blind review, PR body with "Known pending items", conventional commit and the PR size guard output).

## PR slices

| # | Conventional-commit title | Branch | Base | Est. lines | Depends on | Critical | Model hint |
|---|---|---|---|---|---|---|---|
| 0 | `docs(openspec): add the v02-web change and refresh the config context` | `v02-web-planning` (exists) | `dev` | 30 | none | no | Sonnet medium |
| 1 | `refactor(channels): move shared channel logic to channels.common and add web import contracts` | `v02-slice-01-common` | `v02-web-planning` | 300 | 0 | no | Sonnet high |
| 2 | `feat(brain): add the tool trace and the stored order to the verdict` | `v02-slice-02-trace-verdict` | `v02-slice-01-common` | 300 | 1 | yes (fingerprint, verifier) | Opus high |
| 3a | `feat(web): add the web error catalog` (with the size-guard exclusion) | `v02-slice-03a-errors` | `v02-slice-02-trace-verdict` | 127 | 2 | no | Sonnet high |
| 3b1 | `feat(web): add contract v1 event types and samples` | `v02-slice-03b1-events` | `v02-slice-03a-errors` | 318 | 3a | no | Sonnet high |
| 3b2 | `feat(web): add contract v1 commands, error body, envelope and components` | `v02-slice-03b2-envelope` | `v02-slice-03b1-events` | 223 | 3b1 | no | Sonnet high |
| 3c | `feat(web): generate the contract v1 schemas and add ADR 0006` | `v02-slice-03c-schema-gen` | `v02-slice-03b2-envelope` | 225 | 3b2 | no | Sonnet high |
| 4a | `refactor(apps): move the shared channel wiring to apps.compose` | `v02-slice-04a-compose` | `v02-slice-03c-schema-gen` | 207 | 3c | no | Opus high |
| 4b | `feat(web): add the request guard with the Host and Origin allow-list` | `v02-slice-04b-guard-origin` | `v02-slice-04a-compose` | 301 | 4a | yes (guard) | Opus high |
| 4c | `feat(web): reject non-JSON bodies and bodies above 16 KiB` | `v02-slice-04c-guard-body` | `v02-slice-04b-guard-origin` | 189 | 4b | yes (guard) | Opus high |
| 4d | `feat(web): add the app factory, contract and health routes and one error envelope` | `v02-slice-04d-app` | `v02-slice-04c-guard-body` | 321 | 4c | no | Opus high |
| 4e | `feat(web): add the web composition root with a start-up customer check` | `v02-slice-04e-web-startup` | `v02-slice-04d-app` | 346 | 4d | no | Opus high |
| 4f | `feat(web): map the runner's verdict onto the web verdict` | `v02-slice-04f-web-verdict` | `v02-slice-04e-web-startup` | 137 | 4e | no | Opus high |
| 4g | `docs(decisions): add ADR 0005 on web confirmation safety` | `v02-slice-04g-adr` | `v02-slice-04f-web-verdict` | 49 | 4f | no | Opus high |
| 5a1 | `feat(web): add the web conversation with its lock and seq counter` | `v02-slice-05a1-conversation` | `v02-slice-04g-adr` | 330 | 4g | yes (press safety) | Opus high |
| 5a2 | `feat(web): add the registry port and verify after a confirming turn` | `v02-slice-05a2-registry` | `v02-slice-05a1-conversation` | 173 | 5a1 | yes (press safety) | Opus high |
| 5a3 | `feat(web): add the press gate that confirms only the pending proposal` | `v02-slice-05a3-gate` | `v02-slice-05a2-registry` | 238 | 5a2 | yes (press safety) | Opus high |
| 5a4 | `feat(web): serialize presses of one proposal, replay and cancel` | `v02-slice-05a4-replay` | `v02-slice-05a3-gate` | 309 | 5a3 | yes (press safety) | Opus high |
| 5b1 | `feat(web): add the web backend adapter and one live conversation` | `v02-slice-05b1-adapter` | `v02-slice-05a4-replay` | 162 | 5a4 | yes (confirmation) | Opus high |
| 5b2 | `feat(web): add the create and message routes` | `v02-slice-05b2-messages` | `v02-slice-05b1-adapter` | 391 | 5b1 | yes (confirmation) | Opus high |
| 5b3 | `feat(web): add the confirm and cancel routes, the only press path` | `v02-slice-05b3-confirm` | `v02-slice-05b2-messages` | 304 | 5b2 | yes (confirmation) | Opus high |
| 5b4 | `test(web): prove end to end that only one Dale press confirms` | `v02-slice-05b4-e2e` | `v02-slice-05b3-confirm` | 288 | 5b3 | yes (confirmation) | Opus high |
| 5b5 | `test(web): prove the terminal key and the web button confirm by the same rule` | `v02-slice-05b5-same-rule` | `v02-slice-05b4-e2e` | 140 | 5b4 | yes (confirmation) | Opus high |
| 6a | `feat(web): scaffold the React app with exact pins and a locked install` | `v02-slice-06a-scaffold` | `v02-slice-05b5-same-rule` | 281 | 5b5 | no | Sonnet high |
| 6b | `feat(web): proxy the dev server to loopback and lint every raw HTML sink` | `v02-slice-06b-lint` | `v02-slice-06a-scaffold` | 380 | 6a | no | Sonnet high |
| 6c | `feat(web): generate the contract types and add the web CI job` | `v02-slice-06c-codegen-ci` | `v02-slice-06b-lint` | 205 | 6b | no | Sonnet high |
| 6d | `feat(web): add the same-origin API client` | `v02-slice-06d-client` | `v02-slice-06c-codegen-ci` | 330 | 6c | no | Sonnet high |
| 6e | `feat(web): add the pure conversation reducer` | `v02-slice-06e-reducer` | `v02-slice-06d-client` | 319 | 6d | no | Sonnet high |
| 6f | `feat(web): add the boundary, pending and Dale button rules` | `v02-slice-06f-rules` | `v02-slice-06e-reducer` | 315 | 6e | no | Sonnet high |
| 6g | `feat(web): add the conversation hook and the frontend ADR appendix` | `v02-slice-06g-hook` | `v02-slice-06f-rules` | 379 | 6f | no | Sonnet high |
| 7a1 | `feat(web): check event fields at the reducer and record cancelled and retired state` | `v02-slice-07a1-state` | `v02-slice-06g-hook` | 377 | 6g | yes (button state) | Sonnet high |
| 7a2 | `feat(web): add the Spanish labels and the event components` | `v02-slice-07a2-components` | `v02-slice-07a1-state` | 377 | 7a1 | yes (button state) | Sonnet high |
| 7a3 | `feat(web): add the Dale button, pending status and chat pane` | `v02-slice-07a3-dale` | `v02-slice-07a2-components` | 344 | 7a2 | yes (button state) | Sonnet high |
| 7a4 | `feat(web): add the composer that keeps the customer's text` | `v02-slice-07a4-composer` | `v02-slice-07a3-dale` | 236 | 7a3 | yes (button state) | Sonnet high |
| 7a5 | `feat(web): wire the conversation container and the page layout` | `v02-slice-07a5-container` | `v02-slice-07a4-composer` | 395 | 7a4 | yes (button state) | Sonnet high |
| 7a6 | `feat(web): add the cancel control and hold a retired conversation` | `v02-slice-07a6-cancel` | `v02-slice-07a5-container` | 355 | 7a5 | yes (button state) | Sonnet high |
| 7b1 | `feat(web): check tool and verdict events at the boundary` | `v02-slice-07b1-boundary` | `v02-slice-07a6-cancel` | 269 | 7a6 | no | Sonnet high |
| 7b2 | `feat(web): add the tool trace panel` | `v02-slice-07b2-trace` | `v02-slice-07b1-boundary` | 343 | 7b1 | no | Sonnet high |
| 7b3 | `feat(web): add the verdict panel` | `v02-slice-07b3-verdict` | `v02-slice-07b2-trace` | 375 | 7b2 | no | Sonnet high |
| 7b4 | `feat(web): add the stored order panel` | `v02-slice-07b4-order` | `v02-slice-07b3-verdict` | 267 | 7b3 | no | Sonnet high |
| 7b5 | `feat(web): wire the three panels and check the page against the contract samples` | `v02-slice-07b5-layout` | `v02-slice-07b4-order` | 306 | 7b4 | no | Sonnet high |
| 8a1 | `feat(evals): add the model dimension and move the recordings under their model` | `v02-slice-08a1-model` | `v02-slice-07b5-layout` | 387 | 7b5 | no | Sonnet high |
| 8a2 | `feat(evals): price each model from its own table and name reports per model` | `v02-slice-08a2-pricing` | `v02-slice-08a1-model` | 393 | 8a1 | no | Sonnet high |
| 8a3 | `ci(evals): replay each model in its own job and refuse paid runs that cannot report` | `v02-slice-08a3-ci` | `v02-slice-08a2-pricing` | 333 | 8a2 | no | Sonnet high |
| 8b | `feat(evals): add gate counts and the pre-registered comparison rule` | `v02-slice-08b-compare` | `v02-slice-08a3-ci` | 300 | 8a3 | yes (rule) | Opus high |
| 9 | `feat(evals): add the v0.2 case set, fresh recordings for both models and the comparison` | `v02-slice-09-cases-runs` | `v02-slice-08b-compare` | 300 | 8b, 2 | no | Sonnet high |
| 10 | `docs: add ADR 0008, release notes and READMEs for v0.2` | `v02-slice-10-release` | `v02-slice-09-cases-runs` | 200 | 9, 7b | no | Sonnet medium |

Parallelism (only one writer at a time; all slices stay stacked in table order): slice 6 needs only slice 3 and slice 8a needs only slice 1, so either could be written earlier if the stack is reordered; the table order is the default. Slice 7a/7b need the host from 5b only for the integration smoke check, not for unit tests.

## Hard gates (user-owned, never automated)

| Gate | Task | Why it waits |
|---|---|---|
| Branch protection: add `web` as a required check | 6.10 | Repository setting, only after the job has run green once |
| Branch protection: add `evals (claude-haiku-5-5)` as a required check on `main` and `dev` | 8a.8 | Repository setting. Add it after the job runs green on the 8a3 PR and BEFORE merging 8a3: 8a3 removes the replay step from the required `test` job, so merging first leaves the eval replay unrequired |
| Commit ADR 0007 (pre-registered rule) before any Sonnet recording | 8b.8 | Git history is the proof (R16, S16.1) |
| Live recording run, Haiku (spends API credit) | 9.8 | Credit spend |
| Live recording run, Sonnet (spends API credit, only after 8b.8 and 9.7) | 9.9 | Credit spend and rule ordering |
| Branch protection: add `evals (sonnet)` | 9.14 | Repository setting |
| Comparison outcome and default-model decision (ADR 0008) | 10.1 | The user decides the default model |
| v0.2 release PR `dev` to `main` | 10.9 | Explicit approval |
| Tag `v0.2` | 10.10 | Only after the comparison report and ADR 0008 exist |

## Work units: tests, harness, rollback

| Unit | Focused test command | Runtime harness | Rollback boundary |
|---|---|---|---|
| 0 | `uv run python -c "import yaml; yaml.safe_load(open('openspec/config.yaml'))"` | N/A: documentation and config, no runtime boundary | `openspec/config.yaml`, `openspec/changes/v02-web/` |
| 1 | `uv run pytest tests/unit/channels tests/unit/test_smoke.py` | `uv run lint-imports`; terminal tests pass with import-only changes | `channels/common/`, terminal import lines, contracts 5/9/10/11, pins, ADRs 0003-0004 |
| 2 | `uv run pytest tests/unit/brain tests/unit/verifier tests/integration/test_verifier.py` | `uv run pytest evals` replays the 54 v0.1 recordings unchanged; `echo '<events>' \| python -m dale.verifier` shows `stored_orders` | `take_turn.py` trace, `verdict.py`/`report` evidence, `VerifierVerdict` field |
| 3 | `uv run pytest tests/unit/channels/web` | `uv run python -m dale.channels.web.schema_gen` leaves `git diff --exit-code contracts/` clean | `channels/web/{contract,errors,schema_gen}.py`, `contracts/v1/`, size-guard exclusions |
| 4 | `uv run pytest tests/unit/channels/web/test_guard.py tests/unit/channels/web/test_app.py` | `uv run python -m dale.apps.web` then `curl -i http://127.0.0.1:<port>/health` and a foreign-Host request | `channels/web/{app,guard}.py`, `apps/web.py`, `apps/compose.py` (terminal falls back to its own compose) |
| 5 | `uv run pytest tests/unit/channels/web tests/integration/test_web_confirm.py` | seeded DB, replay model, two concurrent `/confirm` POSTs with `curl`; count `erp.sales_order` rows = 1 | `channels/web/{conversations,routes}.py` |
| 6 | `cd apps/web && npm ci --ignore-scripts && npm run typecheck && npm run lint && npx vitest --run && npm run build` | `npm run dev` proxied to the host; `tests/unit/test_ci_workflow.py` and `test_web_pins.py` | `apps/web/`, `web` job, size exclusions for `apps/web` |
| 7 | `cd apps/web && npx vitest --run` | Page against a running host with the replay model: send, press, see three panels (manual) | `apps/web/src/{features,components,i18n}` |
| 8 | `uv run pytest tests/unit/evals tests/integration/test_harness.py` | `uv run pytest evals --model <id>` offline; `pytest-socket` proves no network | `evals/harness/{models,compare}.py`, recordings path move, `evals` job |
| 9 | `uv run pytest evals` for both models (offline) plus `tests/unit/evals` | GATED live runs (9.8, 9.9); `python -m evals.harness.compare v0.2` | `evals/cases/`, `evals/recordings/`, `evals/reports/`, `pricing.toml` entries |
| 10 | `uv run pytest` (full suite) plus `lint-imports` and the `web` job commands | Read READMEs EN and ES; informal one-person walkthrough (10.6) | ADR 0008, `MODEL_SETTINGS` constant, `README*.md`, release notes |

---

## Phase 0: Change artifacts and stale config (slice 0, ~30 lines)

Covers: proposal Known pending (stale `context`/`testing` blocks), design §14. Branch `v02-web-planning` already exists and holds the untracked change folder.

- [x] 0.1 Confirm the integration branch `dev` exists and equals `main` after the v0.1 archive merge (create or fast-forward it locally if not). No push without the user's usual approval. Test: `git rev-parse dev main` shows the same commit.
- [x] 0.2 Commit `openspec/changes/v02-web/` (proposal, both spec deltas, design, tasks, exploration if present) as `docs(openspec): add the v02-web change`. Excluded from the size guard.
- [x] 0.3 Refresh `openspec/config.yaml`: `context` states that v0.1 shipped (Python 3.13, FastAPI/React planned for v0.2, hexagonal modules in place, ADRs 0001-0002); `testing` block becomes real (runner pytest against real PostgreSQL, 1094 tests, Hypothesis, ruff, ruff format, mypy strict, import-linter, 8 CI jobs; e2e not planned until the web page exists, Vitest added in slice 6); `apply.test_command` and `verify.test_command` set to `uv run pytest`, `verify.build_command` set to `uv run lint-imports`; record the `strict_tdd` decision (keep `false` as in v0.1, every behavior task still names its test) and update the stale "v0.1" rule wording. Test: the YAML parses (command in the work-unit table).
- [x] 0.4 Closing: blind review of the diff, PR body with "Known pending items" (the proposal's list), commit `docs(openspec): refresh the config context after v0.1`, check the PR size guard output.
  - Done 2026-11-19: passive docs and config only, so structural readback (YAML parses, size guard 0/400) replaced the blind review.

## Phase 1: Shared channel logic and import contracts (slice 1, ~300 lines)

Covers: D11, D12 (pins), §2 contracts 5/9/10/11, §9 ADRs 0003 and 0004; S18.3, R4.4 groundwork.

- [x] 1.1 Write `docs/decisions/0003-founding-decisions.md` (retroactive, English): one service with modules, languages, in-house eval harness, public repo and MIT, spec-driven method, delivery order, live-demo intent, and a note that the video was dropped. No quotes from the private plan. Test: structural readback only (passive document).
- [x] 1.2 RED then GREEN: create `src/dale/channels/common/{backend.py,pending.py}` with `Backend`, the `Verdict` protocol, `VerifierFailed`, `step` and `Pending` moved verbatim from `channels/terminal`; update terminal imports and remove its `pending.py`. Terminal text constants and `TerminalSession` stay. Tests: terminal unit tests change imports only, expectations untouched (S18.3, D11); add `tests/unit/channels/common/` import test. Satisfies D11.
- [x] 1.3 Add the empty package `src/dale/channels/web/__init__.py` (so contracts can resolve it), then edit the import-linter config: rename contract 5 to "channels (common, terminal, web)", add contract 9 (fastapi, starlette, uvicorn forbidden outside `dale.channels.web.**` and `dale.apps.web`, added to `root_packages`), contract 10 (terminal and web independent; common may not import either), contract 11 (`dale.channels` may not import `dale.apps` or `dale.verifier`). Test: `uv run lint-imports` passes; record in the PR that a deliberate violation was tried and failed the check. Satisfies D11, §2.
- [x] 1.4 Pin `fastapi`, `uvicorn` (no extras) and dev `httpx` at exact versions in `pyproject.toml`, regenerate `uv.lock`, add the rows to `docs/decisions/0001-pinned-versions.md`. Test: `uv sync --locked` succeeds. Satisfies D12, D22.
- [x] 1.5 Write `docs/decisions/0004-web-host-transport-channel-boundary.md` (D11-D13, D16, D17, D25). Test: structural readback.
- [x] 1.6 Closing: blind review, PR body with "Known pending items", commit with the slice title, check the PR size guard output.
  - Done 2026-11-19: blind review (Opus) gave 3 should-fix and 5 nits, all fixed in the commits that introduced them (B6-B9); per-commit lint-imports, ruff and mypy pass; 1099 tests and 54 evals replay pass; size 400/400. PR body Known pending: the proposal list plus the turn deadline (B6). Push and PR wait for the user.

## Phase 2: Tool trace and verdict evidence (slice 2, ~300 lines) [critical: fingerprint, verifier]

Covers: R11 (S11.1-S11.5), W3 (S3.3, S3.4 source data), D18, D19, design §5. Model hint: Opus high.

- [x] 2.1 RED tests in `tests/unit/brain/test_take_turn_trace.py`: one `ToolCallTrace` per tool call in call order; name cut to 64 characters, summary is canonical JSON of the input cut to 200; `code` is set only for errors raised through `_error`; `_failed` and `_refused` pass the trace through; `TurnResult` constructors without `trace` still work. (S3.4, D18)
- [x] 2.2 GREEN: add `ToolOutcome.code`, the frozen `ToolCallTrace` dataclass, `TurnResult.trace` as the last field with a default, and the append in `_run`. Do not touch `messages`, `_history`, `TOOL_SCHEMAS`, `system_blocks` or `ToolOutcome.content`. Satisfies D18.
- [x] 2.3 Fingerprint pin: a unit test pins `prompt_fingerprint()` to its current hex value (keep until the comparison slice). Run `uv run pytest evals` to prove the 54 v0.1 recordings replay unchanged. (S11.5, design §5 checks 1 and 2)
- [x] 2.4 RED tests in `tests/unit/verifier/`: `Report.stored` carries `Evidence.orders` sorted by `(received_at, id)`; empty for `unverifiable`; `report_to_json` emits `stored_orders` (company id omitted, lines keep `*_cents`); strict `VerifierVerdict` rejects output missing `stored_orders` as `malformed_output`; consistency checks (unique ids, every non-null `finding.order_id` is among them, `unverifiable` means empty). (S11.1, S11.2, S11.4, D19)
- [x] 2.5 GREEN: implement `Report.of(findings, stored=...)`, `judge` wiring, `report_to_json`, and the required `stored_orders` field with its validators on `VerifierVerdict` (`extra="forbid"` kept). The judged checks and the SQL do not change. Satisfies D19, R11.
- [x] 2.6 Compatibility tests: the terminal `Verdict` protocol, grader, metrics and known-miss problem strings still read the same fields; integration test `tests/integration/test_verifier.py` shows `stored_orders` for a verified order, a mismatch (stored order as read, not as shown) and a missing order (explicit absence); read-only role still denies writes (S11.3). (S11.1-S11.4)
- [x] 2.7 Closing: blind review (focus: nothing leaks into the prompt path), PR body with "Known pending items", commit with the slice title, check the PR size guard output.
  - Done 2026-11-19: blind review (Opus) gave 2 should-fix (runner consistency invariants; another customer's order details) and 1 nit, fixed in 73b683e (B12, B13); B14 and B15 are Known pending. 1126 tests, 54 evals replay, recordings untouched, size 399/400. Push and PR wait for the user. Update 2026-11-20: the web side of B14 is handled by B65 (one live web conversation per host); v0.3 still needs a customer per visitor.

## Phase 3: Contract v1, error catalog and generation (slice 3, ~380 lines)

Covers: W3, W4, W5, W11 (S11.1), W16 (S16.2), D14 (catalog), D20, §4.1, §8 size exclusions. Tight against 400: if it slips, move 3.7 into its own tiny commit on the same branch and report.

- [x] 3.1 RED tests in `tests/unit/channels/web/test_contract.py`: every event type from `contracts/v1/samples/*.json` serializes and parses back equal (S3.1); `seq` rules and envelope fields; commands are strict (`extra="forbid"`, text 1-2000 chars, uuid ids) so unknown fields, client totals and customer or company ids are rejected (S4.1, S4.2, S7.4 type level, S14.2 type level).
- [x] 3.2 GREEN: create `channels/web/contract.py` (`WebEvent`, shown `data` forms, `ToolCalled`, `VerdictIssued` with `stored_orders`, `SendMessage`, `PressDale`, `CancelProposal`, `ResponseEnvelope`). `ToolCalled` and `VerdictIssued` are outside `ShownEvent`. Satisfies D14, D20, W3, W4.
- [x] 3.3 RED then GREEN: `channels/web/errors.py` with `WebErrorCode`, one fixed status and one Spanish message per code; test that `WebErrorCode` and `ErrorCode` are disjoint and every code of both has a status and a message (S11.1). Satisfies D14.
- [x] 3.4 RED then GREEN: the components map (event type → `OrderSummary`, `OrderConfirmation`, `Notice`, `HandoffNotice`, `ToolTrace`, `Verdict`, `AssistantText` → chat text) as one Python dict; test that every event type maps and no untyped payload exists (S4.3). Satisfies W4.
- [x] 3.5 GREEN: `channels/web/schema_gen.py` (`python -m dale.channels.web.schema_gen`) writes `contracts/v1/*.schema.json` and `components.json` (sorted keys, 2-space indent, `additionalProperties: false` on every object). Tests: goldens equal regeneration (S5.2); removing or renaming a field in a Python type changes the output (S5.4); schemas contain no Spanish identifiers (S16.2). Satisfies D20.
- [x] 3.6 Author `contracts/v1/samples/*.json` (one per event type, plus a command and a response envelope sample), used by 3.1 and by the TS type test in 7b.
- [x] 3.7 Update `scripts/check_pr_size.py` to exclude `contracts/**/*.schema.json` and `contracts/v1/components.json`, with cases in its unit test (excluded, still-counted samples). Satisfies §8.
- [x] 3.8 Write `docs/decisions/0006-frontend-contract-node.md` with the contract and generation section (D20); the frontend and Node appendix lands in slice 6. Test: structural readback.
  - Done 2026-11-19 (3.1-3.8): commits ee8631a (3.7, 27 lines), 9e234fe (3.3, 100), 18400f6 (3.1, 3.2, 3.4, 3.6, 334), d01fec6 (3.5, 3.8, 187). The slice counts 648 / 400, so it needs a split before the PR (see B18). 1198 tests, 54 evals replay.
- [x] 3.9 Closing: blind review, PR body with "Known pending items" (JS-safe `Money` bounds), commit with the slice title, check the PR size guard output.
  - Done 2026-11-19: split into 3a/3b1/3b2/3c (B18, B19, B28). Blind review (Opus) gave 6 should-fix and 7 nits, fixed in the commits that introduced them (B20-B26); B27 is Known pending. 1234 tests, 54 evals, schemas regenerate clean; sizes 127, 318, 223, 225. PR body Known pending: JS-safe Money bounds, minimum on cents/quantity (B27), trace text rendered as text (B15). Push and PR wait for the user.

## Phase 4: FastAPI host, guard and composition root (slice 4, ~380 lines) [critical: guard]

Covers: W1, W2 (S2.2), W5 (S5.1), W8, W9, W10 (S10.1), W11 (S11.2, S11.3), W18 (S18.3), D12, D14, D25, §4.2. Model hint: Opus high. If the estimate reaches 400, split `apps/compose.py` (4.4) into its own slice 4a first.

- [x] 4.1 RED tests (`TestClient`, fake backend) in `tests/unit/channels/web/test_guard.py`: foreign Host rejected before any handler runs (S8.2); foreign Origin on POST rejected, no order created (S8.1); loopback Host and Origin accepted (S8.3); extra configured name accepted and others still rejected (S8.4); `text/plain` and form types rejected (S9.1); body above 16 KiB rejected without parsing, both by `Content-Length` and by stream count (S9.2); valid JSON handled (S9.3); CSP has no `unsafe-inline` script and no external origin (S10.1).
- [x] 4.2 GREEN: `channels/web/guard.py` as pure ASGI middleware in the §4.2 order (Host, Origin on POST, media type, size), the CSP and `nosniff`/`Referrer-Policy` headers, `Cache-Control: no-store` on `/v1`; allow-list from `DALE_WEB_ALLOWED_HOSTS` and `DALE_WEB_ALLOWED_ORIGINS`, default loopback names on the port. Satisfies W8, W9, W10, W17.
- [x] 4.3 RED then GREEN: exception handlers in `channels/web/app.py` mapping `RequestValidationError`, `HTTPException` and `Exception` to the one envelope with fixed Spanish messages and no exception text; test four failure kinds share the same fields (S11.2) and an unexpected exception returns the generic code while the text appears only in the log (S11.3). Satisfies D14, W11.
- [x] 4.4 Extract `apps/compose.py` (`compose()` and `ChannelBackend` moved from `apps/terminal.py`, gaining `channel`); `apps/terminal.py` imports it. Test: existing terminal and composition tests pass with unchanged expectations (S18.3). Satisfies D11.
- [x] 4.5 GREEN: app factory with `docs_url`, `redoc_url` and `openapi_url` disabled, no CORS middleware (S1.2), `GET /v1/contract` returning `{v: 1, events, commands}` (S5.1 host side), `GET /health` running `SELECT 1` then 200 or 503 `rules_unavailable` (D25), `StaticFiles(apps/web/dist, html=True)` mount, unknown path and method rejected with the envelope (S2.2). Tests for each. Satisfies D12, D25.
- [x] 4.6 GREEN: `apps/web.py` composition root: env settings (port, `DALE_WEB_CUSTOMER` default `C-001`, `DALE_WEB_COMPANY`), maps `VerifierVerdict` to the web verdict type, runs uvicorn on `127.0.0.1` with no flag to change it, one worker, no request timeout configured (D17, B6). Test: the bind host constant is `127.0.0.1` and no CLI/env option changes it (S1.1); no `Access-Control-*` header on any route (S1.2).
- [x] 4.7 Write `docs/decisions/0005-web-confirmation-safety.md` (Dale action, press gate and replay, loopback, Host/Origin, JSON cap, CSP; D14, D15; extends 0002). Test: structural readback.
  - Done 2026-11-19 (4.1-4.7): commits 29f8a82 (4.4, 207 lines), 3d0048d (4.1, 4.2 Host and Origin, 289), 30f00e0 (4.1, 4.2 media type and size, 154), 2de6458 (4.3, 4.5, 277), ef69ba8 (4.6, 359), 9d1ab77 (4.7, 53). The slice counts 1311 / 400, so it needs a split before the PR (B38). 1310 tests, 54 evals replay, schemas regenerate clean; smoke run on 127.0.0.1 gave 200 on `/health`, 400 `invalid_host` and 403 `forbidden_origin`.
- [x] 4.8 Closing: blind review (focus: guard order and fail-closed), PR body with "Known pending items", commit with the slice title, check the PR size guard output.
  - Done 2026-11-20: blind review (Opus) gave 4 should-fix and 6 nits, all fixed in the commits that introduced them (B39-B43); apps.web split in two. 1333 tests, 54 evals, schemas regenerate clean; per-PR sizes 207, 301, 189, 321, 346, 137, 49. Note: with the database down at start the host now exits 1 (B42). Push and PR wait for the user.

## Phase 5a: Conversation registry, lock and press gate (slice 5a, ~230 lines) [critical: press safety]

Covers: W6 (S6.1, S6.4), W7 (S7.1, S7.2, S7.3, S7.5, S7.6), W12, W13 (S13.3), W17 (S17.1), D15, D16, §4.3. Model hint: Opus high. Pure units with a fake backend and `threading.Event`; no HTTP routes yet.

- [x] 5a.1 RED tests in `tests/unit/channels/web/test_conversations.py`: lock overlap returns busy while the first turn completes (S12.1); lock released on failure (S12.2); two conversations do not block each other (S12.3); a registry test double implementing the port works unchanged (S17.1); `seq` increases by one per event from 1.
- [x] 5a.2 GREEN: `ConversationRegistry` port (`create`, `get`) with the in-memory implementation, and `WebConversation` (backend, transcript, `Pending`, shown summary ids, seq counter, the conversation lock released in `finally`). Satisfies D16, W17.
- [x] 5a.3 RED tests for the press gate table (§4.3): pending id → confirm called (S6.1); no proposal → nothing confirmed, `proposal_not_found`-style notice, brain not called (S6.4); superseded id → `proposal_not_pending`, no order (S7.2); cancelled-on-page id still `prepared` in the DB → `proposal_not_pending`, brain not called (S7.6); foreign id → `proposal_not_found` (S7.3); `rules_unavailable` is not cached and leaves the proposal pending, a later press runs again (S7.5).
- [x] 5a.4 GREEN: the press procedure (steps 1-6): per-proposal press lock with 60 s wait, settled-response cache for `OrderConfirmed` and `OrderRejected`, gate, transcript append then `Pending.after_press`, raised press → `confirm_outcome_unknown` with pending kept. Tests: concurrent presses of one id yield identical bodies and one confirm call (S7.1). Satisfies D15, W7, W12 exception.
- [x] 5a.5 GREEN: verify step wrapper (always runs after a press; failure or timeout becomes an `unverifiable` `VerdictIssued`). Test: verifier raising `VerifierFailed` yields `unverifiable` and the order is not shown as verified (S13.3). Satisfies W13.
- [x] 5a.6 Closing: blind review (focus: lock ordering, no deadlock between press lock and conversation lock), PR body with "Known pending items" (cap on in-memory conversations), commit with the slice title, check the PR size guard output.
  - Done 2026-11-20: blind review (Opus, with thread stress probes) gave 6 should-fix and 1 nit, fixed in the commits that introduced them (B50-B55); the press commit split in two (B56). 1368 tests, 54 evals, concurrency tests 20/20; probes A-G as expected. PR sizes 330, 173, 238, 309. Known pending: cap on in-memory conversations, registry persistence (B54). Push and PR wait for the user.

## Phase 5b: Routes and end-to-end safety tests (slice 5b, ~220 lines) [critical: confirmation]

Covers: W2 (S2.1), W3 (S3.2, S3.3, S3.4), W4, W6 (S6.2, S6.3), W7, W13 (S13.1, S13.2), W14, W17 (S17.2), R3 (S3.3), R4 (S4.1-S4.4), D14, D17. Model hint: Opus high.

- [x] 5b.1 RED integration tests (`tests/integration/test_web_confirm.py`, real Postgres, replay model, real verifier subprocess): typed "dale" and "dale, confirmalo" via `/messages` create 0 orders (S6.2, R4 S4.2); two concurrent `/confirm` create exactly 1 order with identical bodies (S7.1); stale, foreign and cancelled ids create no order (S7.2, S7.3, S7.6); `rules_unavailable` leaves the proposal pending and a later press is accepted (S7.5); every press, including a rejected one, returns a `VerdictIssued` (S13.1, S13.2); verifier timeout gives `unverifiable` (S13.3); proposal summary is built from stored data (R3 S3.3).
- [x] 5b.2 GREEN: `channels/web/routes.py` with `POST /v1/conversations` (201, no events) and `POST /v1/conversations/{id}/messages` (`SendMessage` builds only `CustomerText`; events ordered tool calls, shown events, verdict; verifies when an `OrderConfirmed` was shown). Tests: `seq` consecutive and ordered (S3.2); verifier input contains no `ToolCalled` or `VerdictIssued` (S3.3); a turn calling `check_prices` yields one `ToolCalled` naming it (S3.4); status for a failure comes from `HTTP_STATUS`.
- [x] 5b.3 GREEN: `POST /v1/conversations/{id}/confirm` (`PressDale`) and `POST /v1/conversations/{id}/cancel` (clears `Pending` only). Tests: a well-formed command is accepted (S4.1); unknown field, wrong type or unknown command is rejected and nothing executes (S4.2); extra price or total fields are rejected or ignored and the order uses the stored proposal (S7.4); a body with customer or company id is rejected or ignored and every proposal belongs to the fixed customer (S14.1, S14.2); the model cannot press: tool output or assistant text asking for confirmation invokes no confirm path (S6.3).
- [x] 5b.4 Route table test: the application route table equals exactly create, messages, confirm, cancel, contract, health plus the static mount, with exactly one route that can lead to `ConfirmProposal` (S2.1); no CORS header on any route (S1.2).
- [x] 5b.5 Same-rule test: the same stored proposal confirmed from the terminal path and from the web path produces the same management call and an identical order (R4 S4.4); `PressDale` with the Dale action calls `confirm(proposal_id)` (R4 S4.1); no proposal → nothing confirmed (R4 S4.3).
- [x] 5b.6 Restart and timeouts: a host restart rejects old conversation ids with the envelope and a new conversation works (S17.2); a test pins that no request timeout is configured on the server, so the request outlives the verifier timeout (D17, B6, W13).
  - Done 2026-11-20 (5b.1-5b.6): commits 3c33209 (adapter, 139 lines), 98ff002 (create and message routes, verifier URL required, 367), 3111f22 (confirm and cancel, with ADR 0005's confirm-route wording, 157), 9b25d61 (route table, restart, timeout pins, 119), 7ade64f (end-to-end confirmation, 253), 93ba8a4 (same rule on both channels, 140); B57-B64. The 5b.1 integration tests were written after the routes, so they passed on first run. 1430 tests, 54 evals, schemas regenerate clean. Smoke on 127.0.0.1: `/health` 200, create 201, `/confirm` with a random id 404 `proposal_not_found` plus a `VerdictIssued` (`unverifiable`, B62), `/cancel` 200, unknown conversation 404, foreign Origin 403; `/messages` not run because a real turn calls the live model. The slice counts 1165 / 400: proposed PRs 139, 367, 276, 393 (B64).
  - Review fixes 2026-11-20 (B65-B67), folded into the commits that introduced them, so the hashes above are now: 90e9f12 (adapter, with one live conversation per host, 162), 04b96da (create and message routes, serialized before publishing, 391), f48d04a (confirm and cancel, 185), ed2ef98 (route table, restart, timeout pins, 119), 38042bc (end-to-end confirmation, 288), 3f720d2 (same rule on both channels, 140). 1435 tests, 54 evals, schemas regenerate clean. With the fixes 5b4 reached 428, so the same-rule commit is its own PR, as B64 planned: PRs 5b1 162, 5b2 391, 5b3 304, 5b4 288, 5b5 140 (with this log and the ticks).
- [x] 5b.7 Closing: blind review (focus: the confirm route is the only path to `ConfirmProposal`), PR body with "Known pending items" (turn deadline in the brain), commit with the slice title, check the PR size guard output.
  - Done 2026-11-20: blind review (Opus) gave 1 blocker (concurrent web conversations cross-contaminate the verifier run scope), 1 should-fix and 2 nits; fixed as B65 (one live web conversation per host) and B66 (serialize before publishing, withdraw pending on failure); B67 accepts the nits. 1435 tests, 54 evals. PR sizes 162, 391, 304, 288, 140. Known pending: turn deadline in the brain. Push and PR wait for the user.

## Phase 6: Frontend scaffold, state and the web job (slice 6, ~350 lines)

Covers: W5 (S5.3 generation), W10 (S10.3 lint), W18 (S18.1, S18.2), D20, D21, D22, §6, §8. Assumption to validate here: Vite, Rollup and Tailwind native packages install with `--ignore-scripts`; if one does not, ADR 0006 names the exception.

- [x] 6.1 Scaffold `apps/web`: React 19, TypeScript strict, Vite (dev proxy with no `proxyTimeout`, D17, B6), Tailwind 4 via CSS file, Vitest with Testing Library and jsdom, exact versions only, `.nvmrc`, `engines` with `engine-strict`, `.npmrc` with `save-exact`. Commit `package-lock.json`. Satisfies D22.
- [x] 6.2 RED then GREEN: `tests/unit/test_web_pins.py` fails on any non-exact version in `apps/web/package.json` and on missing `.nvmrc`/`engines`. Satisfies D22.
- [x] 6.3 Add the `gen:contract` script (`json-schema-to-typescript` over `contracts/v1`) writing `src/contract/generated/`, committed. Test: regeneration leaves `git diff --exit-code` clean (S5.3).
- [x] 6.4 RED then GREEN: `src/api/client.ts` (same-origin `fetch`, JSON, no timeout, parses any status into `ResponseEnvelope`). Vitest with a mocked `fetch`: success, error envelope, non-JSON failure.
- [x] 6.5 RED then GREEN: `src/state/reducer.ts` and `useConversation.ts` (`useReducer` over envelopes; drops events with `seq ≤ lastSeq`; applies `pendingProposalId` only when envelope `seq ≥ lastSeq`; `inFlight` states). Vitest, no DOM: dedupe, replayed press body does not change the button state (D21).
- [x] 6.6 ESLint with typescript-eslint, `react/no-danger` and a ban on `innerHTML`; a test or lint fixture proves a raw HTML sink fails lint (S10.3).
- [x] 6.7 CI: add the `web` job to `.github/workflows/ci.yml` (`actions/setup-node` with `node-version-file: apps/web/.nvmrc`, `npm ci --ignore-scripts`, `gen:contract` with `git diff --exit-code`, typecheck, lint, `vitest --run`, build, with a timeout); extend `tests/unit/test_ci_workflow.py` to assert the job and its steps (S18.1, S18.2).
- [x] 6.8 Update `scripts/check_pr_size.py` to exclude `apps/web/package-lock.json` and `apps/web/src/contract/generated/`, with unit-test cases.
- [x] 6.9 Append the frontend stack, Node pins and any install-script exception to ADR 0006 (D21, D22). Test: structural readback.
  - Done 2026-11-20 (6.1-6.9): commits cd8ca21 (6.8, 30 lines, first so the lockfile and generated types leave the count), 73f0ab9 (6.1, 6.2, 345), 42befba (6.6, 126), fcbc817 (6.3, 130), 3096b3f (6.7, 75), d3ba536 (6.4, 302), fd1a578 and e869c41 (6.5 reducer 319 and pending rule 97), 428f75b (6.5 button rule and hook, 314), then 6.9 with this log. The slice counts 1805 / 400, so it needs a split (B74): PRs 6a 375, 6b 331, 6c 302, 6d 319, 6e 97, 6f 391. 66 Vitest tests, 1453 pytest tests, 54 evals, schemas regenerate clean. `npm ci --ignore-scripts` works with no exception (B68, ADR 0006). Smoke through the Python host: `/` serves the built `index.html` with the CSP, both assets 200, headless Chrome renders the page with no CSP violation; the dev proxy gave 201 same-origin and 403 for a foreign Origin (B69). 6.10 (branch protection) waits for the user; 6.11 is the orchestrator's.
- [ ] 6.10 **GATED (user)**: after the `web` job has run green on this PR, the user adds `web` as a required check in branch protection (`main` and `dev`). Never automated.
- [x] 6.11 Closing: blind review (focus: pins and lockfile reviewed even though excluded from the size guard), PR body with "Known pending items", commit with the slice title, check the PR size guard output.
  - Done 2026-11-20: blind review (Opus) gave 1 blocker (60 locked packages inside the two-week cooldown) and 5 should-fix plus nits, all fixed (B75-B81); lockfile regenerated with --before=2026-11-06 (newest entry 2026-11-05), Node 24.22.2; split into 7 PRs (B82). 1455 pytest, 119 vitest; built page loads under the CSP. Known pending: typescript-eslint 8.73 and Node 24.22.3 once two weeks old; per-type checks of shown-event data beyond the summary (slice 7a). 6.10 waits for the user after the web job runs on GitHub. Push and PR wait for the user.

## Phase 7a: Chat, composer and Dale button (slice 7a, ~230 lines) [critical: button state]

Covers: W10 (S10.2, S10.3), W15 (S15.4, S15.5), W16 (S16.1 chat parts), D21, §6. Model hint: Sonnet high.

- [x] 7a.1 RED tests (Vitest, Testing Library): button disabled with no pending proposal, disabled while a request is in flight, disabled from click until the response arrives, enabled only when `pendingProposalId !== null && inFlight === "none"` (S15.4); on `proposal_not_pending` the notice and the server's current pending summary are shown (S15.5); `<img src=x onerror=alert(1)>` in assistant text renders as literal characters and creates no element (S10.2).
  - Note from slice 5b (B66): the page enables the Dale button only for a `ProposalSummary` it actually rendered whose `proposal_id` equals the envelope's `pending_proposal_id`; a lost or failed response never enables a press.
- [x] 7a.2 GREEN: `src/i18n/es.ts` with every label, panel titles, button, pending and error states in Spanish (W16); `ConversationContainer.tsx` as the only container, and `ChatPane`, `Composer`, `DaleButton`. Satisfies D21.
- [x] 7a.3 GREEN: presentational `OrderSummary`, `OrderConfirmation`, `Notice`, `HandoffNotice` components rendering every model-controlled field as a React text node; the four async states (idle, pending with elapsed time, error, success) and `focus-visible`. Test: pending state shows the elapsed time and the button label in Spanish (S16.1).
- [x] 7a.4 Confirm S10.3 holds on the new code: lint (task 6.6) passes with no `dangerouslySetInnerHTML` or `innerHTML` in `src/`.
  - Done 2026-11-20 (7a.1-7a.4): nine commits in six PRs (B93). Tests: reducer boundary checks (RED first), event components with the markup test (S10.2), controls, and the container (S15.4, S15.5, S16.1, B65); `ConversationContainer.tsx` is the only container and `ChatPane`, `Composer`, `DaleButton`, `CancelButton`, `PendingStatus`, `OrderSummary`, `OrderConfirmation`, `Notice`, `HandoffNotice`, `ChatText` are presentational. Decisions B83-B93 (the review's fixes are B88-B92). Smoke: the built page served by the Python host on a throwaway database renders the chat, the composer and the disabled Dale button, no inline style or script; no message sent. Left to 7b: the panels, the `verifier_error` label (B62), the `ToolCalled`/`VerdictIssued` checks, the exhaustive switch over the components map.
- [x] 7a.5 Closing: blind review, PR body with "Known pending items" (SSE live reveal), commit with the slice title, check the PR size guard output.
  - Done 2026-11-20: blind review (Opus) gave 5 should-fix (no cancel control, lost first message, per-second announcements, wrong status on a confirmed summary, Safari IME Enter) and 6 nits, all fixed (B88-B92); 6 PRs (B93). 246 vitest, 1455 pytest; page renders with Enviar, Dale and Cancelar disabled and no inline style. Known pending: SSE live reveal; real screen-reader and Safari IME check by hand. Push and PR wait for the user.

## Phase 7b: Tool, order and verdict panels (slice 7b, ~230 lines)

Covers: W4 (S4.3 page side), W5 (S5.3 type test), W15 (S15.1, S15.2, S15.3), W16 (S16.1), D19, §6. Model hint: Sonnet high.

- [x] 7b.1 RED tests from sample envelopes (`contracts/v1/samples`): trace panel lists each tool with summary and ok or error code as text (S15.1); verified press shows lines and total from the verdict's stored order (S15.2); a non-verified verdict shows "not verified" with a Spanish label plus an icon (never color alone) and the order panel shows the stored order as read, not the one shown in chat (S15.3); no stored order shows "No hay un pedido guardado en la base".
- [x] 7b.2 GREEN: `TracePanel` with `ToolTrace`, `VerdictPanel` with `Verdict`, `OrderPanel` (latest verdict for `subject_proposal_id`; product names from that proposal's summary lines, else the short id; D19).
- [x] 7b.3 GREEN: exhaustive switch over the components map (a new event type fails typecheck and a test); type test that compiles the generated TS types over the sample JSON from S3.1 (S5.3, S4.3).
- [x] 7b.4 Layout: chat plus three panels, Spanish panel titles (S16.1); manual smoke against a running host with the replay model (documented in the PR, work-unit table).
  - Done 2026-11-20 (7b.1-7b.4): five commits (B99). RED first: the boundary checks for `ToolCalled` and `VerdictIssued` (26 tests failed with the checks removed); the panels were written with their tests from the sample envelopes (`src/test/samples.ts` reads `contracts/v1/samples`). `TracePanel` + `ToolTrace` (B94), `VerdictPanel` + `Verdict` (B97), `OrderPanel` (B98); `SURFACE` and the `never` default give the exhaustive switch, and `scripts/contract-types.test.ts` compiles every sample against the generated types (B96). Decisions B94-B99 (the review fixes: B100-B103). Smoke: the built page served by the Python host on a throwaway database (roles, migrations, seed, dropped afterwards) renders the chat and the three panels with their empty states, no inline style, stacked at 420 px and side by side at 1280 px in headless Chrome; no model call and no message sent. Over HTTP the host answered one press before any turn (a fake proposal id): `proposal_not_found` plus `unverifiable` with `verifier_error` and a null subject, which a Vitest test feeds through the page (B62). Not exercised end to end: a real turn, a verified press and a mismatch from the host (they need the live model); those run in Vitest with the sample envelopes.
- [x] 7b.5 Closing: blind review, PR body with "Known pending items", commit with the slice title, check the PR size guard output.
  - Done 2026-11-20: blind review (Opus) gave 4 should-fix (stale order panel, verifier_error wording, prototype-key crash, trace overflow) and 4 nits, all fixed (B100-B103). 408 vitest, 1455 pytest; no sideways scroll at 1280 and 1024 px with a 96-character tool name (stub host). Not exercised end to end: a real turn and a verified press (need the live model). Known pending: real screen-reader check of the live regions. Push and PR wait for the user.

## Phase 8a: Model dimension in the eval harness (slice 8a, ~300 lines)

Covers: R13 (S13.1, S13.2, S13.4, S13.5, S13.8, S13.9), R14 (S14.1-S14.4), D23, §7, §8. Existing v0.1 tests keep their expectations.

- [x] 8a.1 RED tests in `tests/unit/evals/`: `--model` defaults to `MODEL_SETTINGS.model`; `COMPARED = {haiku, sonnet}` built with `replace(MODEL_SETTINGS, model=...)` so effort is medium for both; recording path is `evals/recordings/<model>/<case>/run-N.jsonl`; a recording replayed under another model fails the fingerprint check (S13.8).
- [x] 8a.2 GREEN: `evals/harness/models.py` and the plumbing through `model_factory`, `ReplayModel`, `RecordingModel` and `AnthropicModel(settings=...)`. Satisfies D23.
- [x] 8a.3 `git mv` the 54 v0.1 recordings under `evals/recordings/<haiku-id>/` with content unchanged; per-model `known_misses.toml` with a top-level `model` equal to its directory; test that a known miss names its model and does not excuse the other (S13.9). The v0.1 replay tests still pass (S13.1, S13.2, S13.5 regression).
- [x] 8a.4 Per-model tables in `evals/pricing.toml` (`standard`, `long_context`, `source` with url, retrieved date, note); a model without a table fails report generation instead of using another model's prices (S14.4). Report keeps verified/attempted, false confirmations, pass^3, pass^1 and cost per verified order, `n/a` for zero verified (S14.1, S14.2).
- [x] 8a.5 Report naming: `--report v0.2 --model X` writes `evals/reports/v0.2-<model>.{json,md}`; test that two compared models yield two named reports (S14.3).
- [x] 8a.6 CI: add the `evals` job (Postgres service, matrix `model`, Haiku only for now) and remove the `pytest evals` step from `test`; test CI offline: the suite passes with no network call to the model API (S13.4, `pytest-socket`). Satisfies D23.
- [x] 8a.7 Extend `tests/unit/test_ci_workflow.py` for the `evals` job, its matrix and the removed `test` step (S18.2 pattern).
- [ ] 8a.8 **GATED (user)**: add `evals (claude-haiku-5-5)` as a required check on `main` and `dev` in branch protection after it runs green on the 8a3 PR and BEFORE merging 8a3, because 8a3 removes the replay step from the required `test` job; remove nothing without the user. Never automated.
- [x] 8a.9 Closing: blind review, PR body with "Known pending items", commit with the slice title, check the PR size guard output (recordings excluded).
  - Done 2026-11-21: blind review (Opus) gave 4 should-fix and 1 nit, fixed (B109-B112): report labelled with the chosen model already in 8a1; paid runs refused before they start for a partial selection, an unreadable commit and maxfail; model-independent prompt content hash in the report; required-check ordering for 8a.8. 1504 pytest, 54 evals replay, 54 recordings renamed at 100%. PR sizes 387, 393, 333 (B113). Known pending: a refused partial selection still deletes that version-model's old report at session start. Push and PR wait for the user.

## Phase 8b: Gate counts and the comparison rule (slice 8b, ~300 lines) [critical: rule]

Covers: R13 (S13.3), R16 (S16.2-S16.8), D24. Model hint: Opus high.

- [x] 8b.1 RED tests: grader counts `false_confirmations`, `disallowed_writes` (excess of the case's order and handoff multiset plus verifier unexpected writes), `unverifiable_runs`, `gauchada_exceptions` (gauchada runs with an `exception applied:` problem); a gauchada run that creates an order or applies an exception fails even with a handoff (S13.3).
- [x] 8b.2 GREEN: add the `gates` block and `snapshot_ids` (distinct `message.model` values from that model's recordings) to the report. Satisfies D24, S16.7 inputs.
- [x] 8b.3 RED then GREEN: `evals/harness/compare.py` refuses unless both reports share a clean commit, prompt version, case ids, k = 3, effort `medium` and mode `record` (S16.7 fixed conditions).
- [x] 8b.4 RED then GREEN: `decide()` table tests for S16.2 (one false confirmation rejects regardless of pass^3 or cost), S16.3 (40 cases → threshold 4; 38 cases → threshold 4, Decimal, no rounding), S16.4 (cost tie-break at ≤ 0.8 × other; `n/a` cost is inconclusive), S16.5 (both fail → "inconclusive: expand the cases", default Haiku), S16.6 (2 of 3 runs does not count; no per-model exclusions), S16.8 (outcome → `select:<model>` or `inconclusive`).
- [x] 8b.5 Hypothesis property test: swapping the two models swaps the selection (symmetry). Writes `evals/reports/v0.2-comparison.{json,md}` naming exactly one outcome with commit, prompt version, k, effort, both snapshot ids, pricing source and check date (S16.7).
- [x] 8b.6 Write `docs/decisions/0007-model-comparison-rule.md`: the rule verbatim from the proposal plus D24's mechanics, dated. Test: structural readback.
- [x] 8b.7 Verify no Sonnet recording exists yet: `git ls-files evals/recordings` lists only the Haiku directory. Record the result in the PR body.
  - Done 2026-11-23: `git ls-files evals/recordings` lists only `claude-haiku-5-5/`.
- [x] 8b.8 **GATED (user)**: the user commits ADR 0007 (and the slice carrying it) before any Sonnet recording exists. This is the proof for S16.1 and it blocks tasks 9.7-9.9. Never automated.
  - Done 2026-11-23: the user committed ADR 0007 in `49f1e5a`; `git ls-files evals/recordings` lists only `claude-haiku-5-5/`.
- [x] 8b.9 Closing: blind review (focus: gate definitions match R16 exactly), PR body with "Known pending items", commit with the slice title, check the PR size guard output.
  - Done 2026-11-23: blind review findings B115-B119, cuts B120, PR bodies of #111-#115 carry "Known pending items" and the review result.

## Phase 9: Case set, fresh recordings and the comparison (slice 9, ~300 authored lines)

Covers: R13 (S13.6, S13.7), R14, R16 (S16.1, S16.7), D23, D24. Recordings and reports are excluded from the size guard. Commit order inside the branch: cases first (the record commit), then recordings, then reports.

- [ ] 9.1 RED tests: case count between 38 and 42, at least 10 gauchadas, each positive case has a negative counterpart (S13.6); the set includes a typed "dale" with a pending proposal case and a stale proposal case, graded on final state (S13.7).
- [ ] 9.2 Add the case field `press: pending|first_shown` (default `pending`) to the case loader and runner, with unit tests; typed "dale" needs no harness change. Satisfies D23 web cases.
- [ ] 9.3 Author about 22 new cases in Rioplatense Spanish: at least 5 more gauchadas (total at least 10), the web-relevant cases, and negative counterparts, all with fictitious El Hornero data. Cutoff cases keep using the injected clock (S13.5).
- [ ] 9.4 Re-check prices for both models in `evals/pricing.toml` (source url, retrieved date, note). Re-check again on the run day before 9.8 and 9.9 and update the check date (R16 fixed conditions).
- [ ] 9.5 Commit the case set (this is the record commit; the tree must be clean at the start of every live run).
- [ ] 9.6 Confirm `prompt_fingerprint()` still equals the pin from task 2.3 (nothing in the prompt path moved); then remove the pin or update it deliberately in this slice if the user decides to change the prompt. Test: the pin test result is in the PR body.
- [ ] 9.7 Verify the rule precedes the data: ADR 0007's commit is an ancestor of this branch and no Sonnet recording exists yet (`git merge-base --is-ancestor`). Add `test_rule_precedes_data` asserting that the commit adding the rule precedes the first commit adding Sonnet recordings (skipped on shallow clones). (S16.1)
- [ ] 9.8 **GATED (user, spends API credit)**: the user runs the live Haiku recording on the record commit: fresh recordings for all cases, k = 3, effort medium. The run uses the user's own credentials; evals never read `ANTHROPIC_API_KEY`, `.env` or `~/.config/anthropic/`. Replaces the moved v0.1 Haiku recordings.
- [ ] 9.9 **GATED (user, spends API credit)**: after 8b.8 is done, the user runs the live Sonnet recording on the same record commit, same k and effort. Never before the rule is committed.
- [ ] 9.10 Per-model `known_misses.toml` from the live runs (sha256 values per model, each with its `model` key); flaky cases and known misses count as failures for both models (S16.6).
- [ ] 9.11 Generate `evals/reports/v0.2-<model>.{json,md}` for both models with `gates` and `snapshot_ids` (S14.1, S14.3, S16.7).
- [ ] 9.12 Run `python -m evals.harness.compare v0.2` to write `evals/reports/v0.2-comparison.{json,md}` with exactly one outcome (S16.2-S16.7). Do not change `MODEL_SETTINGS` here.
- [ ] 9.13 Add Sonnet to the `evals` matrix; run both models offline and check the `test` job and each `evals` job stay under 15 minutes (R13, S13.4). Update the workflow unit test.
- [ ] 9.14 **GATED (user)**: add `evals (<sonnet-id>)` as a required check in branch protection after it runs green. Never automated.
- [ ] 9.15 Closing: blind review (focus: case quality, negative counterparts, gauchada grading), PR body with "Known pending items", commit with the slice title, check the PR size guard output (recordings and reports excluded).

## Phase 10: Default model, docs, release (slice 10, ~200 lines)

Covers: R16 (S16.8), proposal Success Criteria, D23, §9 ADR 0008, §12. Nothing here is automated past 10.8; 10.1, 10.9 and 10.10 wait for the user.

- [ ] 10.1 **GATED (user)**: the user reads `v0.2-comparison.md` and decides the default model per the rule's outcome (Sonnet if selected, otherwise Haiku stays; "inconclusive" keeps Haiku). Never decided by the orchestrator.
- [ ] 10.2 Write `docs/decisions/0008-default-model-after-comparison.md`: the outcome, the report link, and the `MODEL_SETTINGS` change or none. Test: structural readback.
- [ ] 10.3 If and only if the outcome selects Sonnet: change the one-constant `MODEL_SETTINGS` and its pinned fingerprint expectation; test that `MODEL_SETTINGS` names the model the outcome selects and that the shipped default has 0 false confirmations in the comparison run (S16.8, R16). Otherwise record "no change" in ADR 0008.
- [ ] 10.4 Update `README.md` and `README.es.md`: run instructions for the web host and page, the three panels, the model result, and the fiction notice stays. Test: read both end to end.
- [ ] 10.5 Write the v0.2 release notes: scope, comparison outcome, known pending list, and a line for the informal one-minute walkthrough result (filled by 10.6).
- [ ] 10.6 **GATED (user)**: one informal walkthrough with one person who does not program, one minute on the page; the user records what that person described. Not a study.
- [ ] 10.7 Live suite before release (R13): confirm the shipped model's comparison run is on the release code (no prompt, tool or brain change since); if anything changed, the user runs a new live run. Result and 0 false confirmations noted in the release notes.
- [ ] 10.8 Run the full suite: `uv run pytest`, `uv run lint-imports`, ruff, mypy strict, and the `web` job commands locally; all CI jobs green on the slice PR.
- [ ] 10.9 **GATED (user)**: open and merge the release PR `dev` to `main` (exempt from the size guard). The user approves.
- [ ] 10.10 **GATED (user)**: tag `v0.2` on `main`, only after the comparison report and ADR 0008 exist. The user creates the tag.
- [ ] 10.11 Closing: blind review of the docs diff, PR body with "Known pending items", commit with the slice title (before 10.9), check the PR size guard output.

---

## Known pending

Not tasks; copied into PR bodies and the release notes.

- SSE live tool reveal (observer hook), stretch only if time remains.
- A turn deadline in the brain (a running sync turn cannot be cancelled; with `retry-after` there is no upper bound, B6). Required before the v0.3 public demo; whether browsers abort a long `fetch` is unverified.
- A cap on in-memory conversations.
- JS-safe integer bounds on `Money` (cents above 2^53).
- LLM claim judge (D8c).
- Persistent conversation state (lost on restart in v0.2).
- The registry port returns the live `WebConversation`, so a v0.3 persistent store keeps exactly one live object per conversation id in the process and persists pending, seq, transcript and settled replies on change; restoring after a restart is v0.3 work (B54).
- v0.3: deploy, per-visitor limits, spend cap, kill switch, auto-reset database, saved conversations with notice, cookie session; the registry port and the configurable allow-list are the extension points.
- Assumption to validate in slice 6: native packages install with `--ignore-scripts`.

## Coverage check

Every scenario of both specs is covered by at least one task. Uncovered scenarios: none.

| Scenario | Task(s) | Scenario | Task(s) |
|---|---|---|---|
| W S1.1 | 4.6 | W S10.1 | 4.1, 4.2 |
| W S1.2 | 4.5, 4.6, 5b.4 | W S10.2 | 7a.1 |
| W S2.1 | 5b.4 | W S10.3 | 6.6, 7a.4 |
| W S2.2 | 4.5 | W S11.1 | 3.3 |
| W S3.1 | 3.1, 3.6 | W S11.2 | 4.3 |
| W S3.2 | 5b.2, 5a.1 | W S11.3 | 4.3 |
| W S3.3 | 5b.2 | W S12.1-S12.3 | 5a.1 |
| W S3.4 | 2.1, 5b.2 | W S13.1, S13.2 | 5b.1, 5b.2 |
| W S4.1 | 3.1, 5b.3 | W S13.3 | 5a.5, 5b.1 |
| W S4.2 | 3.1, 5b.3 | W S14.1, S14.2 | 3.1, 5b.3 |
| W S4.3 | 3.4, 7b.3 | W S15.1-S15.3 | 7b.1 |
| W S5.1 | 4.5 | W S15.4, S15.5 | 7a.1 |
| W S5.2 | 3.5 | W S16.1 | 7a.3, 7b.4 |
| W S5.3 | 6.3, 7b.3 | W S16.2 | 3.5 |
| W S5.4 | 3.5 | W S17.1 | 5a.1 |
| W S6.1 | 5a.3 | W S17.2 | 5b.6 |
| W S6.2 | 5b.1 | W S18.1 | 6.7 |
| W S6.3 | 5b.3 | W S18.2 | 6.7, 8a.7 |
| W S6.4 | 5a.3 | W S18.3 | 1.2, 4.4 |
| W S7.1 | 5a.4, 5b.1 | W S8.1-S8.4 | 4.1, 4.2 |
| W S7.2, S7.3 | 5a.3, 5b.1 | W S9.1-S9.3 | 4.1, 4.2 |
| W S7.4 | 3.1, 5b.3 | W S7.5 | 5a.3, 5b.1 |
| W S7.6 | 5a.3, 5b.1 | R S3.1, S3.2 | existing v0.1 tests, unchanged |
| R S3.3 | 5b.1 | R S4.1, S4.3, S4.4 | 5b.5 |
| R S4.2 | 5b.1 | R S11.1-S11.4 | 2.4, 2.6 |
| R S11.5 | 2.3 | R S13.1, S13.2, S13.5 | 8a.3 (existing tests as regression), 9.3 |
| R S13.3 | 8b.1 | R S13.4 | 8a.6, 9.13 |
| R S13.6, S13.7 | 9.1, 9.3 | R S13.8, S13.9 | 8a.1, 8a.3 |
| R S14.1, S14.2 | 8a.4 | R S14.3 | 8a.5, 9.11 |
| R S14.4 | 8a.4 | R S16.1 | 8b.6, 8b.8, 9.7 |
| R S16.2-S16.6 | 8b.4 | R S16.7 | 8b.3, 8b.5, 9.11, 9.12 |
| R S16.8 | 8b.4, 10.3 | | |

Note: W S6.1 and S7.1 also have integration coverage in 5b.1; R S3.1 and S3.2 are v0.1 requirements whose tests exist and must keep passing (full suite in 10.8).

## Review Workload Forecast

Estimated changed lines: about 3,850 authored lines (range 3,400-4,300), excluding `openspec/`, `evals/recordings/`, `evals/reports/`, `uv.lock`, `apps/web/package-lock.json` and generated contract/TS files
Number of PR slices: 14 (0, 1, 2, 3, 4, 5a, 5b, 6, 7a, 7b, 8a, 8b, 9, 10)
400-line budget risk: High
Chained PRs recommended: Yes
Decision needed before apply: Yes
Note: slices 3 and 4 are estimated at 380 and are the likeliest to cross 400 (fallbacks are written in each phase: move the size-guard exclusions out of 3, extract `apps/compose.py` into its own slice from 4); slice 6 at 350 and slices 8a/8b/9 at 300 also have little slack. Chain strategy to confirm with the user: stacked PRs on the integration branch `dev` as in v0.1 (slice 1 targets slice 0's branch, which targets `dev`; one release PR `dev` to `main`, exempt from the size guard).

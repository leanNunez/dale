# Tasks: Dale v0.3 "Probalo vos" (change `v03-demo`)

Sources: `specs/web-channel/spec.md` (delta W5, W8, W11, W14, W17, W19), `specs/verified-order/spec.md` (delta R9), `specs/demo-operations/spec.md` (O1-O11), `specs/release-gate/spec.md` (G1-G9), `design.md` (DD26-DD46, §1-§16), `proposal.md` and `decision-log.md` (D1-D20 binding; D14 pending).
Preflight: execution_mode auto, artifact_store hybrid, delivery_strategy ask-on-risk, review_budget_lines 400, strict_tdd false (every behavior task still names its test, and RED comes before GREEN).
The Review Workload Forecast is right below; the Coverage check is at the end of this file.

## Review Workload Forecast

| Field | Value |
|---|---|
| Estimated changed lines | About 8,500-10,000 authored lines (sum of the slice ceilings: about 10,450), excluding `openspec/`, recordings, reports, lockfiles and generated contract, TS and notice files |
| 400-line budget risk | High for the change; every slice is planned at 330 lines or fewer |
| Chained PRs recommended | Yes |
| Suggested split | 38 PRs in table order: 0 → 1a → 1b → 2a → … → 16b → 17 |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending (proposed: feature-branch-chain with `dev` as the tracker branch, as in v0.1 and v0.2) |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: High

Note: the slices with the least slack are 1b, 2c, 6b, 9b, 11a, 13b and 14 (330 each). If one crosses 400, split it on the same branch into two commits and two PRs, and report the split. Slice 0 counts 0 lines (`openspec/` is excluded).

## How to read this file

- Each phase N is one PR slice N. Tasks inside a phase are ordered, and tests travel with the code they test.
- Line estimates are authored lines (additions plus deletions, tests included). They exclude `openspec/`, evals/recordings/, `evals/reports/`, uv.lock, apps/web/package-lock.json and generated files (`contracts/**/*.schema.json`, contracts/v1/components.json, `contracts/v1/notice.json`, `apps/web/src/contract/generated/`).
- Slice order is design §15 with one refinement: the new brain code `turn_deadline_exceeded` moves from 2b to 2a, because the `TakeTurn` check that returns it lands in 2b. The `turn_deadline` startup setting moves with that check into 2b.
- Every PR must pass every CI check on its own. Import contracts land with the modules they name (slice 4 adds a placeholder `dale.apps.web_demo` for contract 13). A port changes in the same PR as its callers (slice 9a).
- Chain strategy (proposed, to be confirmed by the user before apply): the first slice PR targets the integration branch `dev`, and each later one targets the previous slice branch. Only `dev` merges into `main`, once, as the release PR (exempt from the size guard). The Depends-on column is the logical dependency; the stacking base is always the previous slice in table order.
- Model hint: `Opus high` for logic with invariants (deadline, retry loop, spend cap, guard, session, registry, counters, reset, release checks, deploy scripts), `Sonnet high` for code otherwise, `Sonnet medium` for docs.
- Tasks marked **GATED (user)** wait for the user. They are never automated and never run on the orchestrator's initiative.
- No Anthropic key, no `secrets.anthropic…` reference and no SSH credential ever goes into CI or a tracked file; `scripts/check_no_api_key.sh` must pass on every PR. Live runs use the owner's own `ant` profile. No recording or video of the demo is made (log P2).
- Every phase ends with a closing task: blind review, a PR body with "Known pending items", a conventional commit with the slice title, and the PR size guard output in the PR body.

## PR slices

| # | Conventional-commit title | Branch | Base | Est. lines | Depends on | Critical | Model hint |
|---|---|---|---|---|---|---|---|
| 0 | `docs(openspec): add the v03-demo tasks` | `v03-demo-planning` (exists) | `dev` | 0 | none | no | Sonnet medium |
| 1a | `docs(decisions): add ADR 0013 on the release criterion and ADR 0011 on the turn deadline` | `v03-slice-01a-criterion` | `v03-demo-planning` | 220 | 0 | yes (criterion first) | Sonnet high |
| 1b | `docs(decisions): add ADRs 0009, 0010 and 0012 on the public demo` | `v03-slice-01b-records` | `v03-slice-01a-criterion` | 330 | 1a | no | Sonnet high |
| 2a | `feat(brain): add the turn deadline value and the turn_deadline_exceeded code` | `v03-slice-02a-deadline` | `v03-slice-01b-records` | 240 | 1a | yes (fingerprint) | Opus high |
| 2b | `feat(brain): end a turn at its deadline and validate the setting at startup` | `v03-slice-02b-turn-check` | `v03-slice-02a-deadline` | 300 | 2a | yes (no partial confirmation) | Opus high |
| 2c | `feat(brain): bound model retries by the turn deadline` | `v03-slice-02c-retry` | `v03-slice-02b-turn-check` | 330 | 2b | yes (unbounded wait) | Opus high |
| 2d | `feat(brain): add the attempt gate port and a statement timeout on the app engine` | `v03-slice-02d-gate-engine` | `v03-slice-02c-retry` | 280 | 2c | no | Opus high |
| 3 | `feat(erp): add a visitor customer write port` | `v03-slice-03-visitors` | `v03-slice-02d-gate-engine` | 300 | none | yes (least privilege) | Opus high |
| 4 | `feat(apps): add demo settings, the web mode switch and import contracts 13 and 14` | `v03-slice-04-demo-settings` | `v03-slice-03-visitors` | 325 | 2b | no | Opus high |
| 5a | `feat(db): add the demo schema` | `v03-slice-05a-demo-schema` | `v03-slice-04-demo-settings` | 250 | 4 | yes (grants) | Opus high |
| 5b | `test(db): pin the demo grants and keep migrations additive` | `v03-slice-05b-grants` | `v03-slice-05a-demo-schema` | 180 | 5a | yes (grants) | Opus high |
| 6a | `feat(apps): add the runtime price table and the reservation bound` | `v03-slice-06a-prices` | `v03-slice-05b-grants` | 300 | 5a | yes (spend cap) | Opus high |
| 6b | `feat(apps): add the spend ledger as the attempt gate` | `v03-slice-06b-ledger` | `v03-slice-06a-prices` | 330 | 6a, 2d | yes (spend cap) | Opus high |
| 7a | `feat(apps): add the kill switch and the pause and resume commands` | `v03-slice-07a-control` | `v03-slice-06b-ledger` | 260 | 5a | yes (kill switch) | Opus high |
| 7b | `feat(apps): add the operator status command` | `v03-slice-07b-status` | `v03-slice-07a-control` | 200 | 7a | no | Sonnet high |
| 8a | `feat(web): add the demo codes, the start command and the demo contract field` | `v03-slice-08a-demo-contract` | `v03-slice-07b-status` | 300 | 4 | no | Sonnet high |
| 8b | `feat(web): take the client IP only from the loopback proxy` | `v03-slice-08b-client-ip` | `v03-slice-08a-demo-contract` | 220 | 8a | yes (guard) | Opus high |
| 8c | `feat(web): add the demo session cookie` | `v03-slice-08c-session` | `v03-slice-08b-client-ip` | 280 | 8b | yes (session, CSRF) | Opus high |
| 9a | `refactor(web): pass the visitor through the registry port` | `v03-slice-09a-registry-port` | `v03-slice-08c-session` | 220 | 8a | no | Opus high |
| 9b | `feat(web): add the demo registry with caps, idle TTL and ownership` | `v03-slice-09b-demo-registry` | `v03-slice-09a-registry-port` | 330 | 9a, 8c | yes (isolation) | Opus high |
| 9c | `feat(web): count requests in flight and drain the demo registry` | `v03-slice-09c-drain` | `v03-slice-09b-demo-registry` | 240 | 9b | yes (reset safety) | Opus high |
| 9d | `feat(web): enforce the demo request order behind a policy port` | `v03-slice-09d-route-order` | `v03-slice-09c-drain` | 300 | 9c | yes (limits) | Opus high |
| 9e | `feat(apps): wire demo mode with visitor customers, the gate and the kill switch` | `v03-slice-09e-web-demo` | `v03-slice-09d-route-order` | 280 | 9d, 3, 6b, 7a | yes (verifier scope, spend) | Opus high |
| 10 | `feat(apps): add the session and IP daily counters` | `v03-slice-10-counters` | `v03-slice-09e-web-demo` | 320 | 9e | yes (limits) | Opus high |
| 11a | `feat(apps): save demo transcripts with usage and cost` | `v03-slice-11a-transcripts` | `v03-slice-10-counters` | 330 | 10 | yes (privacy) | Opus high |
| 11b | `feat(apps): add transcript purge and failure export` | `v03-slice-11b-purge-export` | `v03-slice-11a-transcripts` | 300 | 11a | yes (privacy) | Sonnet high |
| 12a | `feat(apps): add the demo scheduler tick` | `v03-slice-12a-scheduler` | `v03-slice-11b-purge-export` | 280 | 11a, 9c | no | Opus high |
| 12b | `feat(apps): add the nightly reset with pause and drain` | `v03-slice-12b-reset` | `v03-slice-12a-scheduler` | 320 | 12a | yes (no reseed under a live conversation) | Opus high |
| 13a | `feat(web): read the demo contract and derive the demo page states` | `v03-slice-13a-page-states` | `v03-slice-12b-reset` | 280 | 8a | no | Sonnet high |
| 13b | `feat(web): add the notice banner, accept step, conversation reference and state views` | `v03-slice-13b-page-notice` | `v03-slice-13a-page-states` | 330 | 13a | no | Sonnet high |
| 13c | `feat(web): serve the privacy page` | `v03-slice-13c-privacy` | `v03-slice-13b-page-notice` | 240 | 13b | no | Sonnet high |
| 14 | `build: add the image, Compose and Caddy files` | `v03-slice-14-packaging` | `v03-slice-13c-privacy` | 330 | 4 | yes (exposure) | Sonnet high |
| 15a | `feat(release): check the live report against the pre-registered criterion` | `v03-slice-15a-report-check` | `v03-slice-14-packaging` | 300 | 1a, 6a | yes (release gate) | Opus high |
| 15b | `feat(release): refuse a stale report, price drift or a changed case set` | `v03-slice-15b-stale-check` | `v03-slice-15a-report-check` | 240 | 15a | yes (release gate) | Opus high |
| 15c | `ci(release): add the tag-only release workflow and the image scan` | `v03-slice-15c-release-workflow` | `v03-slice-15b-stale-check` | 300 | 15b, 14 | yes (credentials) | Opus high |
| 16a | `feat(deploy): add the server deploy and rollback script` | `v03-slice-16a-server-deploy` | `v03-slice-15c-release-workflow` | 320 | 15c | yes (shell, SSH) | Opus high |
| 16b | `feat(deploy): add the owner deploy script and the smoke check` | `v03-slice-16b-owner-deploy` | `v03-slice-16a-server-deploy` | 320 | 16a | yes (shell, SSH) | Opus high |
| 17 | `docs: add the v0.3 runbook, release notes and READMEs` | `v03-slice-17-release` | `v03-slice-16b-owner-deploy` | 250 | all | no | Sonnet medium |

Parallelism: one writer at a time, and all slices stay stacked in table order (sequential). Slices 3, 13a, 13b, 13c, 14, 15a and 15b do not depend logically on the 6-12 chain, so they could be written earlier if the stack is reordered; the table order is the default.

## Hard gates (user-owned, never automated)

| Gate | Task | Why it waits |
|---|---|---|
| Privacy contact email and approval of the banner, accept and privacy wording | 13c.3 | Owner's words and a public address (proposal gate 4). It blocks the tag, not slices 14-16 |
| Buy the server | 17.5 | Spends money (D5) |
| Domain and DNS | 17.6 | D14 is pending; buying a domain spends money |
| Demo API workspace and key with its USD 15/month limit; key placed on the server | 17.7 | Account action and credential (D3, D7) |
| Paid live release eval with the owner's `ant` profile | 17.10 | Spends API credit; it must follow ADR 0013's commit (G3) |
| Merge the release PR `dev` to `main` | 17.12 | Explicit approval |
| Tag `v0.3` | 17.13 | Starts the release workflow and publishes the image |
| Public deploy | 17.14 | Acts on the public server (D2) |
| Resume the demo after the first deploy | 17.15 | The first deploy stays `paused, initial` until the owner has looked at it |

## Work units: tests, harness, rollback

| Unit | Focused test command | Runtime harness | Rollback boundary |
|---|---|---|---|
| 0 | `git diff --stat dev -- openspec/changes/v03-demo/` | N/A: documentation only | `openspec/changes/v03-demo/` |
| 1 | N/A: structural readback of each ADR | N/A: passive documents | the five new ADRs, 0009 to 0013 |
| 2 | `uv run pytest tests/unit/brain tests/unit/apps tests/integration/test_statement_timeout.py tests/integration/test_deadline_confirm.py` | `uv run pytest evals --model claude-haiku-5-5` and `--model claude-sonnet-5-5` replay unchanged; `DALE_TURN_DEADLINE_SECONDS=30 uv run python -m dale.apps.terminal` exits 2 | `deadline.py`, the `ModelRequest` field, the `TakeTurn` checks, the adapter loop, `app_engine` |
| 3 | `uv run pytest tests/integration/test_visitor_customers.py` | N/A: the port has no caller until 9e | the `VisitorCustomers` protocol, `visitors.py`, the SQL insert |
| 4 | `uv run pytest tests/unit/apps/demo tests/unit/test_web_app.py` and `uv run lint-imports` | `DALE_WEB_MODE=demo uv run python -m dale.apps.web` exits 2; local mode starts as in v0.2 | `src/dale/apps/demo/__init__.py`, `src/dale/apps/demo/settings.py`, the mode switch, the `web_demo.py` placeholder, contracts 4, 13 and 14 |
| 5 | `uv run pytest tests/integration/test_demo_migration.py tests/integration/test_demo_grants.py tests/unit/test_additive_migrations.py` | `uv run alembic upgrade head` then `uv run alembic check` on a throwaway database | migration 0006 (additive, so the previous image keeps working), `tables.py`, `env.py` |
| 6 | `uv run pytest tests/unit/apps/demo/test_prices.py tests/unit/apps/demo/test_reservation_bound.py tests/integration/test_spend_ledger.py` | N/A: the ledger has no caller until 9e | `prices.py`, `ledger.py` |
| 7 | `uv run pytest tests/integration/test_demo_control.py tests/unit/apps/demo/test_cli.py` | `uv run python -m dale.apps.demo pause`, `resume` and `status` against a throwaway database | `control.py`, `status.py`, `cli.py`, `__main__.py` |
| 8 | `uv run pytest tests/unit/channels/web tests/unit/test_pr_size_guard.py` | `uv run python -m dale.channels.web.schema_gen` leaves `git diff --exit-code contracts/` clean; a local host answers with no `Set-Cookie` | `errors.py`, `contract.py`, `demo.py`, `client.py`, `session.py`, guard step 2, `notice.json` |
| 9 | `uv run pytest tests/unit/channels/web tests/integration/test_web_demo.py` | demo host on a throwaway database with the replay model: two `curl` cookie jars create two conversations; a foreign cookie gets 404; no live model | the registry port, `registry.py`, the demo route branch, `web_demo.py` |
| 10 | `uv run pytest tests/integration/test_demo_counters.py` | same demo host: a 4th create from one cookie jar gets 429 | `counters.py` and the stub it replaces |
| 11 | `uv run pytest tests/integration/test_transcripts.py tests/integration/test_demo_purge_export.py tests/unit/test_ci_workflow.py` | `python -m dale.apps.demo export` with `--since`, `--only-failures` and `--out` set to a scratch directory writes a 0600 file | `transcripts.py`, the sink port and its calls, the CLI commands, the tracked-files rule |
| 12 | `uv run pytest tests/unit/apps/demo/test_scheduler.py tests/integration/test_nightly_reset.py` | demo host: `python -m dale.apps.demo reset`, then `status` shows `ok` and an old id gets 410 | `reset.py`, the scheduler start, the new `status` fields |
| 13 | `cd apps/web && npx vitest --run` and `uv run pytest tests/unit/channels/web/test_page_files.py` | built page served by the demo host in headless Chrome: banner, accept step and `/privacidad` (read-only) under the CSP; no message sent | `apps/web/src` demo components and copy, the privacy page, `page.py` |
| 14 | `uv run pytest tests/unit/test_deploy_files.py tests/unit/test_no_api_key_script.py` | `docker build` and a local Compose run with a throwaway database (14.4) | `Dockerfile`, `.dockerignore`, `deploy/compose.yml`, `deploy/Caddyfile`, `deploy/db/init.sh` |
| 15 | `uv run pytest tests/unit/test_check_release.py tests/unit/test_release_workflow.py tests/unit/test_scan_image.py` | `uv run python scripts/check_release.py` against a temporary repository; the real workflow runs only on the GATED tag (17.13) | `check_release.py`, `release.yml`, `workflow_call`, `scan_image.sh` |
| 16 | `uv run pytest tests/unit/test_dale_deploy.py tests/unit/test_deploy_sh.py` | stub `docker`, `ssh`, `gh`, `curl` and `nc` on `PATH`; the real deploy is GATED (17.14) | `deploy/server/dale-deploy.sh`, `deploy/deploy.sh`, `deploy/smoke.sh` |
| 17 | `uv run pytest` (full suite), `uv run lint-imports` and the `web` job commands | GATED live run, tag and deploy | `README.md`, `README.es.md`, `docs/runbook.md`, `docs/releases/v0.3.md` |

---

## Phase 0: Change artifacts (slice 0, 0 counted lines)

Covers: proposal, design §15. Branch `v03-demo-planning` already holds the change folder.
Model hint: Sonnet medium.

- [x] 0.1 Confirm `dev` equals `main` after the v0.2 release merge (`git rev-parse dev main`); fast-forward locally if not. No push without the user's usual approval.
  - Done 2026-11-26: `dev` (`2e8dbe6`) is ahead of `main` (`c5ff98c`) only by #125, the v0.2 archive (openspec, README links, release notes); no code, so no release is needed and the branch starts from `dev`.
- [x] 0.2 Commit `openspec/changes/v03-demo/tasks.md` on `v03-demo-planning` as `docs(openspec): add the v03-demo tasks`.
  - Done 2026-11-26 in `ff77325`.
- [x] 0.3 Closing: structural readback (passive docs), PR body with "Known pending items" (the list at the end of this file), size guard output (0 counted).
  - Done 2026-11-26: structural readback of the change folder; PR to `dev` with "Known pending items"; size guard 0 counted (`openspec/` excluded).

## Phase 1a: Release criterion and turn deadline records (slice 1a, ~220 lines) [critical: criterion first]

Covers: G3 (S3.1 proof starts), R9 (record), DD28-DD30, design §14, log D12, D18.
Model hint: Sonnet high.

- [ ] 1a.1 Write `docs/decisions/0013-release-eval-criterion.md` in its own commit, with no data in hand: hard gates at 0 (false confirmations, unexpected writes, `unverifiable` verdicts, applied exceptions in gauchadas), pass^3 of at least 35 of 40, valid only for a 40-case set, `live` and `record` reports accepted and `replay` refused, dated. Test: structural readback.
- [ ] 1a.2 Write `docs/decisions/0011-turn-deadline-bounded-retries.md`: DD28-DD30, the 90 s default above the 30 s verifier timeout, the 1 s minimum per attempt, HTTP 504; amends ADR 0004 D17 and B61. Test: structural readback.
- [ ] 1a.3 Verify no v0.3 report exists yet (`git ls-files evals/reports` lists no v0.3 file) and record the result in the PR body (G3 S3.1).
- [ ] 1a.4 Closing: blind review (focus: the criterion matches log D12 and release-gate G3 word for word), PR body with "Known pending items", size guard output.

## Phase 1b: Public demo records (slice 1b, ~330 lines)

Covers: DD26-DD27, DD31-DD46, log D1-D5, D15-D19, design §14.
Model hint: Sonnet high.

- [ ] 1b.1 Write `docs/decisions/0009-public-demo.md`: demo mode, visitor customers (supersedes B65 in demo mode only), caps and limits, spend cap and ledger, kill switch, in-process reset (DD26, DD27, DD31-DD33, DD37-DD40, DD43). Test: structural readback.
- [ ] 1b.2 Write `docs/decisions/0010-cookie-session-csrf-client-ip.md`: cookie session, CSRF without a token, client IP from the loopback proxy only (DD34-DD36); amends ADR 0005's no-cookie premise (W8). Test: structural readback.
- [ ] 1b.3 Write `docs/decisions/0012-hosting-release-deploy.md`: VPS with Compose and host Caddy, image by digest, tag-only release workflow, owner-run deploy, no key or SSH credential in CI, additive migrations (DD44-DD46, log D1-D3, D5). Test: structural readback.
- [ ] 1b.4 Closing: blind review (focus: no record contradicts ADRs 0004, 0005 or 0007), PR body with "Known pending items", size guard output.

## Phase 2a: Deadline value and the new brain code (slice 2a, ~240 lines) [critical: fingerprint]

Covers: R9 (S9.9), W11 (S11.1), W5 (S5.2, S5.3 regeneration), DD28, log D18.
Model hint: Opus high.

- [ ] 2a.1 RED in `tests/unit/brain/test_deadline.py`: `Deadline.after(seconds, monotonic)` reports `remaining()` and `expired()` on a fake clock; `None` seconds gives no deadline; two `ModelRequest`s that differ only in `deadline` are equal and `repr` omits it; `DeadlineExceededError` is a subclass of `ModelUnavailableError`.
- [ ] 2a.2 GREEN: `src/dale/brain/application/deadline.py`; `ModelRequest.deadline` (default `None`, `compare=False`, `repr=False`) and `DeadlineExceededError` in `src/dale/brain/application/model_port.py`. Satisfies DD28.
- [ ] 2a.3 RED then GREEN: `ErrorCode.TURN_DEADLINE_EXCEEDED` in `src/dale/shared/errors.py` with status 504 and a Spanish message; the catalog tests cover it (S11.1). Regenerate the contract schemas and TS types (generated, excluded from the count).
- [ ] 2a.4 Prove the prompt path is untouched: the fingerprint pin test passes unchanged, and both models replay every committed recording unchanged (S9.9).
- [ ] 2a.5 Closing: blind review (focus: `request_params`, `fingerprint` and `messages_digest` never read the deadline), PR body with "Known pending items", size guard output.

## Phase 2b: Turn check and the startup setting (slice 2b, ~300 lines) [critical: no partial confirmation]

Covers: R9 (S9.3, S9.7, S9.8, S9.11), v0.1 B75.
Model hint: Opus high.

- [ ] 2b.1 RED in `tests/unit/brain/test_take_turn_deadline.py`: with a fake model whose every call advances a fake clock by 40 s, a turn needing four calls ends at or before 90 s with `turn_deadline_exceeded`, no order and no `OrderConfirmed` (S9.3); completed exchanges are kept (v0.1 B75); a `DeadlineExceededError` from the model maps to `turn_deadline_exceeded`, caught before `ModelUnavailableError`; every `ModelRequest` carries the turn's deadline.
- [ ] 2b.2 GREEN in `src/dale/brain/application/take_turn.py`: `turn_seconds` and `monotonic` parameters, the check before each model call, and `_failed(TURN_DEADLINE_EXCEEDED, …)`.
- [ ] 2b.3 RED then GREEN in `tests/integration/test_deadline_confirm.py`: a turn that showed a proposal summary and then hit the deadline; typed "dale" confirms nothing, and the Dale action revalidates and confirms (S9.8).
- [ ] 2b.4 RED then GREEN: `turn_deadline(env)` in `src/dale/apps/compose.py` reads `DALE_TURN_DEADLINE_SECONDS` (default 90) and exits 2 when the value is invalid or not greater than the verifier's 30 s; `src/dale/apps/terminal.py` and `src/dale/apps/web.py` call it and pass `turn_seconds` to `TakeTurn`. Test in `tests/unit/apps/test_turn_deadline_setting.py` (S9.11).
- [ ] 2b.5 RED then GREEN: the terminal shows the `turn_deadline_exceeded` message and creates no order (S9.7), in the terminal session tests.
- [ ] 2b.6 Closing: blind review (focus: a deadline never yields a partial confirmation), PR body with "Known pending items", size guard output.

## Phase 2c: Bounded retry loop in the adapter (slice 2c, ~330 lines) [critical: unbounded wait]

Covers: R9 (S9.4, S9.5, S9.6, S9.9), DD29, log D18.
Model hint: Opus high.

- [ ] 2c.1 RED in `tests/unit/brain/test_anthropic_retry.py` (fake `anthropic` client that advances a fake clock, SDK errors built with `httpx.Response`, injected `sleep`): with 30 s left, `retry-after` 60 means no wait, no further request and `DeadlineExceededError` (S9.4); `retry-after` 5 means one 5 s wait and a retry (S9.5); a retryable failure on every attempt stops at 3 attempts with `ModelUnavailableError` (S9.6); under 1 s left sends nothing; `retry-after-ms` wins over `retry-after`; `x-should-retry: false` stops; a 400 is not retried; each attempt's timeout is `min(60, remaining)`; with no deadline a wait is capped at 30 s.
- [ ] 2c.2 GREEN in `src/dale/brain/infrastructure/anthropic_model.py`: `max_retries=0`, the own loop, injected `sleep` and `monotonic`. The client is still built with no arguments (the existing client-arguments test stays green).
- [ ] 2c.3 Replay both models unchanged, and test that `RecordingModel` marks a deadline as a failed run (S9.9).
- [ ] 2c.4 Closing: blind review (focus: no wait path escapes the deadline, SDK retries off), PR body with "Known pending items", size guard output.

## Phase 2d: Attempt gate port, app engine and statement timeout (slice 2d, ~280 lines)

Covers: R9 (S9.10), DD27 (port only), DD30, B61, log D15, D19.
Model hint: Opus high.

- [ ] 2d.1 RED then GREEN: `AttemptGate` and `AttemptTicket` in `src/dale/brain/application/model_port.py`; the adapter calls `admit` before each attempt and `settle(ticket, usage | None)` in `finally`; a `None` gate makes no call; a refused `admit` raises `ModelUnavailableError` and sends nothing; under 1 s left there is no `admit`. Test with a fake gate that records every attempt, retries included.
- [ ] 2d.2 RED then GREEN: `app_engine(url)` in `src/dale/apps/compose.py` (`statement_timeout=5000`, `lock_timeout=3000`, `idle_in_transaction_session_timeout=10000`, `connect_timeout=3`), used by `src/dale/apps/web.py` and `src/dale/apps/terminal.py`. Integration `tests/integration/test_statement_timeout.py`: `SHOW statement_timeout` gives 5 s, and a `pg_sleep(6)` on a tool's data path gives `rules_unavailable` and no order (S9.10).
- [ ] 2d.3 Restate the B61 comments: the page's no-abort comment in `apps/web/src/api/client.ts` and the server-side bound (deadline plus one tool round plus the 30 s verifier); the "no request timeout" pins stay (D17).
- [ ] 2d.4 Closing: blind review (focus: the gate port changes no request parameter), PR body with "Known pending items", size guard output.

## Phase 3: Visitor customer write port (slice 3, ~300 lines) [critical: least privilege]

Covers: W14 (S14.3 port side), DD31, log D4.
Model hint: Opus high.

- [ ] 3.1 RED in `tests/integration/test_visitor_customers.py`: `create_visitor` makes a customer with code `V-` plus 10 hex digits, a random UUID and the template's zone and name, with no orders; two calls give two customers; a unique conflict retries once and then raises; the existing reseed removes visitors and keeps the template.
- [ ] 3.2 GREEN: `VisitorCustomers` in `src/dale/erp_sim/public.py`, `create_visitor` in `src/dale/erp_sim/application/visitors.py`, `SqlVisitorCustomers` in `src/dale/erp_sim/infrastructure/facade.py` and the insert in `src/dale/erp_sim/infrastructure/repositories.py`. A test asserts `ErpFacade` gains no write method.
- [ ] 3.3 Closing: blind review (focus: the brain's `Tools` cannot reach the write port), PR body with "Known pending items", size guard output.

## Phase 4: Demo settings, web mode and import contracts (slice 4, ~325 lines)

Covers: O1 (S1.1, S1.2), W17 (local mode), DD26, design §2 (contracts 4, 13, 14).
Model hint: Opus high.

- [ ] 4.1 RED in `tests/unit/apps/demo/test_settings.py`: every O1 setting parses with its default; a missing privacy contact is an error (S1.1); a missing session secret or template code, an invalid limit, a cap of 0 or below, a non-positive retention, or a drain bound not above max(deadline + 5 + 30, 60 + 30) + 30 is an error, and the default drain bound is 240 s (S11.7); the secret never appears in `repr`.
- [ ] 4.2 GREEN: `src/dale/apps/demo/__init__.py` and `src/dale/apps/demo/settings.py`.
- [ ] 4.3 RED then GREEN in `src/dale/apps/web.py` (tests in `tests/unit/test_web_app.py`): `DALE_WEB_MODE` (`local` by default, or `demo`) and `DALE_WEB_PAGE_DIR` (default: the source checkout path). Demo mode exits 2 on invalid settings or a missing page directory, and exits 2 with "demo wiring not available" until slice 9e. Local mode reads no demo setting (S1.2).
- [ ] 4.4 Add a docstring-only `src/dale/apps/web_demo.py` so contract 13 names an existing module, then edit `pyproject.toml`: contract 4 gains `dale.apps.demo`; new contract 13 (`dale.apps.demo` may not import `dale.channels`, `dale.apps.web` or `dale.apps.web_demo`); new contract 14 (`dale.brain` and `dale.erp_sim` may not import `dale.apps`). Test: `uv run lint-imports` keeps 17 contracts; a deliberate violation is tried, fails, and is recorded in the PR body.
- [ ] 4.5 Closing: blind review (focus: local mode is byte-for-byte v0.2), PR body with "Known pending items", size guard output.

## Phase 5a: Demo schema (slice 5a, ~250 lines) [critical: grants]

Covers: design §5, DD33, O4 (ledger survives the reset), O11 (reseed never touches `demo`).
Model hint: Opus high.

- [ ] 5a.1 GREEN: `migrations/versions/0006_demo_schema.py` creates schema `demo` owned by `dale_owner`, the seven tables of §5 with their CHECKs, the control row seeded `paused, initial`, `REVOKE ALL ON SCHEMA demo FROM PUBLIC`, and `USAGE` plus per-table grants to `dale_app` only. Add `src/dale/apps/demo/tables.py` (`METADATA`); `migrations/env.py` adds `demo` to `SCHEMAS` and the metadata to the targets.
- [ ] 5a.2 RED then GREEN in `tests/integration/test_demo_migration.py`: `upgrade head` on an empty database works; `alembic check` reports no drift; the control row is `paused, initial`; the existing reseed leaves every `demo` table unchanged.
- [ ] 5a.3 Update the `db/roles.sql` header: no passwords in the file; dev and CI trust local connections; production's `deploy/db/init.sh` (slice 14) sets passwords from a root-only file. Test: structural readback.
- [ ] 5a.4 Closing: blind review (focus: no default privileges, verifier untouched), PR body with "Known pending items", size guard output.

## Phase 5b: Grant pins and additive-migration lint (slice 5b, ~180 lines) [critical: grants]

Covers: design §5 grants, R11 (unchanged), DD46, G8 (forward-only migrations).
Model hint: Opus high.

- [ ] 5b.1 RED then GREEN in `tests/integration/test_demo_grants.py`: `has_table_privilege` for `dale_app` equals §5 table by table; `dale_verifier` and `PUBLIC` have no `USAGE` on `demo` (`has_schema_privilege`).
- [ ] 5b.2 RED then GREEN in `tests/unit/test_additive_migrations.py`: a fixture revision from 0006 on with `DROP`, `RENAME`, `ALTER ... TYPE` or `SET NOT NULL` is rejected (one case each); the real 0006 passes.
- [ ] 5b.3 Closing: blind review, PR body with "Known pending items", size guard output.

## Phase 6a: Runtime prices and the reservation bound (slice 6a, ~300 lines) [critical: spend cap]

Covers: O4 (worst-case cost), G4 (S4.6 unit side), DD38, DD39.
Model hint: Opus high.

- [ ] 6a.1 RED in `tests/unit/apps/demo/test_prices.py`: `PRICES` equals the eval pricing file loaded through the eval harness's `load_pricing` (same model set, tiers, threshold and `retrieved`) (S4.6).
- [ ] 6a.2 GREEN: `src/dale/apps/demo/prices.py` (Decimal values per model).
- [ ] 6a.3 RED then GREEN in `src/dale/apps/demo/ledger.py` (pure functions): `prompt_bound` (UTF-8 bytes of canonical JSON of system, tools and messages, plus 2,000), `reserve_micros` at the tier the bound selects with `max(input, cache_write_5m)` and `max_tokens × output`, rounded up; `cost_micros(usage)`; the reference request. Table tests include the tier threshold boundary.
- [ ] 6a.4 RED then GREEN in `tests/unit/apps/demo/test_reservation_bound.py`: for every committed recording, the reservation is at least the actual cost from `message.usage` (design §13 assumption).
- [ ] 6a.5 Closing: blind review (focus: rounding always up, integer micro-USD), PR body with "Known pending items", size guard output.

## Phase 6b: Spend ledger as the attempt gate (slice 6b, ~330 lines) [critical: spend cap]

Covers: O4 (S4.1-S4.7), DD27, DD38, design §12 (per-attempt log line).
Model hint: Opus high.

- [ ] 6b.1 RED in `tests/integration/test_spend_ledger.py` (real Postgres, frozen clock): under the cap a request is admitted and settled at its actual cost (S4.1); at the cap it is refused and nothing is sent (S4.2); a new ledger object after a restart sees the committed spend (S4.3); two threads with room for one admit exactly one (S4.4); an unreadable ledger refuses (S4.5); unknown usage settles at the reservation (S4.6); the day changes at Buenos Aires midnight (S4.7); a crash between reserve and settle keeps the reservation; room for the reference request is false at the cap.
- [ ] 6b.2 GREEN: `SqlSpendLedger` in `src/dale/apps/demo/ledger.py` (atomic conditional update on `demo.spend_day`, `spend_request` rows, settle).
- [ ] 6b.3 RED then GREEN: one JSON log line per attempt (outcome, tokens, cost, wait) and no customer text (caplog).
- [ ] 6b.4 Closing: blind review (focus: atomic reserve, fail closed on every error), PR body with "Known pending items", size guard output.

## Phase 7a: Kill switch, pause and resume (slice 7a, ~260 lines) [critical: kill switch]

Covers: O5 (S5.1, S5.5 store side), O6 (S6.2, S6.3), DD33.
Model hint: Opus high.

- [ ] 7a.1 RED in `tests/integration/test_demo_control.py`: the store reads `paused` and `reason`; an unreadable row raises a typed error; a `reset` or `deploy` pause applies only `WHERE NOT paused`; `resume(if_reason)` resumes only its own reason; an operator pause survives a deploy resume (S5.1, S5.5).
- [ ] 7a.2 GREEN: `src/dale/apps/demo/control.py`.
- [ ] 7a.3 RED then GREEN: `src/dale/apps/demo/cli.py` and `src/dale/apps/demo/__main__.py` with `pause [--reason operator|deploy]` and `resume [--if-reason R]`. Tests of `main(argv)` in `tests/unit/apps/demo/test_cli.py`: a second `pause` succeeds and the state stays paused (S6.3); a failed write exits non-zero with a message (S6.2); nothing prints a key, IP or session.
- [ ] 7a.4 Closing: blind review (focus: no path resumes an operator pause), PR body with "Known pending items", size guard output.

## Phase 7b: Operator status (slice 7b, ~200 lines)

Covers: O6 (S6.1, first fields).
Model hint: Sonnet high.

- [ ] 7b.1 RED in `tests/unit/apps/demo/test_cli.py`: `status` prints the control state and reason, today's and this month's spend against the cap, and open and unknown reservations; it prints no customer text, IP, session or key.
- [ ] 7b.2 GREEN: `src/dale/apps/demo/status.py` and the `status` command in `src/dale/apps/demo/cli.py`.
- [ ] 7b.3 Closing: blind review, PR body with "Known pending items", size guard output.

## Phase 8a: Demo codes, start command and contract field (slice 8a, ~300 lines)

Covers: W5 (S5.5), W11 (S11.1, S11.4), O7 (S7.2 type level), DD42.
Model hint: Sonnet high.

- [ ] 8a.1 RED in `tests/unit/channels/web/test_demo_contract.py`: `rate_limited` 429, `demo_paused` 503, `demo_busy` 503, `demo_reset` 410 and `notice_not_accepted` 403, each with a Spanish message, disjoint from `ErrorCode` and never in a shown event (S11.1, S11.4); `StartConversation{notice_version}` rejects unknown fields; `GET /v1/contract` (read-only) reports `demo: null` in local mode and `{notice_version, retention_days}` in demo mode.
- [ ] 8a.2 GREEN: `src/dale/channels/web/errors.py`, `src/dale/channels/web/contract.py` (`StartConversation`, the `demo` field), new `src/dale/channels/web/demo.py` (`NOTICE`, `Visitor`), and `src/dale/channels/web/app.py`.
- [ ] 8a.3 GREEN: `src/dale/channels/web/schema_gen.py` writes `contracts/v1/notice.json`; regenerate the schemas and TS types; `scripts/check_pr_size.py` excludes `contracts/v1/notice.json`, with a case in `tests/unit/test_pr_size_guard.py`; a test pins `notice.json` to `NOTICE`.
- [ ] 8a.4 RED then GREEN in `tests/unit/channels/web/test_contract_additive.py`: every field, event type and code of the schemas at tag `v0.2` (read with `git show`) still exists in v0.3 with the same meaning, and the version is 1 (S5.5).
- [ ] 8a.5 Closing: blind review (focus: additive only), PR body with "Known pending items", size guard output.

## Phase 8b: Client IP from the loopback proxy (slice 8b, ~220 lines) [critical: guard]

Covers: W8 (S8.5, S8.6, S8.7, S8.9, S8.10 IP half), O3 (S3.6 logs), DD36.
Model hint: Opus high.

- [ ] 8b.1 RED in `tests/unit/channels/web/test_client_ip.py`: from peer `127.0.0.1` or `::1`, `X-Forwarded-For: 198.51.100.9, 203.0.113.7` gives `203.0.113.7` (S8.5); a non-loopback peer ignores the header and uses the peer (S8.6); an empty, garbage or missing value gives none; IPv6 parses.
- [ ] 8b.2 RED (`TestClient` with `client=`): demo mode with a loopback peer and no header gets `invalid_request` before any handler (S8.7); `Host: evil.example` with an allowed `X-Forwarded-Host` is rejected (S8.9); local mode ignores the header (S8.10); no log line holds a clear IP (caplog, S3.6).
- [ ] 8b.3 GREEN: `src/dale/channels/web/client.py` and guard step 2 in `src/dale/channels/web/guard.py` (demo flag); the uvicorn `proxy_headers=False` pin stays.
- [ ] 8b.4 Closing: blind review (focus: only the proxy-appended value is trusted), PR body with "Known pending items", size guard output.

## Phase 8c: Session cookie (slice 8c, ~280 lines) [critical: session, CSRF]

Covers: W8 (S8.8, S8.10 cookie half), O2 (S2.1, S2.3, S2.4), DD34, DD35.
Model hint: Opus high.

- [ ] 8c.1 RED in `tests/unit/channels/web/test_session.py`: a request with no cookie gets `__Host-dale_session` with `HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=86400` (S8.8, S2.1); only `POST /v1/conversations` (read-only) issues it, and a `GET` of the page, `/privacidad` or a static file with no cookie sets none (S2.3); a request carrying a valid cookie that arrives cross-site without it leaves the existing session untouched (S2.4); the token is 32 random bytes in base64url; a malformed cookie on a create gets a new one, and on any other route gets `conversation_not_found`; the stored subject is HMAC-SHA256 of `"session|" + token`, and the raw token is never stored or logged; local mode sets no cookie on any route (S8.10); no GET route changes state.
- [ ] 8c.2 GREEN: `src/dale/channels/web/session.py`, wired for demo mode in `src/dale/channels/web/app.py`.
- [ ] 8c.3 Closing: blind review (focus: CSRF closed by two independent checks on every path), PR body with "Known pending items", size guard output.

## Phase 9a: Visitor through the registry port (slice 9a, ~220 lines)

Covers: W17 (S17.1, S17.2, S17.6), DD43.
Model hint: Opus high.

- [ ] 9a.1 RED in `tests/unit/channels/web/test_conversations.py` (existing cases unchanged): `create(visitor=None)` and `using(id, None)` yield the conversation or `conversation_not_found`; a second create retires the first (S17.6); a test registry implementing the new port runs the host with no route change (S17.1).
- [ ] 9a.2 GREEN: the port and `InMemoryRegistry` in `src/dale/channels/web/conversations.py` and their callers in `src/dale/channels/web/routes.py`, in one commit. The whole v0.2 web suite passes unchanged, restart test included (S17.2, S17.6).
- [ ] 9a.3 Closing: blind review (focus: the `types` job sees no half change), PR body with "Known pending items", size guard output.

## Phase 9b: Demo registry caps, TTL, ownership and tombstones (slice 9b, ~330 lines) [critical: isolation]

Covers: W17 (S17.3, S17.4), O2 (S2.2), O3 (S3.2).
Model hint: Opus high.

- [ ] 9b.1 RED in `tests/unit/channels/web/test_demo_registry.py` (fake clock): an 11th create gets `demo_busy` and the 10 stay live (S17.3); idle 29 minutes is live, 30 minutes gets `conversation_not_found` and frees the slot (S17.4); another session's id gets `conversation_not_found` (S2.2); a new conversation from the same session ends its earlier one; a 21st customer turn gets `rate_limited` (S3.2); a tombstone answers `demo_reset`, capped at 10,000.
- [ ] 9b.2 GREEN: `DemoRegistry` in `src/dale/channels/web/registry.py`.
- [ ] 9b.3 Closing: blind review (focus: one mutex guards every map), PR body with "Known pending items", size guard output.

## Phase 9c: In-flight count and drain (slice 9c, ~240 lines) [critical: reset safety]

Covers: W17 (S17.5), O11 (S11.2 registry side), DD43.
Model hint: Opus high.

- [ ] 9c.1 RED in `tests/unit/channels/web/test_demo_drain.py` (threads, `threading.Event`): `using` counts on entry and uncounts in `finally`, also on an exception; the TTL sweep skips work in flight (S17.5); after `begin_drain`, a new `using` is refused with no gap; `wait_idle` returns true at zero and false on timeout; `end_all` leaves tombstones; `reopen` admits again.
- [ ] 9c.2 GREEN in `src/dale/channels/web/registry.py`.
- [ ] 9c.3 Closing: blind review (focus: admission and the drain flag share the mutex), PR body with "Known pending items", size guard output.

## Phase 9d: Demo request order and policy port (slice 9d, ~300 lines) [critical: limits]

Covers: design §4 steps 4-9, O2 (S2.2 routes), O3 (S3.4), O5 (S5.4), O7 (S7.2, S7.3), W11 (S11.5).
Model hint: Opus high.

- [ ] 9d.1 RED in `tests/unit/channels/web/test_demo_routes.py` (fake policy and registry): `{}` gets `notice_not_accepted`, also while paused (S7.2); an older version gets `notice_not_accepted` (S7.3); an unknown field gets `invalid_request`; paused gets `demo_paused`; a 5th concurrent turn gets `demo_busy` (S3.4); a locked conversation gets `conversation_busy`; a step-8 refusal gets `rate_limited`, releases the turn slot and leaves the turn count; a rejection calls no backend; presses skip steps 4, 7 and 8; a `rate_limited` body has only code and message (S11.5); another session's press gets `conversation_not_found` (S2.2); the route table is unchanged and no route reads the control state (S5.4).
- [ ] 9d.2 GREEN: the `DemoPolicy` port in `src/dale/channels/web/demo.py` and the demo branch in `src/dale/channels/web/routes.py`; the local branch is untouched.
- [ ] 9d.3 Closing: blind review (focus: counting runs last and every acquired slot is released), PR body with "Known pending items", size guard output.

## Phase 9e: Demo wiring (slice 9e, ~280 lines) [critical: verifier scope, spend]

Covers: W14 (S14.1, S14.3-S14.6), O1 (S1.2), O4 (S4.2, S4.5, S4.8), O5 (S5.1-S5.3, S5.5), O7 (S7.2), log D15.
Model hint: Opus high.

- [ ] 9e.1 RED in `tests/integration/test_web_demo.py` (real Postgres, replay model, real verifier subprocess): two conversations get two visitor customers in zone Centro with no orders (S14.1, S14.3); two presses at once both get `verified`, no `unexpected_write`, and both stay live (S14.4); a failed visitor insert returns the envelope, creates no conversation and binds no other customer (S14.5); `notice_not_accepted` creates no visitor (S7.2).
- [ ] 9e.2 RED: startup exits 2 when the template customer is missing (S14.6), when the model has no entry in `PRICES` (S4.8), or when `retention_days` differs from `NOTICE.retention_days`.
- [ ] 9e.3 RED: a pause makes the next turn `demo_paused` with no model call (S5.1); an unreadable control row gives `demo_paused` for a turn and a press (S5.2, S4.5); a pause between two calls of one turn sends no second call and ends as `model_unavailable` with no order (S5.3); at the cap the next request gets `demo_paused` (S4.2); a resume lets the next turn run (S5.5).
- [ ] 9e.4 GREEN: `src/dale/apps/web_demo.py` (visitor backends, a gate that checks control and then `SqlSpendLedger`, the step-6 policy adapter); step-8 counters answer `demo_paused` (fail closed) until slice 10. `src/dale/apps/web.py` hands demo mode over and drops the slice-4 exit. A test proves local mode reads no control, ledger or session (S1.2).
- [ ] 9e.5 Closing: blind review (focus: verifier run scope unchanged, no shared-customer fallback), PR body with "Known pending items", size guard output.

## Phase 10: Session and IP daily counters (slice 10, ~320 lines) [critical: limits]

Covers: O3 (S3.1, S3.3, S3.5, S3.6 database, S3.7), DD37, log D17.
Model hint: Opus high.

- [ ] 10.1 RED in `tests/integration/test_demo_counters.py`: a 4th conversation from one session gets `rate_limited` and no visitor (S3.1); a 61st turn from `203.0.113.7` across sessions gets `rate_limited` (S3.3); an 11th conversation from that IP with cleared cookies gets `rate_limited` and no visitor (S3.7); the session and IP counters roll back together; a store error gives `demo_paused` with no model call (S3.5); no `counter` row holds the clear IP, and the IP key changes by day (S3.6).
- [ ] 10.2 GREEN: `src/dale/apps/demo/counters.py`; it replaces the fail-closed stub in `src/dale/apps/web_demo.py`.
- [ ] 10.3 Closing: blind review (focus: one transaction per create, no slot consumed on refusal), PR body with "Known pending items", size guard output.

## Phase 11a: Transcripts (slice 11a, ~330 lines) [critical: privacy]

Covers: O9 (S9.1, S9.2), O7 (accepted version stored), O3 (S3.6 transcripts and logs), DD40, design §12.
Model hint: Opus high.

- [ ] 11a.1 RED in `tests/integration/test_transcripts.py`: after a turn and a press, the transcript holds the head row (session hash, notice version), customer text, shown events, trace, verdict and usage rows with cost (S9.1); no row holds an IP, user agent, raw token, cookie or header (S9.2, S3.6); a failing sink leaves the reply unchanged and increments the failure counter.
- [ ] 11a.2 GREEN: the `TranscriptSink` port in `src/dale/channels/web/demo.py`, its calls in `src/dale/channels/web/routes.py`, the SQL writer in `src/dale/apps/demo/transcripts.py`, and the adapter in `src/dale/apps/web_demo.py`.
- [ ] 11a.3 RED then GREEN: one JSON log line per `/v1` (read-only) request (route kind, status, code, conversation id, 8-hex session prefix, latency, calls, tokens, cost); caplog shows no customer text, IP or user agent.
- [ ] 11a.4 Closing: blind review (focus: nothing identifying is written), PR body with "Known pending items", size guard output.

## Phase 11b: Purge and failure export (slice 11b, ~300 lines) [critical: privacy]

Covers: O9 (S9.3, S9.4, S9.5, S9.6 purge side), O10 (S10.1, S10.2).
Model hint: Sonnet high.

- [ ] 11b.1 RED in `tests/integration/test_demo_purge_export.py`: `purge --expired` with transcripts aged 31 and 29 days deletes only the first (S9.3); `purge --conversation <ref>` leaves none of its rows and keeps the others (S9.4, S9.6); the export of one verified and one `mismatch` conversation holds only the second (S10.1); a `--since` before retention shows no purged conversation (S10.2); the file is named dale-export-DATE.jsonl, mode 0600, with no field O9 forbids.
- [ ] 11b.2 GREEN: `purge` and `export` in `src/dale/apps/demo/cli.py` and `src/dale/apps/demo/transcripts.py`.
- [ ] 11b.3 RED then GREEN: the `tracked-files` job in `.github/workflows/ci.yml` fails on any tracked JSONL file outside evals/recordings/; `.gitignore` gains the pattern dale-export-*.jsonl; `tests/unit/test_ci_workflow.py` asserts the rule (S9.5).
- [ ] 11b.4 Closing: blind review, PR body with "Known pending items", size guard output.

## Phase 12a: Scheduler tick (slice 12a, ~280 lines)

Covers: O9 (S9.3 nightly), O11 (tick), W17 (TTL sweep), design §6.
Model hint: Opus high.

- [ ] 12a.1 RED in `tests/unit/apps/demo/test_scheduler.py` (fake clock): each tick writes the heartbeat and runs the TTL sweep; `purge_expired` runs once per Buenos Aires day, also after a failed reset; a tick's exception is caught; a dead thread makes policy step 6 answer `demo_paused`; a scheduler that does not start makes the host exit 2.
- [ ] 12a.2 GREEN: the scheduler in `src/dale/apps/demo/reset.py` with its own `Drain` protocol (contract 13), the heartbeat write in `src/dale/apps/demo/status.py`, and the start in `src/dale/apps/web_demo.py`.
- [ ] 12a.3 Closing: blind review, PR body with "Known pending items", size guard output.

## Phase 12b: Nightly reset (slice 12b, ~320 lines) [critical: no reseed under a live conversation]

Covers: O11 (S11.1-S11.7), O6 (S6.1 remaining fields), DD32, DD33.
Model hint: Opus high.

- [ ] 12b.1 RED in `tests/integration/test_nightly_reset.py` (threads, fake clock, real Postgres): with none in flight, conversations end, ids get `demo_reset`, visitors are gone, the template stays and the demo resumes (S11.1); a turn in flight delays the reseed until it ends and a request meanwhile gets `demo_paused` (S11.2); a drain timeout runs no reseed, stays paused and records `drain_timeout` (S11.3); the startup refusal for a drain bound at or below max(deadline + 5 + 30, 60 + 30) + 30, which is also covered in 4.1 (S11.7); a failing reseed stays paused and `status` reports it (S11.4); an operator pause survives (S11.5); ledger and transcripts are unchanged (S11.6); a failed step-1 write changes nothing and retries after 5 minutes; a missed 04:00 runs at the first tick.
- [ ] 12b.2 GREEN: the reset steps in `src/dale/apps/demo/reset.py` and the `reset` command (sets `reset_requested_at`) in `src/dale/apps/demo/cli.py`.
- [ ] 12b.3 RED then GREEN: the remaining `status` fields in `src/dale/apps/demo/status.py`: heartbeat age ("host not reporting" after 2 minutes), live conversations, turns today, failures in the last 24 hours, last reset result, transcript and reset failures (S6.1).
- [ ] 12b.4 Closing: blind review (focus: the reseed runs only at zero in flight with every conversation ended), PR body with "Known pending items", size guard output.

## Phase 13a: Demo contract and page states (slice 13a, ~280 lines)

Covers: W19 (S19.1, S19.2 reducer), W5 (S5.3).
Model hint: Sonnet high.

- [ ] 13a.1 RED in `apps/web/src/state/reducer.test.ts` and `apps/web/src/api/client.test.ts`: the page reads `GET /v1/contract` (read-only) on load; each of the six codes derives its own `blocked` state; `demo_reset` clears `pendingProposalId` and offers a new conversation; the `demo` field sets the notice state.
- [ ] 13a.2 GREEN: `apps/web/src/api/client.ts` and `apps/web/src/state/reducer.ts`; the generated TS type test still compiles over the samples (S5.3).
- [ ] 13a.3 Closing: blind review, PR body with "Known pending items", size guard output.

## Phase 13b: Notice, accept step, reference and state views (slice 13b, ~330 lines)

Covers: W19 (S19.1, S19.2, S19.3), O7 (S7.1), O9 (S9.6 page side).
Model hint: Sonnet high.

- [ ] 13b.1 RED (Vitest and Testing Library): each code shows its own Spanish state as text (S19.1); after `demo_reset` the Dale button is disabled and a new conversation is offered (S19.2); the banner shows in every state and links to `/privacidad` (read-only) (S7.1); the accept step sends `{notice_version}`; the reference shows `conversation_id` (S9.6); the trace panel lists tools in demo mode (S19.3); local mode shows no banner.
- [ ] 13b.2 GREEN: `apps/web/src/components/NoticeBanner.tsx`, `apps/web/src/components/AcceptNotice.tsx`, `apps/web/src/components/DemoState.tsx`, `apps/web/src/components/ConversationReference.tsx`, copy in `apps/web/src/i18n/es.ts`, wiring in `apps/web/src/features/ConversationContainer.tsx`. Lint passes (no raw HTML sink).
- [ ] 13b.3 Closing: blind review, PR body with "Known pending items" (the wording waits for 13c.3), size guard output.

## Phase 13c: Privacy page (slice 13c, ~240 lines)

Covers: O8 (S8.1), O9 (S9.6 privacy side), DD41.
Model hint: Sonnet high.

- [ ] 13c.1 RED in `tests/unit/channels/web/test_page_files.py`: `/privacidad` (read-only) and `/privacidad/` (read-only) return 200 with the CSP, the retention days and the HTML-escaped contact, with no redirect; the page states the purpose, what is stored, that IP and user agent are not stored, and asks for the conversation reference (S8.1, S9.6); no inline style or script; local mode is unchanged.
- [ ] 13c.2 GREEN: `apps/web/public/privacidad/index.html`, `apps/web/public/privacidad/privacidad.css`, `PageFiles` in `src/dale/channels/web/page.py`, and the mount swap in `src/dale/channels/web/app.py`.
- [ ] 13c.3 **GATED (user)**: the owner provides the privacy contact alias (it goes in the server settings only, never in a tracked file) and approves the banner, accept and privacy wording. A wording change bumps `NOTICE.version` and regenerates `contracts/v1/notice.json`. Never automated.
- [ ] 13c.4 Closing: blind review, PR body with "Known pending items", size guard output.

## Phase 14: Image, Compose and Caddy (slice 14, ~330 lines) [critical: exposure]

Covers: G6 (S6.3), G7 (no key names), G9 (S9.1 Compose side), DD44, design §9.
Model hint: Sonnet high.

- [ ] 14.1 RED in `tests/unit/test_deploy_files.py`: `db` publishes only `127.0.0.1:5432:5432`; `app` runs on `network_mode: host` with `read_only`, `cap_drop: [ALL]`, `no-new-privileges`, `stop_grace_period: 150s` and `env_file` paths under the root-only /etc/dale directory on the server; `migrate` is in profile `ops`; every image is pinned by digest; the Caddyfile has HSTS `max-age=31536000`, `request_body max_size 16KB`, `reverse_proxy 127.0.0.1:8000` and no response timeout; the Dockerfile runs as user 10001 with `DALE_WEB_PAGE_DIR=/app/page`; `.dockerignore` is an allow-list.
- [ ] 14.2 GREEN: `Dockerfile`, `.dockerignore`, `deploy/compose.yml`, `deploy/Caddyfile`, `deploy/db/init.sh`.
- [ ] 14.3 RED then GREEN: `scripts/check_no_api_key.sh` today scans only `*.py *.sh *.toml *.yml *.yaml *.cfg *.ini *.json *.jsonl` outside `openspec`, with assignment-shaped patterns; extend it to `Dockerfile`, `deploy/Caddyfile`, `.env*`, `.dockerignore` and the extensionless scripts under `deploy/`, with cases in `tests/unit/test_no_api_key_script.py` (a key-shaped assignment in each new file kind fails; Markdown stays unread).
- [ ] 14.4 Runtime harness (local, no key, no model call): build the image and run it with a throwaway database; the page is served with no source tree mounted (S6.3), and `ss -ltn` shows the app and Postgres on `127.0.0.1` only (S9.1). Results go in the PR body.
- [ ] 14.5 Closing: blind review (focus: nothing listens on a public interface, no key name in any file), PR body with "Known pending items", size guard output.

## Phase 15a: Live report and criterion check (slice 15a, ~300 lines) [critical: release gate]

Covers: G4 (S4.1-S4.5), G3 (S3.2 report side, S3.4, S3.7), threat matrix (Git repository selection).
Model hint: Opus high.

- [ ] 15a.1 RED in `tests/unit/test_check_release.py` (temporary git repositories): gates at 0 and pass^3 36 of 40 pass (S4.1); a missing report fails (S4.2); one false confirmation fails (S4.3); 34 of 40 fails (S4.4); `replay` fails while `live` and `record` pass (S4.5); a `-dirty` commit, a model other than `MODEL_SETTINGS.model`, empty `snapshot_ids` or `pass_3.cases` other than 40 fail (S3.2); `gates.disallowed_writes` 0 with `metrics.unexpected_writes` 1, or the reverse, fails (S3.7); of two reports for the same commit the newer by adding commit is the one read (S3.4). Threat cases: a `commit` value holding `--upload-pack=…` text and a malformed tag are refused before any git call.
- [ ] 15a.2 GREEN: `scripts/check_release.py` (fixed argv, no shell, `cwd` from `__file__`, 40-hex commit and tag regex).
- [ ] 15a.3 Closing: blind review (focus: every field is checked, nothing defaults to pass), PR body with "Known pending items", size guard output.

## Phase 15b: Stale report, prices, case count and history (slice 15b, ~240 lines) [critical: release gate]

Covers: G5 (S5.1-S5.4), G4 (S4.6), G3 (S3.1, S3.2, S3.5, S3.6), threat matrix (literal pathspecs).
Model hint: Opus high.

- [ ] 15b.1 RED in `tests/unit/test_check_release.py`: only `README.md` and release notes changed after the report commit passes (S5.1); a changed file in the `dale` package fails (S5.2); a changed `db/roles.sql` fails (S5.4); a report commit that is not an ancestor fails (S5.3); a runtime price that differs from the eval pricing file fails (S4.6); 41 case files fail (S3.2); ADR 0013's commit after the first report commit fails (S3.1); a changed case file or `evals/harness/grader.py` between ADR 0013's commit and the report commit fails with no decision record added under `docs/decisions/` in that range and passes this rule with one (S3.5, S3.6); pathspecs after `--` are literal (a path named `:(glob)*` matches only itself).
- [ ] 15b.2 GREEN in `scripts/check_release.py`: the guarded-path constant (the script itself and `db/roles.sql` included), the measurement-path rule, `git diff --quiet <commit> <tag> -- …`, the price comparison, the case count and the history order.
- [ ] 15b.3 Closing: blind review (focus: the guarded paths, including `db/roles.sql`, match design §9), PR body with "Known pending items", size guard output.

## Phase 15c: Release workflow and image scan (slice 15c, ~300 lines) [critical: credentials]

Covers: G1 (S1.1-S1.3), G2 (S2.1, S2.2), G6 (S6.1, S6.2), G7 (S7.1, S7.2), threat matrix (push state).
Model hint: Opus high.

- [ ] 15c.1 RED in `tests/unit/test_release_workflow.py`: the only trigger is `push: tags: ['v*']` (S1.3); jobs run `on-main` → `ci` → `report` → `image` → `release` through `needs` (S1.1, S1.2, S2.1); the tag is checked against the regex before use; `packages: write` only on `image` and `contents: write` only on `release`; only `GITHUB_TOKEN`, no `ssh` and no other secret (S7.2); evals stay offline and no step names the model API (S2.2); the digest goes in the release body (S6.1).
- [ ] 15c.2 GREEN: `.github/workflows/release.yml` and `workflow_call` in `.github/workflows/ci.yml`; `tests/unit/test_ci_workflow.py` updated.
- [ ] 15c.3 RED then GREEN: `scripts/scan_image.sh` with `tests/unit/test_scan_image.py` over fixture filesystems: a `sk-ant-` value, a .env file and a dale-export file each fail; a clean tree passes (S6.2).
- [ ] 15c.4 RED then GREEN in `tests/unit/test_no_api_key_script.py`: a workflow fixture naming an Anthropic key secret fails the script (S7.1); the real `.github/workflows/release.yml` passes.
- [ ] 15c.5 Closing: blind review (focus: no path to a key or the server from CI), PR body with "Known pending items", size guard output.

## Phase 16a: Server deploy and rollback (slice 16a, ~320 lines) [critical: shell, SSH]

Covers: G8 (S8.1 server half, S8.3, S8.4, S8.5), threat matrix (shell and SSH).
Model hint: Opus high.

- [ ] 16a.1 RED in `tests/unit/test_dale_deploy.py` (stub `docker` and `curl` on `PATH` that log argv): `v0.3;rm -rf /`, a digest with a newline and an empty previous on rollback are refused before any `docker` call; a first deploy skips the pause and stays `paused, initial`; a digest mismatch starts nothing (S8.5); a failed migration runs `resume --if-reason deploy`, exits 1 and keeps the old image serving (S8.3); success checks local `/health` (read-only) with `Host` and `X-Forwarded-For` and records `current` and `previous`; `rollback` starts the previous version and checks it, or stops the app when there is none (S8.4).
- [ ] 16a.2 GREEN: `deploy/server/dale-deploy.sh` (`set -euo pipefail`, no `eval`, quoted arguments).
- [ ] 16a.3 Closing: blind review (focus: every argument validated before use), PR body with "Known pending items", size guard output.

## Phase 16b: Owner deploy and smoke check (slice 16b, ~320 lines) [critical: shell, SSH]

Covers: G8 (S8.1, S8.2), G9 (S9.1-S9.3), G6 (S6.3 public side), threat matrix (shell and SSH).
Model hint: Opus high.

- [ ] 16b.1 RED in `tests/unit/test_deploy_sh.py` (stub `gh`, `ssh`, `curl` and `nc`): a bad version is refused before `gh` or `ssh`; a release body with two digests or none is refused; the only remote command is sudo /opt/dale/dale-deploy with the version and digest (a server path, not a repository file), sent to the destination in `DALE_DEPLOY_SSH`; a passing smoke runs `resume --if-reason deploy` except on a first deploy (S8.1); a failing smoke runs `rollback`, smokes again, resumes only if that passes, and exits 1 (S8.2).
- [ ] 16b.2 RED in `tests/unit/test_deploy_sh.py` for the smoke: missing HSTS fails (S9.3); `{}` not answering `notice_not_accepted` (local mode) fails (S9.2); HTTP not answering 301 or 308 fails; no CSP on `/` (read-only) fails (S6.3); a connectable port 8000 or 5432 fails (S9.1); the smoke calls only health, the page and the create route with `{}`.
- [ ] 16b.3 GREEN: `deploy/deploy.sh` and `deploy/smoke.sh`.
- [ ] 16b.4 Closing: blind review (focus: the smoke never reaches the model, resume only after a passing smoke), PR body with "Known pending items", size guard output.

## Phase 17: Docs, live report, release and deploy (slice 17, ~250 lines)

Covers: proposal Success Criteria, G1 (S1.1), G3 (S3.1), G5, G6 (S6.1), G8 (S8.1), G9 (S9.1), hard gates. Nothing past 17.4 runs without the user except 17.9 and 17.11.
Model hint: Sonnet medium.

- [ ] 17.1 Update `README.md` and `README.es.md`: local and demo modes, the demo link (placeholder until D14), the notice; the fiction notice stays. Test: the README tests pass, and reading both end to end.
- [ ] 17.2 Write `docs/runbook.md`: server setup, the variable names of the root-only env files (markdown only), installing `dale-deploy`, `pause`, `resume`, `status`, `reset`, `purge` on request, `export`, the uptime check, and the incident order (pause, disable the key, stop Compose, remove DNS).
- [ ] 17.3 Write `docs/releases/v0.3.md`: scope, known pending, and a marked placeholder for the live report result.
- [ ] 17.4 Run the full suite on the slice head: `uv run pytest`, both models' replay, `uv run lint-imports` (17 kept), ruff, ruff format check, mypy strict, the `web` job commands and `bash scripts/check_no_api_key.sh`.
- [ ] 17.5 **GATED (user)**: buy the server (D5). Never automated.
- [ ] 17.6 **GATED (user)**: choose the domain (D14), buy it if needed and set DNS; the orchestrator then records D14 in `openspec/changes/v03-demo/decision-log.md`. Never automated.
- [ ] 17.7 **GATED (user)**: create the demo API workspace and key with its USD 15/month limit, place the key in the root-only app env file on the server, and set the other root-only files per the runbook. No key in any tracked file or CI. Never automated.
- [ ] 17.8 Confirm every slice from 1a to 16b and this slice's docs are on `dev`, and that `prompt_fingerprint()` still equals the pin.
- [ ] 17.9 Re-check both models' published prices. If they changed, update `evals/pricing.toml` and `src/dale/apps/demo/prices.py` in one commit on `dev` before the live run (guarded paths).
- [ ] 17.10 **GATED (user, spends API credit)**: the owner runs the live Haiku release eval (40 cases, k = 3, effort medium, record mode) with their own `ant` profile on a clean `dev` commit after ADR 0013's commit, then commits `evals/reports/v0.3-claude-haiku-5-5.json` and its markdown twin. Every run is committed, a failed one too (a rerun adds `-2`, `-3`, … to the name), and the newest report for the release commit is the one that counts (log D21, G3 S3.3, S3.4). Changing a case file, the grader or the claim list after ADR 0013's commit needs a new decision record before the next run (S3.5). Evals never read the key variable or the key files. Never automated.
- [ ] 17.11 Run `scripts/check_release.py` locally against `dev`; fill the release notes with the result (0 false confirmations, pass^3, turn latency p50 and p95 for log D10).
- [ ] 17.12 **GATED (user)**: merge the release PR `dev` to `main` with a merge commit (not squash or rebase), so the report commit stays an ancestor of the tag (G5 S5.3). Never automated.
- [ ] 17.13 **GATED (user)**: tag `v0.3` on `main` and push it; the release workflow runs (S1.1) and records the digest (S6.1). The orchestrator only reads the result. Never automated.
- [ ] 17.14 **GATED (user)**: the first public deploy with `deploy/deploy.sh v0.3` from the owner's machine; the smoke check passes (S8.1, S9.1) and the demo stays `paused, initial`. Never automated.
- [ ] 17.15 **GATED (user)**: after a look, the owner resumes the demo on the server. Never automated.
- [ ] 17.16 Closing: blind review of the docs diff, PR body with "Known pending items", size guard output (before 17.12).

---

## Known pending

Not tasks; copied into PR bodies and the release notes.

- D14: the demo domain is still open; it blocks the Caddyfile value, the allow-list, the HSTS scope and the smoke targets (not before slice 16).
- httpx timeouts bound each I/O phase, not the total; measured on the release live run (design §13).
- The byte bound on input tokens is an assumption, checked by the replay test (6a.4).
- Conversation state is in memory only; a deploy or restart drops live conversations.
- Per-session limits are defeated by cookie churn; the per-IP limits are the real bound (log D17).
- Carried from v0.2: claim detector false alarms, the "$" grader echo, paraphrase misses, the `Money` 2^53 bound, the SSE live reveal, the LLM claim judge.
- Single VPS: patching and backups are in the runbook; no high availability.
- A real screen-reader check of the new live states, by hand.
- The 90 s deadline is revisited after the p50 and p95 of the release live run (log D10).

## Coverage check

Every requirement and scenario of the four specs maps to at least one task. Uncovered scenarios: none. Prefixes: W = web-channel, R = verified-order, O = demo-operations, G = release-gate.

| Scenario | Task(s) | Scenario | Task(s) |
|---|---|---|---|
| W S5.1-S5.4 | existing v0.2 tests; 2a.3, 8a.3 (regeneration), 13a.2 | W S5.5 | 8a.4 |
| W S8.1-S8.4 | existing v0.2 guard tests, 17.4 | W S8.5-S8.7 | 8b.1, 8b.2 |
| W S8.8 | 8c.1 | W S8.9 | 8b.2 |
| W S8.10 | 8b.2, 8c.1 | W S11.1 | 2a.3, 8a.1 |
| W S11.2, S11.3 | existing v0.2 tests, 17.4 | W S11.4 | 8a.1 |
| W S11.5 | 9d.1 | W S14.1 | existing v0.2 tests, 9e.1 |
| W S14.2 | existing v0.2 tests, 8a.1 | W S14.3 | 3.1, 9e.1 |
| W S14.4, S14.5 | 9e.1 | W S14.6 | 9e.2 |
| W S17.1 | 9a.1 | W S17.2 | 9a.2 |
| W S17.3, S17.4 | 9b.1 | W S17.5 | 9c.1 |
| W S17.6 | 9a.1, 9a.2 | W S19.1 | 13a.1, 13b.1 |
| W S19.2 | 13a.1, 13b.1 | W S19.3 | 13b.1 |
| R S9.1, S9.2 | existing v0.1 tests, 17.4 | R S9.3 | 2b.1 |
| R S9.4-S9.6 | 2c.1 | R S9.7 | 2b.5 |
| R S9.8 | 2b.3 | R S9.9 | 2a.4, 2c.3 |
| R S9.10 | 2d.2 | R S9.11 | 2b.4 |
| O S1.1 | 4.1 | O S1.2 | 4.3, 9e.4 |
| O S2.1, S2.3, S2.4 | 8c.1 | O S2.2 | 9b.1, 9d.1 |
| O S3.1 | 10.1 | O S3.2 | 9b.1 |
| O S3.3 | 10.1 | O S3.4 | 9d.1 |
| O S3.5 | 10.1 | O S3.6 | 8b.2, 10.1, 11a.1, 11a.3 |
| O S3.7 | 10.1 | O S4.1, S4.3, S4.4, S4.6, S4.7 | 6b.1 |
| O S4.2, S4.5 | 6b.1, 9e.3 | O S4.8 | 9e.2 |
| O S5.1, S5.5 | 7a.1, 9e.3 | O S5.2, S5.3 | 9e.3 |
| O S5.4 | 9d.1 | O S6.1 | 7b.1, 12b.3 |
| O S6.2, S6.3 | 7a.3 | O S7.1 | 13b.1 |
| O S7.2 | 8a.1, 9d.1, 9e.1 | O S7.3 | 9d.1 |
| O S8.1 | 13c.1 | O S9.1, S9.2 | 11a.1 |
| O S9.3 | 11b.1, 12a.1 | O S9.4 | 11b.1 |
| O S9.5 | 11b.3 | O S9.6 | 11b.1, 13b.1, 13c.1 |
| O S10.1, S10.2 | 11b.1 | O S11.1 | 12b.1 |
| O S11.2 | 9c.1, 12b.1 | O S11.3-S11.6 | 12b.1 |
| O S11.7 | 4.1, 12b.1 | | |
| G S1.1 | 15c.1, 17.13 | G S1.2, S1.3 | 15c.1 |
| G S2.1, S2.2 | 15c.1 | G S3.1 | 1a.1, 1a.3, 15b.1, 17.10 |
| G S3.2 | 15a.1, 15b.1 | G S3.3 | 17.10 |
| G S3.4, S3.7 | 15a.1 | G S3.5, S3.6 | 15b.1 |
| G S4.1-S4.5 | 15a.1 | | |
| G S4.6 | 6a.1, 15b.1 | G S5.1-S5.4 | 15b.1, 17.12 |
| G S6.1 | 15c.1, 17.13 | G S6.2 | 15c.3 |
| G S6.3 | 14.4, 16b.2 | G S7.1 | 14.3, 15c.4 |
| G S7.2 | 15c.1 | G S8.1 | 16a.1, 16b.1, 17.14 |
| G S8.2 | 16b.1 | G S8.3-S8.5 | 16a.1 |
| G S9.1 | 14.1, 14.4, 16b.2, 17.14 | G S9.2, S9.3 | 16b.2 |

Requirements: W5, W8, W11, W14, W17, W19, R9, O1-O11 and G1-G9 each map to the tasks of their scenarios above. Threat matrix (design §11): Git repository selection → 15a.1, 15b.1; push state → 15c.1; shell and SSH → 16a.1, 16b.1; rows marked N/A are omitted.

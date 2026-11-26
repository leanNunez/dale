# Archive report: v01-core (Dale v0.1 "El nucleo")

**Archived on**: 2026-11-18
**Archive path**: `openspec/changes/archive/2026-11-18-v01-core/`
**Artifact store**: hybrid (OpenSpec files are the source of truth; Engram is mirrored by the orchestrator)
**Verdict at close**: PASS WITH WARNINGS (0 CRITICAL, 7 WARNING), archive READY (`verify-report.md`)

## What was archived

`proposal.md`, `specs/verified-order/spec.md`, `design.md`, `tasks.md`, `apply-progress.md`, `decision-log.md` and `verify-report.md`, moved with `git mv`. None of their bytes were edited by the move (git reports each as a pure rename; `verify-report.md` carries the sdd-verify rewrite made before archive).

## Spec merge

The change was a new capability, so the delta spec became the main spec: `openspec/specs/verified-order/spec.md` (R1-R15, 43 scenarios). Only the spec drift items from the verify report were applied to the MAIN spec; the archived delta is unchanged.

- S10.1 reworded to the approved behavior: no proposal left pending, no summary shown, no order; a refused turn may leave a `superseded` proposal row that is not confirmable (decision-log B75, B72). This closes the requirements 14/15 and scenarios 42/43 gap.
- Header line 8 and "Open design dependencies" replaced by "Resolved design dependencies", pointing at design decisions D1-D6 (D1-D10 overall).
- One related stale sentence in R5 ("Depends on design: whether a price change ... rejects or re-quotes") now states design decision D4 (reject at confirm). The R5 requirement itself is unchanged. The R7 "Depends on design" sentence was left as is.
- No requirement or scenario text was changed otherwise.

## Final task state

110/110 checked. Task 15.5 is recorded as closed by the user's decision on 2026-11-18, not the unaided explanation the task describes (verify-report W2). The text under it is a study summary written by the agent at the user's request.

## Release evidence

- Release gate: `evals/reports/v0.1-run4.md` PASS, 0 false confirmations; verified 14/15, pass^3 17/18, pass^1 53/54; cost per verified order USD 0.001778889. Runs 1-3 failed and are committed with reasons.
- PR #64 (`dev` to `main`) merged as `85fdb96`.
- Tag `v0.1` (annotated, object `e32a5e4`, dereferences to `85fdb96`).
- Verification on `aff2cb4`: 1094 tests passed, 54 replay eval tests passed, ruff, mypy strict and import-linter green.

## Known warnings carried forward

W1 (S10.1 wording, resolved by the spec reword above), W2 (15.5 deviation), W3 (S1.1 unstable live: `order-cola-ok` run 1), W4 (S7.4 model-text side only prompt-guarded), W5 (gate is the fourth attempt), W6 (drift below), W7 (stale records below). Details are in `verify-report.md`.

## As-built drift

The design and the spec describe the plan; the code shipped differently in the places below. Most of these decisions were logged under the autonomous build rule (entries marked `auto`) and were NOT individually confirmed by the user; only planning decisions P1-P12 and B103, B104, B106, B109-B112 are marked `user`. The archived `design.md` is left unchanged and is not the as-built description in these sections.

Spec items (resolved in the main spec, see above): S10.1 wording (B75, B72(4)); the "Open design dependencies" section (decided by D1-D10).

Design drift (table copied from the verify report):

| Section | Design says | Code does | Decision-log entry |
|---|---|---|---|
| Header and §1 D5 | F2 "verify inside tmux and Zellij" | Both verified and recorded; F3 cancels, typeahead is discarded before each prompt, paste and batch input never presses (B82-B84) | B82 (auto), B83 (auto), `docs/decisions/0002-confirm-key.md` |
| §1 D8, §9 | One versioned phrase list; "other verdicts: mismatch, missing, unexpected_write" | List 2026-11-16.4, negation rules by closed word lists; verdicts add `unverifiable{reason}` and `nothing_confirmed`; a claim is backed only by the text right after a verified confirmation; REPEATABLE READ snapshot; child env allow-list; the prompt bans claim words about an order in any form | B78, B79, B80 (auto); B105, B109, B110 (B109 and B110 user) |
| §1 D9, §10 | Fingerprint of (model, effort, system, tools) | Also `max_tokens`, `tool_choice` and a per-step messages digest | B75(6), B87 (auto) |
| §3 contracts and tree | 7 contracts; tree without `evals/reports` details | 10 contracts: 3 split into 3a/3b, 7 into 7a/7b, contract 8 added (evals reach `anthropic` only through the brain adapter); contracts 2, 5, 8 use `allow_indirect_imports = true` | B86(8) (auto); `pyproject.toml` |
| §5 data model | PKs are `(company_id, id)`; `status` and `reason` imply enums; grants in the roles file; TRUNCATE implied by "truncates the tables" | `product_price` PK `(company_id, product_id, valid_from)`; `text` plus named CHECKs; grants live in migration 0001 and `db/roles.sql` only creates roles; no TRUNCATE (DELETE as `dale_app`); `product_name` on proposal lines (0005); one prepared proposal per conversation (partial unique index, 0004) | B17, B12, B9, B13, B21, B64, B82 (all auto) |
| §6 rules, idempotency, catalog | 16 codes; fail-closed on any read error; `confirm` looks up, then inserts | 17 codes (`invalid_tool_input` added); fail-closed only on `DBAPIError`; READ COMMITTED plus re-read; a different payload on a replayed id gives `proposal_not_pending`; a shown total that differs gives `price_changed`; fixed check order; `find_order` and a per-conversation lock | B57, B47, B46, B45, B49, B54, B67, B68 (auto) |
| §7 brain loop | Tool bounds as JSON-schema keywords; `effort` "checked against the SDK"; refusal: fixed message plus handoff | Bounds are prose plus strict pydantic validation (SDK drops the keywords); `output_config={"effort": "medium"}`, 60 s timeout; empty, `max_tokens` and malformed replies show `model_unavailable`; a refusal also withdraws the turn's proposals; history keeps 8 customer turns; fencing by Unicode category and a `<catalog_text>` fence; handoff reason is a bare enum, `agent_refusal` is code-only | B58, B74, B72, B75, B73, B66 (auto); B69 closed by run 4 |
| §8 terminal | Typed input, F2 emits `KeyPress(DALE)` | Plus F3 cancel, Ctrl-C/Ctrl-D, typeahead discard, paste rule, file logging; the verifier runs after every press over everything shown; "NO VERIFICADO" and "CONFIRMACION FALSA" wording | B82, B83, B84 (auto) |
| §10 eval harness | Case schema `id, suite, now, customer, seed_overrides, history, message, press_dale, expect`; each run "truncates the tables" | Adds `pending_proposal`, `failure`, `shown`, `premise`, `price_change`, `negative_of`; gauchadas must press; the release gate blocks on any false confirmation, unverifiable run or run that raised (a merely failed case does not block); per-session sink; stale-report deletion; 9-place rounding; long-context price tier; `--report <version>`; `known_misses.toml` with a pinned sha256 per recording (a known miss must fail exactly as recorded and never be a false confirmation) | B86-B97 (auto), B107 (auto) |
| §11 CI | Six jobs; secrets grep "under `src/` and `evals/`" | Eight required jobs (adds `pr-base`, `tracked-files`); `pytest evals` runs in the `test` job; the key guard scans tracked code, config and `*.jsonl` and also fails on re-enabled sockets; triggers are pull requests and pushes to `main` and `dev` | B5, B104, B106 (user), B107 (auto) |
| §15 slices | 12 PRs, about 3,300 lines | 58 slice PRs (#1-#58), the main-into-dev sync (#59), five docs PRs (#60-#63 and #65) and the release PR (#64); about 14,800 authored code lines; the live runs and release evidence went in slices `slice-16a/b/c` | B8, B36, B56, B71, B77, B81, B85, B88, B92, B112 |

## Stale records (known, left untouched to preserve history)

- `tasks.md` slice table: rows 9-15 show estimates, not actual branches; slices 16a-16c are not listed; 8.1 still lists "confirmed to `proposal_not_pending`" (superseded by 8.5a, B65); 15.2 names `evals/reports/v0.1.json`, which is run 1 (FAIL), while the passing report is `v0.1-run4.{json,md}` (B111). The task file therefore names `v0.1.json` where `v0.1-run4` is the release evidence.
- `apply-progress.md`: no section for slice 16, 11.6, 15.5 or 15.6; the "Chain merge (2026-11-17)" paragraph still says "Left: 11.6, 15.5, 15.6 and 15.7".
- `decision-log.md`: the footer "Waiting for the user (hard gates)" still lists 15.6, 11.6 and 15.5 as open; no entry records the Zellij result, the 15.5 closure or the release PR and tag; B107 says the only known miss is `cutoff-met-delivers-thursday` run 2, replaced by `order-cola-ok` run 1 (B111).

## Repository links updated at archive

`README.md`, `README.es.md` and `tests/unit/test_readmes.py` pointed at `openspec/changes/v01-core/decision-log.md`; they now point at `openspec/changes/archive/2026-11-18-v01-core/decision-log.md`.

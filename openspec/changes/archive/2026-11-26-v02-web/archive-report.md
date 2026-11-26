# Archive report: v02-web (Dale v0.2 "Se ve")

**Archived on**: 2026-11-26
**Archive path**: `openspec/changes/archive/2026-11-26-v02-web/`
**Artifact store**: hybrid (OpenSpec files are the source of truth; Engram holds mirrors: proposal #1089, spec #1090, design #1091, tasks #1093, apply-progress #1095, explore #1086)
**Verdict at close**: no `verify-report` exists for this change. `sdd-verify` was not run. The work was verified per slice by blind reviews and CI, recorded in the PR bodies, in `tasks.md` (each closing task) and in `decision-log.md`. Native status reported 112/112 tasks and `nextRecommended: archive` before the move; no review receipt governs this change (`reviewGate` absent).

## What was archived

`proposal.md`, `exploration.md`, `specs/verified-order/spec.md`, `specs/web-channel/spec.md`, `design.md`, `tasks.md` and `decision-log.md`, moved with `git mv`. `diff -r` of a pre-move copy against the archived folder was empty, so no byte changed. There is no `apply-progress.md` or `verify-report.md` file; apply progress lives only in Engram (#1095) and is an intermediate snapshot (it still lists the release PR and the tag as remaining; both are done, see below).

## Spec merge

- `openspec/specs/verified-order/spec.md` (existing, from v0.1): the modified blocks R3, R4, R11, R13 and R14 replace the v0.1 text, and R16 (pre-registered model comparison) is added after R15. Each merged block is identical to the delta block (only the heading level changes from `###` to `##`). R1, R2, R5-R10, R12, R15 and "Resolved design dependencies" are unchanged. The header now names both changes and points to `web-channel`; the terms gain **Dale action**, which replaces **Dale key** in R4 (the delta's "Terms added"). Nothing is removed (the delta's REMOVED section is "None"). Result: R1-R16, 60 scenarios.
- `openspec/specs/web-channel/spec.md` (new capability): a mechanical copy of the delta, W1-W18, 58 scenarios. `diff -r` was empty.
- No as-built drift was written into either main spec; the drift below is in design, not in the requirements.

## Final task state

112/112 checked. Task 10.6 (informal one-minute walkthrough) is checked as closed by the user's decision to skip it (B141), not as done; `docs/releases/v0.2.md` says it was not done and claims no result.

## Release evidence

- Chain: 55 slice PRs (#67-#121) merged bottom-up into `dev` on 2026-11-26 with the user's authorization (B140); bookkeeping PRs #122 and #124 merged; CI green on `dev`.
- Release PR #123 (`dev` to `main`) merged as `c5ff98c`; CI green on `main`. Annotated tag `v0.2` (object `9a8000d`) dereferences to `c5ff98c`.
- Required checks on `main` and `dev`: lint, types, arch, test, tracked-files, secrets, size, pr-base, `evals (claude-haiku-5-5)`, `web`, `evals (claude-sonnet-5-5)`.
- Model comparison: `evals/reports/v0.2-comparison.md`, both models recorded on `f9db72a`, 40 cases (13 gauchadas) x 3 runs, effort medium. Outcome `select:claude-haiku-5-5`: pass^3 37/40 (Haiku) vs 40/40 (Sonnet), a difference below the minimum of 4, so a tie; Haiku at least 20% cheaper (USD 0.062 vs 0.94 for all 120 runs). Both models: 0 false confirmations, all hard gates pass. The user confirmed Haiku stays the default; `MODEL_SETTINGS` is unchanged (ADR 0008).
- Haiku record run 1 (on `7d3a4f0`) was discarded: its 4 false confirmations were claim-detector false positives on correct negated replies. The detector was fixed (claim list `2026-11-26.1`, PR #119, B134) and both models were recorded on the fixed commit. Evidence: `evals/reports/discarded/v0.2-run1-claude-haiku-5-5/` (B139).
- Release code: `git diff f9db72a` of `src/` is empty and `prompt_fingerprint()` equals its pin, so the comparison run is a run of the release code (task 10.7). On the release slice: pytest 1701 passed, eval replay 120/120 per model, Vitest 408, ruff, mypy strict, import-linter (15 contracts), page typecheck, lint and build green, no generated-type drift (task 10.8).

## As-built drift

The design describes the plan; the code shipped differently in the places below. Build decisions B1-B139 were taken under the autonomous build rule (marked `auto`) and were NOT individually confirmed by the user; B140, B141 and planning decisions P1-P8 are marked `user`. The archived `design.md` is left unchanged and is not the as-built description in these sections.

| Section | Design says | Code does | Decision-log entry |
|---|---|---|---|
| §2 contracts and pins | New contracts 9, 10, 11; pins `fastapi`, `uvicorn`, dev `httpx` | Contract 10 split into 10a (independence) and 10b (`common` imports neither); contract 9 also covers submodules and `evals`; new contract 12 (`prompt_toolkit` only in the terminal channel); 15 contracts in total. Dev `httpx2==2.16.0` instead of `httpx`; direct `starlette` pin | B3, B8, B7, B9 |
| §1 D11, §2 composition | `compose()` moves to `apps/compose.py` and gains `channel` | `compose(..., *, channel)` with no default; `TerminalBackend` becomes `ChannelBackend` (alias kept); a channel-side `WebBackend` protocol and an `apps.web.ComposedBackend` adapter, one composed backend per conversation; a failed compose answers 503 `rules_unavailable` | B29, B44, B57 |
| §4.1 types and envelope | `VerdictIssued.stored_orders[].lines` with `unit_price`, `line_total`; envelope `seq` loosely defined | Stored-order lines reuse `ShownLine` and totals use `Money` (`{cents}`); every event's `conversation_id` equals the envelope's; with events `seq` is the largest event seq, without events the conversation's last seq (0 before the first) | B17, B24 |
| §4.2 guard | Origin checked "on POST, when present"; media type and body cap; every API response is one `ResponseEnvelope` | Origin required (exactly one, allow-listed) on every method but GET and HEAD; missing or repeated Host, repeated Origin or Content-Type, non-UTF-8 charset and bad Content-Length rejected; WebSocket closed with 1008; guard wraps outside FastAPI's error middleware; the body is read up to 16 KiB then replayed. `/v1/contract` answers a bare body and `/health` an empty envelope; errors are always one envelope. The page mount exists only when `apps/web/dist` exists, else `/` is 404 | B30, B31, B32, B33, B34, B39, B41 |
| §4.3 conversations and press | A registry of conversations; gate step 3 also sends an id shown in an `OrderConfirmed` to `backend.confirm`; step 4 appends the gate's notices to the transcript | One live conversation per host: creating one retires the earlier ones (`conversation_not_found`). Only the pending id reaches the brain; a settled id replays from the cache, any other id gets a notice without a brain call. Gate notices do not enter the transcript or touch `Pending`. At most one press waits per id; an unknown outcome is shared once with the waiting press and not cached; a replay carries the latest envelope `seq` and pending id. A reply that cannot be serialized withdraws its pending proposal and answers 500 | B45, B46, B50, B51, B52, B53, B65, B66 |
| §4.3 start-up settings | Fixed customer from `DALE_WEB_CUSTOMER`, company from `DALE_WEB_COMPANY` | `DALE_WEB_COMPANY`, `DALE_APP_DATABASE_URL` and `DALE_VERIFIER_DATABASE_URL` required (exit 2); a start-up `find_customer` check; no `--host` option; `proxy_headers=False`, `server_header=False` | B36, B42, B59 |
| §5 verifier evidence | `Report.stored = Evidence.orders`; the runner checks ids unique and findings consistent | Only the session customer's orders are stored (another customer's order appears only by id in its finding); the runner enforces further consistency rules between findings and stored orders, failing closed as `malformed_output` | B12, B13 |
| §6 frontend | Dale button enabled when a pending id exists and nothing is in flight; no cancel control listed; pins resolved at scaffold time | The button also needs a rendered `ProposalSummary` with the pending id (`canPressDale`); a `Cancelar propuesta` button by the same rule. Pins dated on or before 2026-11-06 with a two-week cooldown on every locked package; Node 24.22.2. The trace panel replaces control and format characters and isolates text with `<bdi>`; the order panel follows the latest verdict naming a subject and shows orders of other proposals; the verdict panel words every outcome in Spanish with a mark; a generated `components.ts` drives the exhaustive switch | B68, B70, B73, B75, B80, B88, B94, B97, B98, B100, B101 |
| §7 evals | Report `v0.2-<model>`; "about 22 new cases"; the existing claim detector | Reports always `<version>-<model>`, default included; pricing tables carry a long-context threshold; reports add `prompt.content_sha256`; replay skips cases with no recording yet; a record session leaves `evals/recordings/` out of the dirty check; the comparison refuses errored runs and reports without snapshot ids. Case set: 40 cases, 13 gauchadas. Claim list changed to `2026-11-26.1` after the discarded Haiku run 1 | B104, B105, B111, B114, B115, B116, B122, B123, B132, B134 |
| §8 CI | `web` and `evals (<model>)` required as slices land | Final required checks: the eight v0.1 jobs plus `evals (claude-haiku-5-5)`, `web` and `evals (claude-sonnet-5-5)`, added in chain order; the `web` job's rebinding test was fixed in its own PR (#116) | B107, B121, B135, B140 |
| §13 slices | 11 slices, about 3,400 lines, in 11-13 PRs | 55 slice PRs (#67-#121), two bookkeeping PRs (#122, #124) and the release PR (#123); most planned slices were split to fit the 400-line budget | B18, B19, B38, B49, B56, B64, B74, B82, B87, B93, B108, B113, B120, B133 |

## Stale records (known, left untouched to preserve history)

- `docs/releases/v0.2.md` "Known pending" still says the required checks are to be added as the chain merges (B135); all three were added (B140).
- `tasks.md` 10.5 says "The 10.6 line is a marked placeholder"; PR #124 replaced it with "not done".
- `tasks.md` hard-gates table names `evals (sonnet)`; the check is `evals (claude-sonnet-5-5)`. The PR slice table header and P7 say 14 chained PRs; 55 were merged.
- `decision-log.md` has no row for the release PR #123 or the tag `v0.2`; tasks 10.9 and 10.10 record them.
- Engram apply-progress #1095 still lists the release PR merge and the tag as remaining.

## Known pending

From `tasks.md` and `docs/releases/v0.2.md`:

- A turn deadline in the brain (no upper bound with `retry-after`, B6). Required before the v0.3 public demo.
- In-memory conversations: no cap on their number, lost on restart; a v0.3 persistent store behind the registry port (B54).
- Two concurrent conversations of one customer see each other's orders in their evidence (B14, B65).
- `Money` has no JS-safe integer bound (cents above 2^53); the published schema has no `minimum` on cents or quantity (B27).
- LLM claim judge (D8c); accepted claim-detector false alarms; a reply naming a "$" amount no tool returned fails the grader (B133).
- SSE live tool reveal (stretch, not in v0.2).
- v0.3: deploy, per-visitor limits, spend cap, kill switch, auto-reset database, saved conversations with notice, cookie session.

## Repository links updated at archive

`README.md` and `README.es.md` pointed at `openspec/changes/v02-web/decision-log.md`; they now point at `openspec/changes/archive/2026-11-26-v02-web/decision-log.md`.

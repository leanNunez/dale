# Proposal: Dale v0.2 "Se ve"

## Intent

v0.2 makes the v0.1 result visible: a person who does not program understands what Dale does in about one minute. A local web page shows the chat and, beside it, the tools the agent used, the order stored in the database and the verifier's verdict. The Dale button is a real button handled by code. The eval suite grows to about 40 cases, and a pre-registered rule decides between Haiku 5.5 and Sonnet 5.5.

Sources: the exploration (`exploration.md`) and the internal plan (private). User decisions of 2026-11-19 are binding and are not reopened.

## Scope

### In Scope

| Area | Deliverable |
|---|---|
| Web host | `dale.channels.web` (FastAPI) and composition root `dale.apps.web`; same-origin static build; bound to `127.0.0.1` |
| Shared channel logic | `Backend`, `step` and `Pending` moved to `dale.channels.common`; the terminal keeps working unchanged |
| Transport | Request/response JSON. Every event carries an SSE-ready envelope (`v`, `seq`, `conversation_id`, `type`, `data`) |
| Contract v1 | Events (the six shown events plus `ToolCalled` and `VerdictIssued`), commands (`SendMessage`, `PressDale`, `CancelProposal`), typed components. JSON Schema generated from the Python types, then TS types; both committed and drift-checked in CI |
| Brain | Additive tool `trace` on `TurnResult` (tool name, argument summary, ok or error code). Outside the prompt path |
| Verifier | The verdict also returns the stored order it read (evidence it already loads) |
| Safety | Host and Origin allow-list, JSON-only with size cap, CSP, text-only rendering, one error envelope via `HTTP_STATUS`, per-conversation lock (409 while a turn runs) |
| Frontend | React + TS + Vite + Tailwind under `apps/web`, exact pinned versions |
| Customer | One fixed seeded customer of Distribuidora El Hornero; no picker |
| CI | New required Node job `web` (typecheck, lint, Vitest, build). Size guard excludes `package-lock.json` and generated schema/TS files |
| Evals | About 40 cases (at least 10 gauchadas), web-relevant cases, model dimension in harness, recordings and pricing; both models replayed in CI |
| Comparison | Pre-registered rule (below), committed before any Sonnet recording; comparison report |
| Decision records | One retroactive "founding decisions" record (no private-plan quotes; notes the dropped video) plus records for web host and transport, web confirmation safety, frontend and contract, and the comparison rule |

### Out of Scope

Video or recording of any kind; deploy; per-visitor limits; spend cap; kill switch; auto-reset database; saved conversations; customer picker; effort comparison; WebSocket; multiple companies.

### Known pending items

- SSE live tool reveal (stretch: only if time remains, not committed).
- v0.3: deploy, limits, spend cap, kill switch, auto-reset, saved conversations with notice, cookie session. v0.2 keeps the conversation registry behind a port and the Host/Origin allow-list configurable so v0.3 adds them without reshaping routes.
- Persistent conversation state (in memory in v0.2; lost on restart).
- Stale `context`/`testing` blocks in `openspec/config.yaml`.

## Capabilities

### New Capabilities
- `web-channel`: local HTTP host, contract v1 (events, commands, components, versioning), web confirmation safety, the three panels, the Dale button.

### Modified Capabilities
- `verified-order`:
  - R4 and S3.3: the "Dale key" becomes a channel-neutral Dale action (terminal key or web button), always handled by code. Typed text still never confirms.
  - R11: the verdict also carries the stored order the verifier read. Read-only behavior is unchanged.
  - R13: about 40 cases, at least 10 gauchadas, recordings per model, CI replays every compared model.
  - R14 and a new requirement: per-model reports plus a comparison decided by the pre-registered rule.

## Model comparison rule (pre-registered)

Fixed conditions: same commit, prompt version, tools, case set and k = 3; effort medium for both; model snapshot ids recorded; prices from `evals/pricing.toml` with source and check date, re-checked on run day. Both models record fresh on that commit.

| Step | Rule |
|---|---|
| Hard gates (per model, all runs) | 0 false confirmations, 0 unexpected writes (an order or handoff the case does not allow), 0 `unverifiable` verdicts, 0 applied exceptions in gauchadas. Any breach rejects that model |
| Primary metric | pass^3 count over the case set. Flaky cases and known misses count as failures for both models; no per-model exclusions |
| Minimum meaningful difference | max(4 cases, 10% of the case set) in pass^3. Smaller is a tie |
| Tie-break | Cost per verified order (model cost / verified orders). The cheaper model wins only if at least 20% cheaper |
| Outcomes | One model passes the gates: that model. Both pass, clear difference: higher pass^3. Tie: the cheaper by the 20% margin. Otherwise, or both fail the gates: "inconclusive: expand the cases", and the default stays Haiku |

## Approach

Hexagonal as in v0.1. The web channel is a thin host over `TakeTurn` and `ConfirmProposal`; confirmation safety is already structural and is proved by tests, not new logic. The confirm route runs the verifier after every press and after a turn that showed `OrderConfirmed`, and returns the verdict in the same response. Trace and verdict events stay outside `ShownEvent` so the verifier never judges them. Generation lives in `channels.web` because `shared` must not import pydantic.

## Affected Areas

| Path | Impact |
|---|---|
| `src/dale/channels/common/`, `src/dale/channels/web/`, `src/dale/apps/web.py` | New |
| `src/dale/channels/terminal/` | Modified: imports moved shared logic |
| `src/dale/brain/application/take_turn.py` | Modified: additive `trace` |
| `src/dale/verifier/` | Modified: verdict evidence |
| `contracts/v1/`, `apps/web/` | New (generated files committed) |
| `evals/` (harness, cases, `recordings/<model>/`, pricing, known misses, reports) | Modified |
| `.github/workflows/`, `scripts/check_pr_size.py`, import-linter config, `tests/unit/test_ci_workflow.py` | Modified |
| `docs/decisions/`, `README*.md` | New and modified |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| A trace or verdict change alters the fingerprint and forces re-recording | Med | Keep both out of the prompt path; a fingerprint-unchanged test until the comparison run |
| Cross-site or DNS-rebinding POST to localhost | Med | Host/Origin allow-list, JSON-only, no CORS, CSP; tests for each |
| Slow turns (up to six model calls plus a 30 s verifier) | High | Pending UI state, button disabled while a request runs, request timeout above both limits, 409 on overlap |
| Models do not separate on 40 cases | Med | "Inconclusive" is a valid, pre-registered outcome |
| Node supply chain and lockfile churn | Med | Exact pins, `npm ci`, lockfile excluded from size guard but reviewed |
| 400-line budget | High | Chained PRs (below) |

## Rollback Plan

The web channel is additive; the terminal remains the working channel, so reverting any web PR leaves v0.1 behavior intact. The `channels.common` move, the trace and the verdict evidence are each one revertible PR. The recordings move is a pure path move, revertible with `git revert`. A model switch is a one-constant change to `MODEL_SETTINGS`, revertible alone. No schema migration is planned; if one appears it is forward-only and the demo DB is reseeded. Removing the `web` job also requires a branch-protection update. The v0.2 tag is published only after the comparison report exists.

## Size forecast (from exploration; tasks will refine it)

About 2,500-3,000 authored lines in 9-11 chained PRs. **400-line budget risk: High**, so ask-on-risk applies before apply. Slices: (1) decision records, `channels.common`, import-linter contracts; (2) contract and golden tests; (3) FastAPI app and safety tests (may split); (4) trace, verdict evidence, spec delta; (5) frontend scaffold, `web` job, size-guard exclusions; (6) chat and panels (may split); (7) harness model dimension and the rule; (8) new cases, both-model runs, report; (9) docs, release notes, tag.

## Success Criteria

- [ ] Typed "dale" via `/messages` with a pending proposal creates 0 orders; two concurrent `/confirm` POSTs create exactly 1 order with identical bodies.
- [ ] A foreign `Origin` or disallowed `Host` is rejected; the route table exposes no confirm path besides `/confirm`.
- [ ] Every event kind round-trips; every `ErrorCode` has an HTTP status; regenerating schemas and TS types gives no diff in CI.
- [ ] The order panel shows the stored order from the verdict, and the verdict panel shows the verifier's result for every press.
- [ ] 38-42 cases, at least 10 gauchadas; both models replay offline in CI and the `test` job stays within 15 minutes.
- [ ] The rule commit precedes the first Sonnet recording commit; the report names one rule outcome; the shipped model has 0 false confirmations.
- [ ] All existing CI jobs and the new `web` job are green.
- [ ] One person who does not program describes the order flow after one minute on the page (noted in release notes).

## Proposal question round

Accepted by the user on 2026-11-19, together with the model comparison rule above:

1. If the rule picks Sonnet, v0.2 switches the default model (which raises v0.3 demo cost). Alternative: record the result only.
2. Panel labels are in Spanish like the chat, since the audience is a non-programmer. Alternative: English labels.
3. The one-minute understanding check is one informal walkthrough with one person, not a study.
4. At least 10 gauchadas out of about 40 cases (v0.1: 5 out of 18).

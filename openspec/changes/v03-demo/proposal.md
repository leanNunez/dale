# Proposal: Dale v0.3 "Probalo vos"

## Intent

v0.3 lets anyone try Dale from a public link in the owner's CV, with no risk to the owner's account. v0.2 is a single-operator loopback host: one fixed customer, one live conversation, no turn deadline, no limits, no spend accounting. v0.3 adds what a safe public demo needs and nothing more.

Sources: `exploration.md` and `decision-log.md`. Decisions D1-D13 are accepted by the user (2026-11-26) and binding. D1-D3 replace the exploration's CI live eval with a key and CI SSH deploy. D14 (domain) is pending.

## Scope

### In Scope

| Area | Deliverable |
|---|---|
| Isolation (D4) | A new visitor customer per conversation, cloned from a template customer in zone Centro; many live conversations; caps and idle TTL. Supersedes v0.2 B65; verifier run scope unchanged |
| Turn deadline (D10) | 90 s per turn (setting): bounded retries in the adapter, a time check before each model call, `statement_timeout` on `dale_app` |
| Visitor limits (D9) | Cookie session (HttpOnly, Secure, SameSite=Strict); per-session, per-IP and global limits; client IP from Caddy trusted only from loopback; IPs never stored in clear |
| Spend cap (D6) | Code cap of USD 0.50/day checked before each model call, a persistent spend ledger, a runtime price table inside `dale` |
| Kill switch | A control row read before each turn and call (unreadable means paused); operator CLI `pause`, `resume`, `status` over SSH; no public admin endpoint |
| Notice and transcripts (D8) | Always-visible automated-assistant banner, accept-to-start, `/privacidad` page with a deletion contact; transcripts kept 30 days and purged nightly; failure export to JSONL for hand-written cases |
| Reset (D11) | Nightly 04:00 Buenos Aires: pause, drain, clear registry, reseed, resume |
| Page states | Paused, limit reached, demo busy, demo reset, turn deadline; tool-trace panel stays (D13) |
| Packaging (D5) | Dockerfile, Compose, host Caddy with TLS and HSTS; app keeps the `127.0.0.1` bind; Postgres only on loopback with passwords from a root-only file |
| Release (D1, D2, D12) | `release.yml` on `v*` tags on `main`: rerun CI gates, check the committed live report and the pass criterion, check no code or prompt-path change since it, publish the image to GHCR. The owner runs the deploy script (migrate, up, smoke, roll back) |
| Credentials (D3) | Demo workspace key only on the server; repository and CI stay key-free |
| Records | Decision records: public demo (isolation, cookie session and CSRF, deadline, hosting and deploy); release eval criterion committed before the first release run |

### Out of Scope

Video or recording of any kind; login or accounts; CAPTCHA (breaks W10's CSP); customer picker; conversation restore after restart; high availability or more than one instance; managed database; live eval or deploy run by CI; a key anywhere in CI or the repository; browser error SDK or analytics; SSE or WebSocket; LLM claim judge; automatic transcript-to-case conversion; changing the default model; multiple companies; a public admin endpoint.

### Known pending carried from v0.2

| Item | v0.3 |
|---|---|
| Turn deadline in the brain | In scope |
| Unbounded in-memory conversations | Capped and TTL'd; still lost on restart |
| Local only | Addressed by the deploy |
| Claim detector false alarms, "$" grader echo, paraphrase misses | Carried; transcripts may surface new cases |
| `Money` 2^53 bound | Carried; unreachable with seeded prices and line bounds |
| SSE live reveal | Carried |

## Capabilities

### New Capabilities
- `demo-operations`: cookie session, visitor and global limits, spend cap and ledger, kill switch and operator CLI, notice and accept-to-start, transcripts with retention and export, nightly reset and drain.
- `release-gate`: tag-on-`main` release checks, committed live report against the pre-registered criterion, image publication, owner-run deploy with smoke check and rollback, no keys in the repository or CI.

### Modified Capabilities
- `web-channel`:
  - W14: the fixed seeded customer becomes a new visitor customer per conversation; the page still cannot name a customer.
  - W17: the registry holds many live conversations with caps and idle TTL; the local host still runs without demo controls.
  - W11 and W5: new transport codes (rate limited, paused, busy, reset) added to contract v1, additive only.
  - W8: client IP from forwarded headers trusted only from loopback; session cookie with SameSite=Strict, and the Origin, Host and JSON checks still close CSRF (amends ADR 0005's no-cookie premise).
  - W1, W6, W7, W12, W13 unchanged.
- `verified-order`:
  - R9: a turn has a wall-clock deadline and fails with a catalog code, never a partial confirmation; applies to the terminal too. R11 run scope unchanged.

## Approach

- Hexagonal as in v0.1 and v0.2. Demo controls live in `dale.apps` and `dale.channels.web`. The brain changes only for the deadline. The spend cap wraps `ModelPort` in the apps layer. (Superseded: the spend cap is an `AttemptGate` the adapter calls on every attempt, retries included; design DD27, log D19.)
- A `demo` schema holds control, ledger, sessions and transcripts, so reseed never touches it.
- Per-visitor customers go through a new `erp_sim` write port. The nightly reseed removes them.
- The deadline is passed into `TakeTurn`. The adapter makes no SDK retries and runs its own bounded loop with `retry-after` honored only when it fits. Request parameters and the prompt fingerprint do not change.
- Live eval: the owner runs it with their `ant` profile and commits the report. CI verifies it and never calls the API.

## Affected Areas

| Path | Impact |
|---|---|
| `src/dale/apps/web.py`, `src/dale/channels/web/` | Modified: customer factory, registry, session, limits, codes, proxy headers, page path |
| `src/dale/brain/infrastructure/anthropic_model.py`, `src/dale/brain/application/take_turn.py` | Modified: deadline |
| `src/dale/erp_sim/` | Modified: visitor customer port |
| `migrations/versions/` | New: `demo` schema |
| `apps/web/src/` | Modified: notice, states, privacy page |
| `contracts/v1/` | Modified: additive codes (generated) |
| New: `Dockerfile`, `deploy/` (Compose, Caddyfile, deploy and reset scripts), operator CLI, `.github/workflows/release.yml` | New |
| `db/roles.sql`, `docs/decisions/`, `docs/releases/v0.3.md`, `README*.md` | New and modified |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Reset under a live conversation gives false `missing` verdicts | Med | Pause and strict drain before reseed; test |
| 90 s deadline cuts legitimate slow turns; no latency data exists | Med | Setting; measure p50/p95 on the first live run |
| Daily cap depends on hand-synced prices | Med | Price table dated and checked at release; USD 15/month workspace limit as backstop |
| Live release eval fails on noise | Med | Criterion pre-registered (D12) |
| Visitors type real personal data | Med | Notice, no IP or user agent stored, 30-day purge, raw transcripts never committed |
| Abusive injected output under the owner's name | Low-Med | Notice, kill switch, transcripts, confirmation outside the model |
| Single VPS: patching, backups, no HA | Med | Documented runbook; out of scope beyond that |
| Cookies reopen CSRF | Low | SameSite=Strict plus existing Origin, Host and JSON checks; decision record |

## Rollback Plan

- Live incident: `pause` with the operator CLI; then disable the demo key or archive the workspace in the Console; then stop Compose and remove the DNS record.
- Bad release: the deploy script redeploys the previous image tag; it rolls back automatically when the smoke check fails.
- Data: the `demo` schema is separate and forward-only; reseed restores `erp`.
- Code: each slice is one revertible PR; the local host keeps v0.2 behavior without demo settings.

## Hard gates for the user

1. Buy the server (D5).
2. Choose and, if needed, buy the domain; set DNS (D14, pending).
3. Create the demo API workspace and key with its USD 15/month limit; place the key on the server (D3, D7).
4. Provide the privacy contact email for deletion requests and approve the notice wording.
5. Run the paid live Haiku release eval and commit its report (D1).
6. Merge to `main` and push the `v0.3` tag.
7. Run the public deploy (D2).

## Size forecast (tasks will refine it)

| # | Slice | Raw estimate (lines) |
|---|---|---|
| 1 | Decision records and release criterion | 200-300 |
| 2 | Turn deadline | 300-450 |
| 3 | Visitor customer and registry caps | 400-600 |
| 4 | Session, limits, proxy IP, codes | 400-600 |
| 5 | Spend cap, ledger, kill switch, operator CLI | 400-600 |
| 6 | Transcripts, notice, page states, export (may split) | 500-800 |
| 7 | Nightly reset and purge | 250-400 |
| 8 | Packaging (Docker, Compose, Caddy, roles) | 250-400 |
| 9 | Release workflow and deploy script | 300-500 |
| 10 | Docs, release notes, live report, tag | 200-300 |

Raw total about 3,200-5,000 authored lines. v0.2 estimates ran 2-3x low, so plan for about 6,500-10,000 lines and 15-25 chained PRs; most slices will split.

Decision needed before apply: Yes
Chained PRs recommended: Yes
400-line budget risk: High

## Success Criteria

- [ ] Two concurrent visitors each get their own customer; neither ends the other; both get `verified` verdicts with the verifier run scope unchanged.
- [ ] With a fake clock, no turn exceeds the deadline; a `retry-after` beyond it fails with a catalog code.
- [ ] With the ledger at the cap, the next model call is refused before reaching the API, including after a restart.
- [ ] `pause` stops new turns; an unreadable control row behaves as paused.
- [ ] Each D9 limit, when exceeded, returns its stable code; the 11th live conversation gets "demo busy".
- [ ] No conversation starts before the notice is accepted; transcripts older than 30 days are purged; no IP or user agent is stored.
- [ ] The nightly reset never runs with a live conversation.
- [ ] `check_no_api_key.sh` passes; `release.yml` refuses a tag with a missing, failing or stale live report.
- [ ] The public URL serves HTTPS with HSTS; the app listens only on `127.0.0.1`; Postgres is not reachable from outside.
- [ ] The release live run meets D12 with 0 false confirmations; all CI jobs are green.

## Proposal question round

Not asked directly (sub-agent, auto mode). D1-D13 are accepted. Assumptions for user review:

1. The demo domain or subdomain (D14) is still open and blocks TLS and the CV link.
2. Notice text follows the exploration's suggestion; the contact email comes from the user.
3. The local host keeps running as in v0.2 when demo settings are absent.
4. The release eval criterion record is written before the first release run, with no data in hand.

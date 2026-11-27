# Exploration: v03-demo (Dale v0.3 "Probalo vos")

**Date**: 2026-11-26
**Base**: `dev` at `2e8dbe6` (v0.2 released at tag `v0.2`)
**Phase**: sdd-explore (read-only). Next: sdd-propose.
**Preflight**: execution_mode auto, artifact_store hybrid, delivery_strategy ask-on-risk, review_budget_lines 400.

## Goal (owner's plan, v0.3)

"Anyone can try it from the owner's CV, with no risk to the owner's account."

- Deploy on a small server.
- Per-visitor limits, a spend cap, an emergency stop and a notice that it is an automated assistant.
- The demo database resets itself.
- Conversations are saved, with notice, to turn failures into eval cases.
- The full suite runs before publishing each version.

## Current state

v0.2 is a single-operator local host.

- **Fixed loopback bind.** The host binds `127.0.0.1` as a constant (`src/dale/apps/web.py:54`, `:215-220`), one worker, `proxy_headers=False`. Spec W1 S1.1 (`openspec/specs/web-channel/spec.md:12-14`) and ADR 0005 ("Loopback only") forbid any flag that changes it.
- **One customer, one live conversation.** Every conversation is composed for one fixed customer (`DALE_WEB_CUSTOMER`, default `C-001`; `web.py:58,87,239-241`). `InMemoryRegistry.create` retires every earlier conversation (`src/dale/channels/web/conversations.py:349-372`). This is B65.
- **Why only one.** The verifier's run scope is the session customer's orders received since the conversation started, plus those for its proposals and the proposals shown confirmed (`src/dale/verifier/infrastructure/evidence.py:5-6,27-34`). Two conversations of one customer see each other's orders and get `unexpected_write`. B14 and B65 keep that scope as the net for unexpected writes and say "v0.3 gives each visitor its own customer".
- **No turn deadline.** The adapter calls the SDK with a 60 s timeout and 2 retries (`src/dale/brain/infrastructure/anthropic_model.py:19,44`). The SDK honors `retry-after` up to `min(retry_after, 4_294_967.0)` seconds, so in practice it is unbounded. A turn makes up to 6 model calls (`take_turn.py:40,93`). No request timeout exists (ADR 0004 D17, B61). The page `fetch` has no abort (`apps/web/src/api/client.ts:1-5`).
- **Threads.** Routes are sync on anyio's shared threadpool of 40 tokens (`conversations.py:131-134`). Every press spawns a verifier subprocess with a 30 s timeout (`verifier_runner.py:24-25,149-176`).
- **Conversation state is memory only.** No messages table: brain tables hold `conversation`, `order_proposal`, its lines and `handoff_request` (`migrations/versions/0003_brain_tables.py`). `ComposedBackend` drops each `TurnResult` (`web.py:168-170`), which carries `usage` per model call (`take_turn.py:59`, `model_port.py:38-42`): token accounting is possible but not done.
- **Existing limits.** Body cap 16 KiB (`guard.py:34`); `SendMessage` text up to 2000 characters (`contract.py:223`); the model sees the last 8 customer turns (`take_turn.py:40`); `max_tokens` 16,000 per call (`model_port.py:27`); lines and quantities bounded (`tools.py:33,237`), so the `Money` 2^53 bound is unreachable with seeded prices.
- **Host and Origin allow-list** take extra names from configuration (`DALE_WEB_ALLOWED_HOSTS`, `DALE_WEB_ALLOWED_ORIGINS`; `guard.py:57-64`, `web.py:86-88`): a public domain needs no code change.
- **Reseed** deletes and re-inserts El Hornero's `erp` rows in foreign-key order (`src/dale/erp_sim/infrastructure/seed/__init__.py:15-28`). Brain tables have no foreign key to `erp`. The seed has 7 active customers in 3 zones (`seed/el_hornero.py:35-43`).
- **Roles.** `db/roles.sql` sets no passwords. `dale_verifier` is SELECT-only and read-only by default.
- **CI** has no release or deploy workflow. Live evals exist behind `pytest evals --live [--record] [--report V] --model M`.
- **Cost basis.** A full Haiku run (40 cases x 3) costs USD 0.062, about USD 0.0016 per verified order (`docs/releases/v0.2.md`). Prices live in `evals/pricing.toml`, which the `dale` package does not import.

## Affected areas

- `src/dale/apps/web.py`: per-visitor customer factory; settings for limits, cap and deadline; proxy header handling; page path (`PAGE` at `:62` assumes a source checkout).
- `src/dale/channels/web/conversations.py`: many live conversations, caps, idle TTL, per-conversation turn cap, persistence hooks.
- `src/dale/channels/web/routes.py`, `guard.py`, `errors.py`, `contract.py`: cookie session, rate-limit and paused codes (additive to contract v1, W5), client identity.
- `src/dale/brain/infrastructure/anthropic_model.py`, `take_turn.py`: deadline and bounded retries.
- `src/dale/erp_sim/public.py`, `infrastructure/facade.py`: a port to create a visitor customer.
- `migrations/`: a `demo` schema for the control row, spend ledger, sessions and transcripts.
- `apps/web/src`: automated-assistant and data notice, accept-to-start, paused, limit and busy states.
- New: Dockerfile, compose file, Caddyfile, release and deploy workflow, operator CLI (pause, resume, status, export, purge), nightly reset job.
- Specs and ADRs: web-channel W14 (fixed customer becomes per-visitor), W17, W1 only if the bind changes; ADR 0004 (B65 superseded); ADR 0005 (it rejected a CSRF token because there were no cookies; a session cookie changes that premise).

## 1. Multi-visitor isolation

| Approach | Pros | Cons | Effort |
|---|---|---|---|
| A. New customer per conversation (`V-<random>`, cloned from a template customer's zone) | Verifier and run scope untouched; exact isolation; the nightly reseed wipes them | erp_sim needs a write port; customer rows grow until the reset; a zone must be chosen | Medium |
| B. Pool of N seeded customers leased per conversation | Pool size is the concurrency cap | A turn still running on the old lease can write after the next conversation starts (safe only with the deadline); lease table and expiry | Medium-High |
| C. Narrow the run scope to the conversation's proposals | Small change | Weakens the unexpected-write net B65 refused to narrow | Rejected |
| D. Schema or database per session | Strongest isolation | Migrations, grants and verifier role per tenant | High |
| E. One visitor at a time with a queue | No isolation change | An idle visitor holds the slot; queue UI | Low-Medium |

**Recommendation: A**, with a global cap on live conversations (about 10), a semaphore on concurrent turns (about 4, below the 40 threadpool tokens) and an idle TTL (about 30 min). It supersedes B65's "one live per host" without weakening the verifier: one customer has exactly one conversation.

## 2. Hosting (prices read 2026-11-26)

| Option | Monthly cost | Pros | Cons |
|---|---|---|---|
| VPS + Docker Compose + Caddy on the host: DigitalOcean Basic 2 GiB / 1 vCPU | USD 12 (verified); 1 GiB is USD 6 | Fits the stateful single-worker design and the subprocess verifier; keeps the `127.0.0.1` bind (Caddy and the app share the host network); separate PG roles easy; automatic TLS | The owner runs patching, backups and the firewall |
| VPS on Hetzner CX23 (2 vCPU / 4 GB) | EUR 5.99 with IPv4 | Same, cheaper | Every shared plan showed "currently unavailable" on 2026-11-26; check the Console |
| Fly.io shared-cpu-1x 1 GB + Postgres | App USD 6.70; managed PG Basic USD 38, or self-run PG at USD 2.19-3.69 | Simple deploy, TLS | Bind must change to 0.0.0.0 (W1 change); managed PG expensive; self-run PG roles and long requests unverified |
| Render 0.5c-512mb web + 0.1c-256mb PG | USD 7 + 6 | Managed, TLS | 512 MB tight for Python plus a verifier subprocess; bind change; request timeout unverified |
| Railway Hobby | USD 5 minimum including USD 5 usage | Cheap if small | Usage-based Postgres cost is unpredictable; bind change |
| Vercel + Neon | Hobby functions capped at 300 s; Neon Free suspends after 5 min | No server | Incompatible: in-memory conversations and locks, single worker, verifier subprocess, multi-minute turns |

**Recommendation:** a 2 GB VPS (DigitalOcean USD 12 verified; Hetzner if orderable).

- Postgres 17 container published only on `127.0.0.1:5432`, passwords from a root-only env file; roles `dale_owner` (migrations, one-shot), `dale_app`, `dale_verifier`.
- App container on host networking, still binding `127.0.0.1:8000`, so W1 and ADR 0005 stay.
- Caddy on the host for TLS and HSTS, `reverse_proxy 127.0.0.1:8000`; Caddy has no default response timeout, so long turns pass.
- Firewall: 22 restricted, 80 and 443 open.

## 3. Abuse and cost controls

- **Identity without login.** A random session id in a cookie (`HttpOnly; Secure; SameSite=Strict; Path=/`), stored server-side as an HMAC. Limits per session and per IP. The IP comes from Caddy's `X-Forwarded-For`, trusted only from loopback (today `proxy_headers=False`, `web.py:219`, so every client looks like 127.0.0.1). IPs only in memory, in a daily-rotated HMAC table, never in transcripts.
- **Default limits.** Per session: 1 turn in flight (exists), 3 conversations per day, 20 customer turns per conversation. Per IP: 60 turns per day. Global: 4 concurrent turns, 10 live conversations; above that, 503 "demo ocupada".
- **Spend cap in code.** A `BudgetedModel` wraps `ModelPort` in the apps layer (the brain does not change): before each call it checks `spent_today + worst_case_call <= daily_cap`; after it, it adds the cost from `Usage` to a `demo.spend_ledger` table that survives restarts. Worst case per Haiku call is about USD 0.008 of output plus input. Prices must be a runtime table inside `dale`. Refusals map to a new catalog code (`demo_paused` or `budget_exhausted`). (Superseded: the spend cap is an `AttemptGate` the adapter calls on every attempt, retries included, not a `BudgetedModel` wrapper; design DD27, log D19.)
- **API workspace limit as backstop.** A dedicated workspace with its own key, a monthly spend limit and per-minute rate limits.
- **Kill switch, layered.** (1) A `demo.control(paused)` row read before each turn and each model call; unreadable means paused (fail closed); flipped over SSH with an operator CLI (`dale-demo pause|resume|status`); no public admin endpoint. (2) The daily cap trips automatically. (3) Emergency: disable the demo key or archive the workspace in the Console.
- **Prompt injection.** Confirmation happens outside the model (ADR 0005), tools are scoped to the visitor's throwaway customer, and text renders as text (W10). The remaining risk is reputational: abusive text under the demo's name; mitigated by the notice, saved transcripts and the kill switch. No CAPTCHA in v0.3: Turnstile needs a third-party script origin, which breaks W10's CSP.

## 4. Turn deadline

| Approach | Pros | Cons |
|---|---|---|
| A. A deadline passed to the turn; the adapter uses `max_retries=0` and its own bounded retry loop | Deterministic, testable with a fake clock; leaves `request_params` and the prompt fingerprint unchanged | Touches the adapter and `TakeTurn` |
| B. Run the turn in a future and abandon it | Small | The turn keeps writing after the reply; breaks lock invariants |
| C. Async rewrite with cancel scopes | Real cancellation | Large; all DB code is sync |
| D. Subprocess per turn | Killable | `TakeTurn` state is in memory |

**Recommendation: A.** `TakeTurn` checks the time left before each model call; each attempt's timeout is `min(60, time left)`; retries on 429, 5xx or connection errors honor `retry-after` only if it fits; otherwise the turn fails as `MODEL_UNAVAILABLE` or a new `turn_deadline` code. Add `statement_timeout` on the `dale_app` engine. The B61 pins and the page's no-abort comment are updated; Caddy keeps no timeout. About 90 s per turn is a placeholder: latency p50/p95 is not recorded in the v0.2 reports, so measure it first. Keep `PRESS_WAIT` (60 s) above the verifier timeout (B60).

## 5. Database reset

Options: (a) scheduled nightly reset; (b) per-session fresh data purged by age; (c) template database clone.

**Recommendation: (a)** with per-visitor customers. A timer at about 04:00 America/Argentina/Buenos_Aires: pause; drain in-flight turns (deadline + verifier); clear the registry so live pages show "la demo se reinició"; `reseed` (wipes visitor customers and their orders) and delete brain rows of ended conversations; resume. Never reseed while a conversation is live: deleted orders would make the verifier report `missing` on a shown confirmation. Transcripts live in the `demo` schema, which reseed does not touch.

## 6. Saved conversations with notice

- **Storage.** Write-through rows in `demo.transcript_event`: conversation id, session HMAC, seq, kind (customer text, shown event, tool trace, verdict, usage, failure code), notice version, time. No restore after restart.
- **Retention.** Default 30 days, purged nightly.
- **Notice.** An always-visible banner plus accept-to-start before the first conversation. Suggested text: "Asistente automático de prueba. Datos ficticios. No escribas datos personales reales. Guardamos las conversaciones 30 días para mejorar el asistente." Plus a `/privacidad` static page and a README line.
- **PII.** Visitors may type real data. Store no IP or user agent. The repo is public: raw transcripts are never committed; a case is rewritten by hand.
- **Legal (not advice).** Argentina's Ley 25.326 and GDPR for EU visitors suggest minimal data, a stated purpose and a deletion contact.
- **Export.** `dale-demo export --since D --only-failures` writes JSONL of conversations with a non-verified verdict, a failure code, a refusal, the turn limit or a handoff; the owner writes `evals/cases/*.yaml` by hand.

## 7. Release gate

A `release.yml` on tag `v*`: verify the tag commit is on `main`; rerun the CI gates (replay); live eval `pytest evals --live --model claude-haiku-5-5` (no `--record`) with a key from a separate "dale-evals" workspace stored in a GitHub Environment `release` that needs approval (about USD 0.06 per release); build a multi-stage image (Node 24.22.2 page build, then uv Python) and push to GHCR; deploy over SSH (`compose pull`, one-shot `alembic upgrade` as `dale_owner`, `up -d`, smoke `/health`, roll back on failure). The live-run pass criterion is written down first (ADR 0007 style), e.g. hard gates at 0 and pass^3 at least the v0.2 level minus a margin.

## 8. Observability (minimal)

One JSON log line per request (conversation, session HMAC, latency, model calls, tokens, cost, failure code, verdict; never customer text, as today in `routes.py:93-95`), Docker or journald with rotation; `dale-demo status` (paused, spend today and this month, turns, live conversations, failures in 24 h); a free external uptime check on `/health`; Console usage and spend alerts. No browser error SDK (CSP).

## 9. Blockers for a public deploy

- `InMemoryRegistry` keeps one live conversation: a second visitor ends the first.
- Fixed customer, and `startup_error` checks only it (`web.py:97-106`).
- No turn deadline, with a 40-token threadpool: a few stuck turns can starve the host.
- `proxy_headers=False`: no client IP behind Caddy.
- No session, rate limits, spend accounting, kill switch or notice.
- `PAGE` resolved from the source tree (`web.py:62`).
- `db/roles.sql` has no passwords: production needs secrets and Postgres not exposed.
- The API key must be the demo workspace's, server-only.
- ADR 0005's "no cookies, so no CSRF token" premise needs a new ADR (SameSite=Strict plus the existing Origin and JSON checks still close CSRF).
- Not blockers: same-origin CSP (add HSTS in Caddy); the Host/Origin allow-list is configuration; the `Money` 2^53 bound is unreachable.

## Recommendation

Per-visitor customer with caps and TTL (replacing B65); adapter-level turn deadline; cookie session with per-session and per-IP limits; a `demo` schema for the control row, spend ledger and transcripts; notice with accept-to-start; nightly paused reseed; a 2 GB VPS with Compose and host-network Caddy keeping the loopback bind; a tag-on-main release workflow with an approved live Haiku eval, then deploy.

It exceeds 400 lines. Suggested chained slices: deadline; per-visitor customer and registry; session and limits; spend and kill switch; transcripts, notice and export; reset job and operator CLI; packaging (Dockerfile, compose, Caddy); release and deploy workflow with docs and ADRs.

## Decisions for the owner (recommended default in brackets)

1. Hosting provider and monthly budget [DigitalOcean Basic 2 GiB, USD 12/month; Hetzner CX23 at EUR 5.99 if orderable].
2. Domain or subdomain for the demo link [a subdomain of a domain the owner holds; a new domain costs about USD 10-15/year, unverified].
3. Daily spend cap enforced in code [USD 0.50/day].
4. Workspace monthly spend limit for the demo key [USD 15/month; a separate "dale-evals" workspace at USD 10].
5. Concurrency and visitor limits [4 concurrent turns, 10 live conversations, 3 conversations per session per day, 20 turns per conversation, 60 turns per IP per day, 30 min idle TTL].
6. Turn deadline [90 s, revisited after measuring p95].
7. Transcript retention [30 days, then purge].
8. Notice wording and the privacy page contact [the text in section 6, with a contact email for deletion requests].
9. Visitor customer zone [one fixed template in zone Centro; letting the visitor pick is the "customer picker" v0.2 left for v0.3].
10. Reset time and frequency [nightly at 04:00 Buenos Aires].
11. Release eval pass criterion and who approves the live run [hard gates = 0 and pass^3 at least 35/40; the owner approves the GitHub Environment].
12. Whether the public demo shows the tool-trace panel [yes; it is the point of the demo].

## Risks

- Hetzner showed every shared plan unavailable on 2026-11-26; Fly, Render and Railway prices come partly from undated pages or third parties.
- Visitor customers grow `erp.customer` until the reset; a reset during a live conversation gives false `missing` verdicts unless the drain is strict.
- The deadline changes ADR 0004 D17 and the B61 pins; a wrong value cuts slow but legitimate turns, and no latency data exists yet.
- Live evals are non-deterministic (Haiku pass^3 37/40): a release gate can fail on noise without a pre-registered criterion.
- Visitors may type real personal data; raw transcripts must never be committed.
- The Console workspace limit is monthly only: daily protection depends on the code cap and hand-synced prices.
- Cookies reopen the CSRF question ADR 0005 closed by assuming none.
- Reputational: injected abusive output under the owner's name; mitigated, not eliminated.
- Single VPS: no high availability; the owner runs backups and patching.

## Sources (retrieved 2026-11-26)

- https://www.hetzner.com/cloud/cost-optimized
- https://www.hetzner.com/cloud/regular-performance
- https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/
- https://www.digitalocean.com/pricing/droplets
- https://docs.fly.io/about/pricing
- https://render.com/pricing.md
- https://docs.railway.com/pricing/plans
- https://neon.com/pricing
- https://vercel.com/docs/functions/limitations
- https://platform.claude.com/docs/en/manage-claude/workspaces
- https://caddyserver.com/docs/caddyfile/directives/reverse_proxy

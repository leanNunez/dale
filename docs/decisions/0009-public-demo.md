# 0009. Public demo: visitors, limits, spend cap, kill switch and reset

Date: 2026-11-26
Status: accepted (decided before the code: the demo lands in slices 3 to 12 of `v03-demo`)

## Context

v0.2 is a single-operator loopback host: one fixed customer (`DALE_WEB_CUSTOMER`, default `C-001`,
`src/dale/apps/web.py:87`), one live conversation (B65, recorded in
[decision 0004](0004-web-host-transport-channel-boundary.md)), no limits and no spend
accounting. v0.3 links the demo from a CV, so anyone may use it, and the model key behind it
belongs to the owner. This record fixes the controls a public demo needs and nothing more. It
states DD26, DD27, DD31 to DD33, DD37 to DD40 and DD43 of the `v03-demo` design and log D4, D6,
D8, D9, D11, D15, D17 and D19. Cookie sessions and CSRF are in
[decision 0010](0010-cookie-session-csrf-client-ip.md), the turn deadline in
[decision 0011](0011-turn-deadline-bounded-retries.md), hosting in
[decision 0012](0012-hosting-release-deploy.md) (hosting, release and deploy).

## Decision

| Topic | Decision |
|---|---|
| Demo mode (DD26) | A host runs in demo mode only when started with `DALE_WEB_MODE=demo` (planned). Without it the host is in local mode and behaves as in v0.2: fixed customer, one live conversation, no cookie, no limits, no control row. Demo code lives in a new package `dale.apps.demo` (SQL, CLI, reset, prices, settings), a new module `dale.apps.web_demo` (wiring) and small pieces in `dale.channels.web`. `src/dale/apps/web.py` stays a module and gains a mode switch. A demo host refuses to start (exit 2) when a required setting is missing or invalid, or when the template customer, a price entry for the model or the scheduler is missing |
| Visitor customers (DD31, log D4) | Each demo conversation gets a new customer, cloned from a configured template customer in zone Centro (the seed has `C-001` and `C-002` there, `src/dale/erp_sim/infrastructure/seed/el_hornero.py:36-37`). The code is `V-` plus 10 random hex digits, the id a random UUID. Creation goes through a separate `VisitorCustomers` port of `erp_sim`, held only by `dale.apps.web_demo`; the brain's tools gain no write path. If the visitor cannot be created, the conversation is not created and no shared customer is used. The nightly reseed removes visitors, because its deletes are scoped by company (`src/dale/erp_sim/infrastructure/seed/__init__.py:15-26`). `dale_app` already has INSERT on `erp` (`migrations/versions/0001_schemas_and_grants.py:22-23`), so no grant changes |
| B65 superseded in demo mode only | B65's one-live-conversation rule is replaced in demo mode by many conversations with caps. In local mode B65 and 0004's row on it stand unchanged. The verifier's run scope (the session customer's orders received since the conversation started) is not narrowed: each visitor has a customer of their own, so two live conversations no longer see each other's orders, and the net for unexpected writes stays exactly as it was (v0.2 B14) |
| Registry and caps (DD43, log D9) | The registry port gains an optional visitor argument, `create(visitor=None)` and `using(id, visitor=None)`; the in-memory registry ignores it. A new `DemoRegistry` holds up to 10 live conversations, binds each to the session that created it, ends one with no request for 30 minutes (never one with a request in flight), counts requests in flight, and leaves tombstones after a reset. It is one object under one mutex. Limits are settings with these defaults: 4 concurrent turns, 10 live conversations, 3 conversations per session per day, 20 customer turns per conversation, 60 turns per IP per day, 10 conversations per IP per day (log D17), 30 minutes idle TTL |
| Counters (DD37) | The daily counters live in the database (`demo.counter`), as a conditional increment that returns no row when the limit is reached. A create's session counter and IP counter run in one transaction, so a refusal consumes neither. The IP is stored only as a keyed hash whose key rotates every day, never in clear. Counting runs last in the request order, so a busy or invalid request never consumes a turn. A store error answers `demo_paused` (fail closed) |
| Spend cap (DD27, DD38, DD39, log D6, D15, D19) | The cap is USD 0.50 per Buenos Aires day, enforced in code, backed by a USD 15 per month limit on the demo workspace (log D7). The cap is checked and reserved before every model attempt, retries included, through an `AttemptGate` port that the adapter calls around each attempt (a wrapper around `ModelPort` would not see its retries). The reservation is the worst case: an upper bound of the input tokens (the UTF-8 bytes of the request plus 2,000 framing tokens) at the higher of the input and cache-write prices, plus `max_tokens` at the output price, in integer micro-USD, rounded up. It is reserved atomically in `demo.spend_day`, then settled to the actual cost from the reported usage; unknown usage stays at the worst case, and a crash between reserve and settle keeps the reservation. The ledger survives restarts and the reset. A runtime price table in `dale.apps.demo.prices` must equal `evals/pricing.toml`; a unit test and the release check compare them. `None` for the gate means no accounting, so local mode and the evals are untouched |
| Kill switch (DD33) | One control row (`demo.control`) holds `paused` and a reason: `initial`, `operator`, `reset` or `deploy`. It is read before each conversation, turn, press and model attempt; paused or unreadable means paused (`demo_paused`). A fresh database starts `paused, initial`. A reset or deploy pause is conditional on not already being paused, and its resume applies only to its own reason, so neither resumes an operator's pause. Only the operator's commands on the server (`pause` and `resume`) and the host's own reset change it; no HTTP route reads or writes it. `/health`, the contract and the page stay served while paused |
| Reset (DD32, log D11) | An in-process scheduler thread resets nightly at 04:00 America/Argentina/Buenos_Aires, or at the first tick after a missed one: pause with reason `reset`, drain through the registry's in-flight counter (the drain bound is a setting, 240 s by default, and the host refuses to start unless it exceeds max(turn deadline + 5 s statement round + 30 s verifier, `PRESS_WAIT` 60 s + 30 s verifier) + 30 s margin, log D23), end every conversation, reseed, then resume. Ended ids answer `demo_reset` until restart. The reseed runs only when nothing is in flight and every conversation has ended: a reseed under a live conversation would give false `missing` verdicts. A drain timeout or a failed reseed leaves the demo paused and visible in `status`. The drain cannot be exact: a reply that trickles in has no hard upper bound (the `httpx` read timeout is per chunk, [decision 0011](0011-turn-deadline-bounded-retries.md)), so such a request can outlast the bound. That is a residual risk, and the outcome is fail closed: no reseed, a paused demo |
| Transcripts (DD40, log D8) | Each conversation is written through to the `demo` schema, which the reseed never touches: customer text, shown events, tool traces, verdicts, failure codes, usage and cost, the accepted notice version and the session's keyed hash. Never an IP, user agent, raw token, cookie or header. They are kept 30 days and purged nightly. A write failure is logged and counted and never changes a reply. The page shows the conversation reference so a deletion request can name it (log D16) |
| Fail closed | An unreadable control row, ledger or counter store gives `demo_paused` or an unsent request. A missing price entry, template customer, setting or scheduler stops the host at startup. A heartbeat or transcript write that fails is only logged |

## Alternatives rejected

- A `BudgetedModel` wrapper around `ModelPort` (the proposal's sketch). It sees one call per turn
  step, not the adapter's retries, so it cannot count every attempt.
- A leased pool of customers, a narrower verifier scope, a schema per session, or one visitor at a
  time, instead of a customer per conversation. Each weakens the verifier's net or limits use.
- A reset by restarting the container or by an external CLI. Neither can see in-memory work in
  flight, and a restart has no `demo_reset` code.
- Keeping every counter in memory. Per-IP limits would reset on every deploy.
- A public admin endpoint for the kill switch. It would add an attack surface to a host that has
  none; the operator already has SSH.

## Consequences

- Conversation state is still in memory, so a deploy or restart ends live conversations. Restoring
  them is out of scope.
- During an API outage, worst-case reservations can exhaust the day's cap. This is intended;
  `status` shows open and unknown reservations, and a new day starts a new cap.
- Visitors may type real personal data. The notice, the 30-day purge, the absence of IPs and user
  agents and the deletion contact reduce the risk but do not remove it; this record is not legal
  advice.
- Per-session limits are weak against a client that clears its cookie, so the per-IP limits are
  the real bound (log D17). The limits are settings, to be revisited after launch.
- A request that outlasts the drain bound leaves the demo paused until the operator looks at
  `status` and resumes it. That costs availability, not integrity, and is the intended side of the
  trade.
- Local mode is unchanged, so the v0.2 tests keep passing as they are.

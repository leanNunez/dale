# Spec: demo-operations (v0.3 "Probalo vos")

New capability. Behavior only; structure and storage are decided in design. Keywords follow RFC 2119. All data is fictitious ("Distribuidora El Hornero"); IP addresses come from documentation ranges. Requirement prefix `O` (operations); `D` is taken by the decision log.

## Purpose

The controls a public demo needs so anyone can try Dale from a link with no risk to the owner's account: visitor sessions and limits, a spend cap, a kill switch, a notice, saved transcripts and a nightly reset. Web behavior is in `web-channel`; turn deadline in `verified-order` R9; release and deploy in `release-gate`.

Terms: **demo mode** and **local mode** as in `web-channel`. **Day** = a calendar day in America/Argentina/Buenos_Aires. **Control state** = the persistent running/paused flag with its reason. **Spend ledger** = the persistent record of model cost. **Model request** = one request attempt to the model API, retries included.

## Settings and defaults

All values are settings (decisions D6, D8, D9, D10, D11); defaults:

| Setting | Default |
|---|---|
| Concurrent turns (global) | 4 |
| Live conversations (global, `web-channel` W17) | 10 |
| Conversations per session per day | 3 |
| Customer turns per conversation | 20 |
| Turns per IP per day | 60 |
| Conversations per IP per day | 10 |
| Idle TTL (`web-channel` W17) | 30 min |
| Turn deadline (`verified-order` R9) | 90 s |
| Daily spend cap | USD 0.50 |
| Transcript retention | 30 days |
| Nightly reset | 04:00 America/Argentina/Buenos_Aires |

## O1. Demo mode

Demo controls MUST be active only in demo mode. In demo mode the host MUST refuse to start when any required demo setting is missing or invalid: the limits above, the spend cap, a price entry for the configured model, the session secret, the template customer and the privacy contact. In local mode none of O2-O11 applies.

- **S1.1 Incomplete settings (negative)** Given demo mode and no privacy contact configured, then the host refuses to start.
- **S1.2 Local mode** Given no demo settings, then the host starts with v0.2 behavior and reads no control state, ledger or session.

## O2. Visitor session

The host MUST identify each visitor by a random, unguessable session ID carried in the session cookie (`web-channel` W8) and MUST store only a keyed hash of it. A conversation MUST be bound to the session that created it. A request for a conversation with no session cookie, or with another session's, MUST be rejected with `conversation_not_found`. A request with no valid session MUST receive a new session.

- **S2.1 Issued** Given a visitor with no cookie, when the page is loaded or a conversation requested, then a session cookie is set and only its keyed hash is stored.
- **S2.2 Foreign session (negative)** Given a conversation created by session A, when session B sends a message or presses Dale for it, then the request gets `conversation_not_found` and nothing executes.

## O3. Visitor and global limits

In demo mode the host MUST enforce, before any turn or model call:

| Limit | Exceeded code |
|---|---|
| Conversations per session per day | `rate_limited` |
| Customer turns per conversation | `rate_limited` |
| Turns per IP per day | `rate_limited` |
| Conversations per IP per day | `rate_limited` |
| Concurrent turns | `demo_busy` |

A rejected request MUST execute nothing, MUST NOT call the model and MUST NOT consume a turn. Per-IP counters MUST be keyed by a keyed hash whose key changes at least daily; the IP in clear MUST NOT be written to the database, logs or transcripts. Counters MAY reset on a host restart. When a limit cannot be evaluated, the request MUST be rejected.

- **S3.1 Session conversations** Given a session that created 3 conversations today, when it requests a 4th, then it gets `rate_limited` and no visitor customer is created.
- **S3.2 Conversation turns** Given a conversation with 20 customer turns, when a 21st message arrives, then it gets `rate_limited` and the model is not called.
- **S3.3 IP turns** Given 60 turns today from `203.0.113.7` across several sessions, when a 61st arrives from that IP, then it gets `rate_limited`.
- **S3.4 Concurrent turns** Given 4 turns in flight, when a 5th turn is requested in another conversation, then it gets `demo_busy`.
- **S3.5 Limit store fails (negative)** Given the counter store raises an error, when a turn is requested, then it is rejected and the model is not called.
- **S3.7 IP conversations (negative)** Given 10 conversations created today from `203.0.113.7` across sessions that cleared their cookie, when an 11th is requested from that IP, then it gets `rate_limited` and no visitor customer is created.
- **S3.6 No clear IP (negative)** Given any number of requests, then no database row, log line or transcript contains a client IP in clear.

## O4. Spend cap and ledger

In demo mode, before each model request the host MUST check that today's recorded spend plus the reservations of requests in flight plus the worst-case cost of this request does not exceed the daily cap; otherwise the request MUST NOT be sent. The worst-case cost MUST use the request's maximum output tokens and an upper bound of its input tokens, at the model's prices in a dated runtime price table inside the `dale` package. The check and the reservation MUST be atomic with respect to other model requests. After each request the host MUST record its cost from the reported usage in the spend ledger, which MUST survive restarts and the nightly reset; a request whose usage is unknown MUST be recorded at its worst-case cost. A refused request MUST end the turn as a failed turn with `model_unavailable` (`verified-order` R9) and no order. A turn or conversation request MUST get `demo_paused` while today's spend plus the worst-case cost of one request exceeds the cap. The cap MUST fail closed: when the ledger cannot be read or written, no model request MUST be sent.

- **S4.1 Under the cap** Given today's spend well under USD 0.50, when a turn runs, then each request is sent and its cost is recorded.
- **S4.2 Cap reached (negative)** Given today's spend plus the worst-case cost exceeds USD 0.50, then the request is not sent, no order is created, and the next turn gets `demo_paused`.
- **S4.3 Restart (negative)** Given the ledger at the cap and a host restart, when a turn is requested, then it gets `demo_paused` and no request reaches the API.
- **S4.4 Concurrent reservations (negative)** Given room for only one worst-case request, when two turns request a model call at once, then exactly one request is sent.
- **S4.5 Ledger unreadable (negative)** Given the ledger cannot be read, then no request is sent and the turn gets `demo_paused`.
- **S4.6 Usage unknown** Given a request that times out with no usage reported, then the ledger records its worst-case cost.
- **S4.7 New day** Given yesterday ended at the cap, when a turn arrives after midnight in Buenos Aires, then requests are sent again.
- **S4.8 No price entry (negative)** Given demo mode and a configured model missing from the price table, then the host refuses to start.

## O5. Kill switch

In demo mode the host MUST read the control state before each turn, each conversation creation, each press and each model request. When it is paused, or cannot be read, the host MUST treat the demo as paused: new conversations, turns and presses get `demo_paused`, and an in-flight turn's next model request is not sent (the turn ends as in O4). A pause MUST take effect without a restart. `GET /health`, the contract and the page MUST stay served while paused. No HTTP route MAY change the control state.

- **S5.1 Pause** Given a running demo, when the operator pauses it, then the next turn request gets `demo_paused` and the model is not called.
- **S5.2 Unreadable is paused (negative)** Given the control state cannot be read, when a turn or press is requested, then it gets `demo_paused` and nothing executes.
- **S5.3 Mid-turn pause (negative)** Given a turn in flight, when the demo is paused before its next model request, then that request is not sent and no order is created.
- **S5.4 No admin route (negative)** Given the route table, then no route reads or changes the control state.
- **S5.5 Resume** Given a paused demo, when the operator resumes it, then the next turn is handled.

## O6. Operator CLI

An operator CLI run on the server MUST provide `pause`, `resume` and `status`, plus `export` (O10) and `purge` (O9). `pause` and `resume` MUST be idempotent and MUST exit non-zero when the control state cannot be written. `status` MUST report the control state and reason, today's and this month's spend against the cap, live conversations, turns today, failures in the last 24 hours and the last reset result, and MUST NOT print customer text, IPs, session IDs or keys.

- **S6.1 Status** Given a running host, when `status` runs, then it prints the listed fields and no customer text.
- **S6.2 Write fails (negative)** Given the control state cannot be written, when `pause` runs, then it exits non-zero and reports the failure.
- **S6.3 Idempotent** Given a paused demo, when `pause` runs again, then the state stays paused and the command succeeds.

## O7. Notice and accept-to-start

In demo mode the page MUST always show a Spanish banner stating that this is an automated test assistant, that the data is fictitious, that visitors must not type real personal data, and that conversations are kept for the retention period, with a link to the privacy page. The host MUST NOT create a conversation unless the request carries acceptance of the current notice version; otherwise it MUST reply `notice_not_accepted`. The accepted version MUST be recorded with the conversation's transcript. A new notice version MUST require a new acceptance. The wording MUST be approved by the owner before release.

- **S7.1 Banner** Given the demo page, then the banner is visible in every page state and links to the privacy page.
- **S7.2 Not accepted (negative)** Given a request to create a conversation without acceptance, then it gets `notice_not_accepted`, no visitor customer is created and the model is not called.
- **S7.3 Stale version (negative)** Given an acceptance of an older notice version, then the request gets `notice_not_accepted`.

## O8. Privacy page

In demo mode the host MUST serve a static `/privacidad` page from the same origin with the page's CSP (`web-channel` W10). It MUST state, in Spanish, the purpose of storage, what is stored, that IP and user agent are not stored, the retention period, and the deletion contact from settings.

- **S8.1 Content** Given a request for `/privacidad`, then it returns the page with the CSP, the retention period and the configured contact.

## O9. Transcripts and retention

In demo mode the host MUST save, per conversation: customer text, shown events, tool traces, verdicts, failure codes, per-request usage and cost, the accepted notice version, the session's keyed hash and times. Transcripts MUST NOT contain an IP, user agent, raw session ID, cookie, request headers or key. Transcripts MUST survive the nightly reseed and MUST be purged once older than the retention period, at least nightly. The page MUST show the current conversation's reference, and the privacy page MUST ask a visitor to include it in a deletion request. The operator MUST be able to delete one conversation's transcripts by that reference with `purge`. A transcript write failure MUST be logged and counted in `status` and MUST NOT change the turn's outcome. Log lines MUST NOT contain customer text, IPs, user agents or raw session IDs. Raw transcripts and exports MUST NOT be committed; the tracked-files CI gate MUST fail when an export file is tracked.

- **S9.1 Saved** Given a conversation with a turn and a press, then its transcript holds the customer text, shown events, trace, verdict, usage and notice version.
- **S9.2 No identifiers (negative)** Given any transcript row, then it contains no IP, user agent, raw session ID or header.
- **S9.3 Retention** Given transcripts aged 31 and 29 days, when the nightly purge runs, then only the 31-day transcript is deleted.
- **S9.4 Deletion request** Given a conversation ID, when `purge` runs for it, then none of its transcript rows remain.
- **S9.6 Reference shown** Given a live conversation, then the page shows its reference, and `purge` with that reference deletes that conversation's transcript rows only.
- **S9.5 Export not committable (negative)** Given an export file added to the index, then the tracked-files gate fails.

## O10. Failure export

`export --since <date> --only-failures` MUST write JSONL with one line per conversation within retention that had a non-verified verdict, a catalog or transport failure code, a refusal, the turn limit, the turn deadline or a handoff. It MUST include no data O9 forbids. Cases are written from it by hand; no automatic conversion exists.

- **S10.1 Only failures** Given one verified conversation and one with a `mismatch` verdict, when the export runs, then only the second appears.
- **S10.2 Beyond retention (negative)** Given `--since` earlier than the retention period, then purged conversations do not appear.

## O11. Nightly reset

At the reset time the host MUST, in order: pause with reason `reset`; drain, waiting until no turn or press is in flight, up to a bound (setting) above the turn deadline plus the verifier timeout; end every live conversation; reseed the `erp` data, removing visitor customers and their orders, and delete brain rows of ended conversations; purge expired transcripts (O9); resume. The reseed MUST NOT touch the control state, spend ledger, sessions or transcripts. Until the host restarts, an ID ended by the reset MUST get `demo_reset`. The reseed MUST NOT run while any conversation is live or any request is in flight. If the drain exceeds its bound or the reseed fails, the demo MUST stay paused and `status` MUST report the failure. The reset MUST NOT resume a demo the operator paused.

- **S11.1 Reset** Given live conversations and none in flight, when the reset runs, then they end, their IDs get `demo_reset`, visitor customers are gone, the template remains, and the demo resumes.
- **S11.2 In flight waits** Given a turn in flight at 04:00, then the reseed starts only after it ends, and a request arriving meanwhile gets `demo_paused`.
- **S11.3 Drain timeout (negative)** Given a request still in flight when the drain bound elapses, then no reseed runs and the demo stays paused.
- **S11.4 Reseed fails (negative)** Given the reseed raises an error, then the demo stays paused and `status` reports it.
- **S11.5 Operator pause kept** Given the operator paused the demo before the reset, then after the reset it is still paused.
- **S11.6 Demo data kept** Given ledger entries and transcripts within retention, then the reset leaves them unchanged.

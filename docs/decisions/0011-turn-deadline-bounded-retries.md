# 0011. Turn deadline and bounded retries

Date: 2026-11-26
Status: accepted (decided before the code: the deadline lands in slices 2a to 2d of `v03-demo`)

## Context

[Decision 0004](0004-web-host-transport-channel-boundary.md) (D17) left a turn with no upper
bound and marked a turn deadline as pending and required before a public demo. Today a turn makes
at most 6 model calls (`src/dale/brain/application/take_turn.py:40`), each with a 60 s timeout and
2 SDK retries (`src/dale/brain/infrastructure/anthropic_model.py:19,44`), plus a 30 s verifier
(`src/dale/apps/verifier_runner.py:25`). That is about 18.5 minutes in the ordinary case, and
the SDK waits as long as a `retry-after` header asks, so the wait has no bound at all. A public
visitor holds a worker thread for that time, and v0.2 B61 pins the host's lack of any request
timeout (`tests/unit/test_web_app.py:63-72`). The deadline must therefore live in the brain and
its adapter, where the waiting happens. This record states DD28 to DD30 of the `v03-demo` design
and log D10 and D18.

## Decision

| Topic | Decision |
|---|---|
| Deadline (DD28, log D10) | A turn has a wall-clock deadline measured from its start, default 90 s, a setting (`DALE_TURN_DEADLINE_SECONDS`, planned) on the terminal and on the web. It travels as an optional field of `ModelRequest`, declared with `compare=False, repr=False` and default `None` (planned), so existing constructors, fakes and equality checks keep working |
| Prompt path untouched | `request_params` (`anthropic_model.py:22-32`), the prompt fingerprint and the messages digest never read the deadline. The fingerprint pin and every committed Haiku and Sonnet recording must replay as they are (R9 S9.9) |
| Check before each call | `TakeTurn` checks the time left before each model call and does not start a call when none is left. The turn then ends as a failed turn with the new catalog code `turn_deadline_exceeded`, with no order and no `OrderConfirmed`. What the turn completed stays, as in v0.1 B75 (planned, slice 2b) |
| Status | `turn_deadline_exceeded` answers HTTP 504 with a Spanish customer-facing message (log D18, planned, slice 2a). It is a brain code in the `ErrorCode` catalog, next to `model_unavailable` (`src/dale/shared/errors.py:25,46`), and an addition to contract v1 (web-channel W5, W11) |
| Error type | `DeadlineExceededError` is a subclass of `ModelUnavailableError` and is caught before it (`take_turn.py:97` is the existing catch), so `RecordingModel`'s handler still marks a deadline as a failed run |
| Retry loop (DD29) | The SDK's own retries are turned off (`max_retries=0`), and the adapter runs its own loop: at most 3 attempts, each with a timeout of `min(60, time left)`. It retries on 408, 409, 429, 5xx and connection or timeout errors, and follows `x-should-retry` as the SDK does. It waits for `retry-after-ms` or `retry-after` when present, else 0.5 s and then 1 s, and only when the wait fits in the time left |
| Minimum per attempt (log D18) | An attempt needs at least 1 s left. Under 1 s the adapter raises `DeadlineExceededError` and sends and reserves nothing |
| No deadline | With no deadline (`None`) a `retry-after` wait is capped at 30 s, so a caller with no deadline is still bounded. `sleep` and the clock are injected, so tests use a fake clock |
| Startup (R9 S9.11) | A deadline not greater than the verifier timeout (30 s) is refused at startup: the terminal and the web host exit with status 2. The 90 s default sits above it. A deadline at or below 30 s could cut a turn while its verifier still runs |
| Statement timeout (DD30) | One shared `app_engine(url)` in `dale.apps.compose` (planned) sets `statement_timeout=5000`, `lock_timeout=3000` and `idle_in_transaction_session_timeout=30000` as engine options (30 s, not 10 s: the proposal lock's transaction sits idle while management confirms on another connection, so it must outlast several statement rounds; `v03-demo` log D31), on top of the existing `connect_timeout=3` (`src/dale/apps/web.py:202`). The web host and the terminal both use it; the terminal builds a plain engine today (`src/dale/apps/terminal.py:63`). An integration test reads `SHOW statement_timeout` |

## What this amends

- **0004, D17 (request timeouts).** "A turn has no fixed upper bound" and "a turn deadline inside
  the brain is pending and is required before a public demo" no longer hold. A turn is now
  bounded by the deadline, plus at most one tool round of database statements (each under the 5 s
  statement timeout), plus the 30 s verifier. The rest of D17 stands: the server sets no request
  timeout and the page sets no abort, because a sync turn still cannot be cancelled in Python.
- **v0.2 B61 (pinning the lack of a request timeout).** The pins stay as they are: uvicorn
  and the host still set no request timeout (`tests/unit/test_web_app.py:63-72`), and the page's
  no-abort comment (`apps/web/src/api/client.ts:2`) is restated to name the new bound instead of
  "a turn may run for minutes". What changes is the reason the lack of a timeout is safe: the
  brain stops waiting, not the host.
- **0004's closing line** "A turn deadline inside the brain is not part of v0.2 (Known pending)"
  is resolved by this record.
- **0005, Consequences** ("a turn or press may run for minutes and no request timeout cuts it").
  It still holds that no request timeout cuts a turn, and the press lock still waits at most
  60 s. A turn no longer runs for minutes: the brain bounds it as in 0004 above. The Vite proxy
  comment (`apps/web/vite.proxy.ts`) is restated the same way as the page's.

## Alternatives rejected

- Keeping the SDK retries and capping only the per-attempt timeout. The SDK honors any
  `retry-after`, so one rate-limit response could still hold a thread for as long as the header
  asks.
- A `complete(request, deadline)` signature. Every fake, `ReplayModel` and `RecordingModel` would
  change, and a deadline that is not part of the request is easy to drop in a wrapper.
- A thread-local deadline. It is hidden state: a test cannot see it and a thread pool can leak it.
- A server-level request timeout. A sync turn cannot be cancelled, so it would drop the response
  while the turn kept running and holding its resources.
- `ALTER ROLE dale_app SET statement_timeout` in `db/roles.sql`. It would also bind the CLI and the
  reseed, and it would not exist on a database whose roles were created another way. Engine
  options travel with the code and a test can check them.

## Consequences

- The bound is honest but not exact, and for one case it does not exist. `httpx` timeouts bound
  each phase of a request, not its total: the read timeout applies to each chunk, so a reply that
  trickles in a few bytes at a time can outlast the attempt timeout, and the deadline, by any
  amount. A reply that is not streamed normally arrives in one piece, so in practice the read
  phase is the whole wait, but the trickle has no hard upper bound. This is a residual risk, not
  one this record closes. The check before each attempt and the minimum of 1 s only stop a new
  attempt from starting late. What contains it is the nightly reset's drain ([decision 0009](0009-public-demo.md)): it
  waits a bounded time for requests in flight, and when one is still running it leaves the demo
  paused and does not reseed (fail closed). The release live run measures p50 and p95 turn time,
  and the deadline is a setting to revisit with that data (log D10, D23).
- The 90 s default is above the verifier timeout and has no latency data behind it. It is a
  first value, not a finding.
- An attempt the deadline refuses costs nothing: nothing is sent and, with the spend gate of
  [decision 0009](0009-public-demo.md) (public demo), nothing is reserved.
- A turn cut by the deadline may have shown a proposal summary. The proposal stays confirmable
  only by the Dale action, with revalidation (R4, R5, S9.8); a typed "dale" still confirms
  nothing.
- Reverting the adapter slice restores the SDK retries and the unbounded wait. The deadline field
  and the catalog code stay, because they change no request parameter.

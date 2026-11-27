# Delta for verified-order (v0.3 "Probalo vos")

Base: `openspec/specs/verified-order/spec.md` (R1-R16). Modified blocks are complete replacements. Behavior only; mechanics are decided in design. Keywords follow RFC 2119. All data is fictitious ("Distribuidora El Hornero").

Terms added: **turn deadline** = the wall-clock limit on one conversation turn, on every channel. **Failed turn** = a turn that ends with a catalog code instead of a reply; what it completed stays, as decided in v0.2 (decision-log v0.1 B75).

## MODIFIED Requirements

### R9. Closed tool list and turn limit

The agent MUST have exactly five tools: search products, check prices, check delivery, prepare order, request human handoff. Any other tool name MUST be denied. A turn limit MUST bound each conversation turn's loop. Reaching it MUST end the turn without creating an order.

Each turn MUST also have a wall-clock deadline (setting, default 90 s, decision D10), on the terminal and on the web, measured from the start of the turn:
- Before each model call, code MUST check the time left and MUST NOT start the call when none is left.
- Every model request attempt MUST be bounded by the time left. Retry attempts MUST be bounded in number. A retry wait, including a server `retry-after`, MUST be taken only when it fits in the time left.
- Database statements made during the turn MUST be bounded by a statement timeout shorter than the deadline.
- When the deadline is reached, the turn MUST end as a failed turn with the catalog code `turn_deadline_exceeded` and its customer-facing message. It MUST NOT create an order and MUST NOT show `OrderConfirmed`. A proposal whose summary the turn already showed stays confirmable only by the Dale action (R4), with revalidation (R5).
- The deadline MUST NOT change model request parameters, the system prompt, tools or messages.
- A configured deadline not greater than the verifier timeout MUST be rejected at startup.
(Previously: an iteration limit only; model calls had no wall-clock bound, and SDK retries could wait an unbounded `retry-after`.)

- **S9.1 Unknown tool (negative)** Given the model requests a tool outside the list, then the call is denied and nothing executes.
- **S9.2 Turn limit** Given the model keeps calling tools past the limit, then the loop stops, no order is created, and the customer receives a safe message.
- **S9.3 Deadline reached (negative)** Given a fake clock where each model call takes 40 s, when a turn needs four calls, then the turn ends at or before 90 s with `turn_deadline_exceeded`, no order is created, and no `OrderConfirmed` is shown.
- **S9.4 Retry-after beyond the deadline (negative)** Given 30 s left and a rate-limit response with `retry-after` of 60 s, then no wait happens, no further request is sent, and the turn ends with `turn_deadline_exceeded`.
- **S9.5 Retry-after that fits** Given 30 s left and a `retry-after` of 5 s, then the attempt is retried after the wait and the turn continues.
- **S9.6 Bounded retries (negative)** Given the model API fails on every attempt with a retryable error and time remains, then the number of attempts does not exceed the configured bound and the turn ends with `model_unavailable`.
- **S9.7 Terminal** Given the terminal channel and the deadline is reached, then the customer sees the `turn_deadline_exceeded` message and no order is created.
- **S9.8 Shown proposal kept** Given a turn that showed a proposal summary and then reached the deadline, when the customer types "dale", then nothing is confirmed; when the Dale action is received, then management revalidates and confirms.
- **S9.9 Fingerprint unchanged** Given the committed eval recordings, then they replay with the deadline in place and every request's parameters equal the recorded ones.
- **S9.10 Slow statement (negative)** Given a database statement during a tool call that exceeds the statement timeout, then it is cancelled, the tool reports a catalog code, and no order is created.
- **S9.11 Invalid setting (negative)** Given a deadline equal to or below the verifier timeout, then the host or terminal refuses to start.

## ADDED Requirements

None. `turn_deadline_exceeded` is a new code in the R6 catalog, with a customer-facing message (S6.2).

## REMOVED Requirements

None.

## Unchanged requirements

R1-R8 and R10-R16 stay exactly as in the base spec. R11 is explicitly unchanged: the verifier's run scope stays the session customer's orders received since the conversation started, plus those for its proposals and the proposals shown confirmed. Per-visitor customers (`web-channel` W14) make that scope hold for many live conversations without narrowing it.

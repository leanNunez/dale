# Spec: web-channel (v0.2 "Se ve")

New capability. Behavior only; structure, package layout and numeric limits are decided in design.
Keywords follow RFC 2119. All data is fictitious ("Distribuidora El Hornero").

Terms: **host** = the local HTTP process serving the API and the static page. **Contract v1** = the versioned set of events, commands and components exchanged between page and host. **Envelope** = `{v, seq, conversation_id, type, data}` wrapping every event. **Dale button** = the page control that posts the press. **Press** = a `PressDale` command carrying a proposal ID. Other terms (proposal, verified, gauchada) are defined in `verified-order`.

Out of scope here (v0.3): deploy, per-visitor limits, spend cap, kill switch, auto-reset database, saved conversations, cookie session, customer picker, WebSocket. Extension points that v0.3 relies on are stated in W17.

## W1. Local binding and same-origin serving

The host MUST bind to `127.0.0.1` only and MUST serve the built page from the same origin as the API. The host MUST NOT enable CORS.

- **S1.1 Loopback only** Given the host starts with default settings, then it listens on `127.0.0.1` and on no other interface.
- **S1.2 Same origin** Given the built page, when it is requested from the host, then the API and the page share one origin and no CORS response header is sent on any route.

## W2. Resource surface

The host MUST expose exactly: create conversation, send message, confirm, cancel, read contract, and health. No route other than confirm MAY create or confirm an order. No route MUST be reachable from tool output or model text.

- **S2.1 Route table** Given the application route table, then it contains only the listed operations and exactly one route that can lead to `ConfirmProposal`.
- **S2.2 Unknown route (negative)** Given a request to a path outside the table, then it is rejected with the error envelope.

## W3. Events and envelope

Every event sent to the page MUST be wrapped in the envelope. `v` MUST be the contract version, `seq` MUST increase by one per event within a conversation starting at 1, and `type` MUST be one of: `AssistantText`, `ProposalSummary`, `OrderConfirmed`, `OrderRejected`, `HandoffNotice`, `SystemNotice`, `ToolCalled`, `VerdictIssued`. `ToolCalled` and `VerdictIssued` MUST NOT be part of the shown events the verifier parses. A `ToolCalled` event MUST carry the tool name, an argument summary and ok or an error code. Its text is model-controlled data.

- **S3.1 Round trip** Given a sample of every event type, when serialized and parsed again, then the result equals the original.
- **S3.2 Sequence** Given a turn that produces several events, then `seq` values are consecutive and ordered as produced.
- **S3.3 Trace outside shown events (negative)** Given a turn with tool calls, then the verifier's shown-event input contains no `ToolCalled` or `VerdictIssued`.
- **S3.4 Trace content** Given a turn that calls `check_prices`, then one `ToolCalled` event names it, summarizes its arguments and reports ok or an error code.

## W4. Commands and components

The page MUST send only `SendMessage{text}`, `PressDale{proposal_id}` and `CancelProposal{proposal_id}`. Every command body MUST be validated against its schema. Server-built UI blocks MUST be typed components: `OrderSummary`, `OrderConfirmation`, `Notice`, `ToolTrace`, `Verdict`, `HandoffNotice`.

- **S4.1 Valid command** Given a well-formed command, then it is accepted and handled.
- **S4.2 Unknown field or type (negative)** Given a body with a missing required field, a wrong type, or an unknown command, then it is rejected with the error envelope and nothing executes.
- **S4.3 Component per event** Given each event type, then it maps to a typed component or to the proposal state, with no untyped payload.

## W5. Contract versioning and drift

Contract v1 MUST be additive-only: fields MAY be added, none MAY be removed or change meaning. The host MUST report the contract version at `GET /v1/contract` and on every envelope. JSON Schema files and the TypeScript types generated from them MUST be committed, and CI MUST fail when regeneration produces a difference.

- **S5.1 Version reported** Given a running host, then `GET /v1/contract` and every envelope report the same version `1`.
- **S5.2 Golden schemas** Given the Python types, when schemas are regenerated, then the result is identical to the committed files.
- **S5.3 TS types match** Given the committed schemas, when TS types are regenerated, then the result is identical to the committed types, and a type test over the sample JSON of S3.1 compiles.
- **S5.4 Breaking change detected (negative)** Given a removed or renamed field in a Python type, when regeneration runs, then CI fails on the diff.

## W6. Confirmation only by the Dale button

An order MUST be confirmed on the web only when the host receives a `PressDale` command for a stored proposal ID on the confirm route. Typed text, including "dale", MUST NOT confirm. The model MUST NOT be able to press. `SendMessage` MUST NOT parse its text for confirmation.

- **S6.1 Button confirms** Given a stored proposal, when `PressDale` arrives with its ID, then management `confirm(proposal_id)` is called.
- **S6.2 Typed "dale" (negative)** Given a pending proposal, when `SendMessage` carries "dale" or "dale, confirmalo", then no confirm call is made and no order is created.
- **S6.3 Model cannot press (negative)** Given tool output or assistant text that asks for a confirmation, then no route or code path invokes confirm.
- **S6.4 No proposal (negative)** Given no pending proposal, when the Dale button is pressed, then nothing is confirmed and the error envelope is returned.

## W7. Press safety: idempotency, staleness, ownership

The press MUST be bound to the proposal ID the page holds, and the host MUST build the confirmed terms from the stored proposal, never from client-sent values. The same ID pressed any number of times, including concurrently, MUST yield exactly one order and identical response bodies. A proposal that is no longer pending MUST be rejected. A proposal ID from another conversation or customer MUST be rejected.

- **S7.1 Double press (negative)** Given a pending proposal, when two `PressDale` requests with its ID are sent concurrently, then exactly one order exists and both responses carry the same body.
- **S7.2 Stale proposal (negative)** Given a proposal that was superseded by a newer one, when its ID is pressed, then it is rejected with the `proposal_not_pending` catalog code and no order is created.
- **S7.3 Foreign proposal (negative)** Given a proposal ID that belongs to another conversation or customer, when it is pressed, then it is rejected with the `proposal_not_found` catalog code and no order is created.
- **S7.4 Client totals ignored** Given a `PressDale` body with extra price or total fields, then they are rejected or ignored and the order uses the stored proposal.
- **S7.5 Retryable outcome** Given an unknown management outcome (`rules_unavailable`), then the response carries its catalog status and message, the proposal stays pending, and a later press is accepted.
- **S7.6 Cancelled proposal (negative)** Given a proposal the customer cancelled on the page (it may still be `prepared` in the database), when its ID is pressed, then it is rejected with the `proposal_not_pending` catalog code, the brain is not called and no order is created.

## W8. Host and Origin allow-list

The host MUST reject any request whose `Host` is not in the allow-list, and any state-changing request whose `Origin` is present and not in the allow-list, before handling its body. The allow-list MUST default to loopback names on the host's port and MUST be configurable without code changes to routes.

- **S8.1 Cross-origin POST (negative)** Given a POST to `/confirm` with `Origin: https://evil.example`, then it is rejected with the error envelope and no order is created.
- **S8.2 Rebinding Host (negative)** Given a request with `Host: evil.example`, then it is rejected before any handler runs.
- **S8.3 Allowed origin** Given `Origin` and `Host` equal to the default loopback values, then the request is handled.
- **S8.4 Configured allow-list** Given an additional name added to the configuration, then requests with it are accepted and others are still rejected.

## W9. JSON-only requests with a size cap

State-changing routes MUST accept only `application/json` bodies and MUST reject a body larger than the configured cap before parsing it.

- **S9.1 Wrong content type (negative)** Given a POST with `Content-Type: text/plain` or a form type, then it is rejected and nothing executes.
- **S9.2 Oversized body (negative)** Given a body above the cap, then it is rejected with the error envelope and its content is not parsed.
- **S9.3 Valid body** Given a JSON body under the cap, then it is handled.

## W10. CSP and text-only rendering

Every response that serves the page MUST send a Content-Security-Policy that denies inline script and third-party origins. The page MUST render assistant text, tool names, argument summaries and order fields as text and MUST NOT interpret them as HTML.

- **S10.1 CSP header** Given a request for the page, then the response carries a CSP with no `unsafe-inline` script and no external origin.
- **S10.2 Markup as text (negative)** Given assistant text or a tool argument containing `<img src=x onerror=alert(1)>`, when rendered, then it appears as literal characters and no element or script is created.
- **S10.3 No raw HTML sink** Given the page source, then no code path inserts model-controlled text as HTML (lint rule or test).

## W11. One error envelope

Every error response MUST use one envelope shape carrying a stable catalog code and a customer-facing message. A brain outcome code MUST take its HTTP status from the existing `ErrorCode` to status map. A transport code (host, origin, media type, size, validation, busy, unknown conversation, internal error) MUST come from a separate web catalog, disjoint from `ErrorCode`, with one fixed status per code, and MUST never appear in a shown event. Responses MUST NOT expose stack traces, exception text, or another conversation's data.

- **S11.1 Every code mapped** Given the `ErrorCode` catalog and the web catalog, then every code of both has an HTTP status and a message, and no code appears in both.
- **S11.2 Same shape** Given a validation error, a rule rejection, an origin rejection and an unexpected failure, then all use the same envelope fields.
- **S11.3 No internals (negative)** Given an unexpected exception in a handler, then the response is a generic error code and message, and the exception text appears only in the server log.

## W12. Per-conversation lock

While a turn or press is running for a conversation, a second request that would start one for the same conversation MUST be rejected with HTTP 409 and a stable code. The one exception is a press of the same proposal ID as the running press: it MUST wait for that press (bounded) and then receive the settled response, as W7 requires. The lock MUST be released when the running request ends, including on failure. Different conversations MUST NOT block each other.

- **S12.1 Overlap rejected** Given a turn in progress, when another `SendMessage` arrives for the same conversation, then it returns 409 with the stable code and the first turn completes normally.
- **S12.2 Release on failure** Given a turn that fails, then the next request for that conversation is accepted.
- **S12.3 Independent conversations** Given two conversations, then a running turn in one does not reject a request in the other.

## W13. Verifier after every press

After every press (including a failed one) and after a turn that showed `OrderConfirmed`, the host MUST run the verifier and MUST return the verdict in the same response as the outcome, as a `VerdictIssued` event. A verifier failure or timeout MUST be returned as an `unverifiable` verdict, never as success. The request timeout MUST exceed the verifier timeout.

- **S13.1 Verdict with outcome** Given a successful press, then the response contains the confirmation event and a `VerdictIssued` event for that order.
- **S13.2 Failed press** Given a rejected press, then the response still contains a `VerdictIssued` event.
- **S13.3 Verifier failure (negative)** Given the verifier times out or crashes, then the verdict is `unverifiable` and the page does not show the order as verified.

## W14. Fixed seeded customer

Each conversation MUST be bound to one fixed seeded customer of Distribuidora El Hornero chosen by the host. The command and resource surface MUST NOT accept a customer or company identifier from the page.

- **S14.1 Fixed customer** Given a new conversation, then every proposal and order in it belongs to that customer.
- **S14.2 Client customer ignored (negative)** Given a command body that includes a customer or company ID, then it is rejected or ignored and the bound customer is used.

## W15. Panels: tool trace, stored order, verdict

Beside the chat the page MUST show three panels: the tools the agent used, the order stored in the database, and the verifier's verdict. The order panel MUST be built from the stored order carried by the verdict (`verified-order` R11), not from the confirmation message. The verdict panel MUST show the verifier's result for every press. The Dale button MUST be enabled only while a pending proposal exists and no request is running.

- **S15.1 Trace panel** Given a turn with tool calls, then the panel lists each tool with its summary and ok or error.
- **S15.2 Order from the database** Given a verified press, then the order panel shows the lines and total from the verdict's stored order.
- **S15.3 Mismatch visible** Given a verdict that is not verified, then the verdict panel shows it as not verified and the order panel shows the stored order as read, not the order shown in chat.
- **S15.4 Button state** Given no pending proposal, or a request in flight, then the Dale button is disabled; after a click it is disabled until the response arrives.
- **S15.5 Stale page** Given the host rejects a press as not pending, then the page shows the notice and the current summary.

## W16. Spanish interface labels

Page labels, panel titles, buttons and states MUST be in Spanish, as is the chat. Contract field names, event types and codes stay in English.

- **S16.1 Labels** Given the page, then the panel titles, the Dale button and the pending and error states render Spanish text.
- **S16.2 Contract unchanged** Given a Spanish page, then the contract schemas contain no Spanish identifiers.

## W17. Extension points for v0.3

The conversation registry MUST sit behind a port with an in-memory implementation. The Host/Origin allow-list MUST be configuration. Conversation state is lost on restart in v0.2. No v0.3 feature MAY be required to run v0.2.

- **S17.1 Registry swap** Given a test registry implementing the port, then the host runs with it and no route changes.
- **S17.2 Restart** Given a host restart, then old conversation IDs are rejected with the error envelope and a new conversation works.

## W18. Frontend build gate

CI MUST run a required job that type-checks, lints, tests and builds the page with a pinned Node version and exact dependency versions installed from the lockfile. The terminal channel MUST keep working unchanged.

- **S18.1 Web job** Given a PR, then the `web` job runs typecheck, lint, Vitest and build, and fails the PR when any fails.
- **S18.2 Workflow test** Given the CI workflow file, then a unit test asserts the `web` job and its steps exist.
- **S18.3 Terminal unchanged** Given the existing terminal tests, then they pass without modification of their expectations.

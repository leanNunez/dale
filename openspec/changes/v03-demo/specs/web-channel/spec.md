# Delta for web-channel (v0.3 "Probalo vos")

Base: `openspec/specs/web-channel/spec.md` (W1-W18). Modified blocks are complete replacements. Behavior only; structure and mechanics are decided in design. Keywords follow RFC 2119. All data is fictitious ("Distribuidora El Hornero"); IP addresses come from documentation ranges.

Terms added: **demo mode** = the host running with the demo settings of `demo-operations` O1. **Local mode** = the host running without them (v0.2 behavior). **Visitor customer** = a customer created by the host for one conversation. **Session** = the visitor identity carried by the session cookie (`demo-operations` O2).

Header note: the base spec's line "Out of scope here (v0.3): deploy, per-visitor limits, spend cap, kill switch, auto-reset database, saved conversations, cookie session, customer picker, WebSocket" is superseded. At archive it becomes: "Demo controls are specified in `demo-operations`; release and deploy in `release-gate`. Out of scope: customer picker, WebSocket, SSE."

## MODIFIED Requirements

### W5. Contract versioning and drift

Contract v1 MUST be additive-only: fields, event types and codes MAY be added, none MAY be removed or change meaning. Every v0.3 code (W11) and every v0.3 field MUST be an addition to v1, and the version MUST stay `1`. The host MUST report the contract version at `GET /v1/contract` and on every envelope. JSON Schema files and the TypeScript types generated from them MUST be committed, and CI MUST fail when regeneration produces a difference.
(Previously: the same rule, with no v0.3 additions named.)

- **S5.1 Version reported** Given a running host, then `GET /v1/contract` and every envelope report the same version `1`.
- **S5.2 Golden schemas** Given the Python types, when schemas are regenerated, then the result is identical to the committed files.
- **S5.3 TS types match** Given the committed schemas, when TS types are regenerated, then the result is identical to the committed types, and a type test over the sample JSON of S3.1 compiles.
- **S5.4 Breaking change detected (negative)** Given a removed or renamed field in a Python type, when regeneration runs, then CI fails on the diff.
- **S5.5 v0.3 is additive** Given the v0.2 committed schemas, when compared with the v0.3 schemas, then every v0.2 field, event type and code still exists with the same meaning, and the version is `1`.

### W8. Host and Origin allow-list, client IP and session cookie

The host MUST reject any request whose `Host` is not in the allow-list, and any state-changing request whose `Origin` is present and not in the allow-list, before handling its body. The allow-list MUST default to loopback names on the host's port and MUST be configurable without code changes to routes. Forwarded headers MUST NOT change the `Host` or `Origin` decision.

In demo mode:
- The client IP MUST be taken from the forwarded header only when the immediate peer is a loopback address, and then only from the value the trusted proxy appended, never from a value the client supplied. When the peer is not loopback, forwarded headers MUST be ignored. A request with no usable client IP MUST be rejected with the error envelope before any handler runs.
- The client IP MUST be used only for limits (`demo-operations` O3) and MUST NOT be stored in clear.
- The session cookie MUST be `HttpOnly`, `Secure`, `SameSite=Strict` and `Path=/`.
- CSRF MUST stay closed by `SameSite=Strict` together with the `Host`, `Origin` and JSON-only (W9) checks. No `GET` route MAY change state.

In local mode, forwarded headers MUST be ignored and no cookie MUST be set, as in v0.2. This amends ADR 0005's "no cookies" premise; a decision record states it.
(Previously: Host/Origin allow-list only; no cookies; forwarded headers never read.)

- **S8.1 Cross-origin POST (negative)** Given a POST to `/confirm` with `Origin: https://evil.example`, then it is rejected with the error envelope and no order is created.
- **S8.2 Rebinding Host (negative)** Given a request with `Host: evil.example`, then it is rejected before any handler runs.
- **S8.3 Allowed origin** Given `Origin` and `Host` equal to the default loopback values, then the request is handled.
- **S8.4 Configured allow-list** Given an additional name added to the configuration, then requests with it are accepted and others are still rejected.
- **S8.5 Proxy-appended IP** Given demo mode, a loopback peer, and a forwarded header where the client sent `198.51.100.9` and the proxy appended `203.0.113.7`, when the request is handled, then the client IP used for limits is `203.0.113.7`.
- **S8.6 Untrusted peer (negative)** Given demo mode and a non-loopback peer that sends a forwarded header, then the header is ignored and the peer address is the client IP.
- **S8.7 No client IP (negative)** Given demo mode and a loopback peer with no forwarded header, then the request is rejected before any handler runs and nothing executes.
- **S8.8 Cookie attributes** Given demo mode, when the host issues a session cookie, then it carries `HttpOnly`, `Secure`, `SameSite=Strict` and `Path=/`.
- **S8.9 Forwarded host ignored (negative)** Given `Host: evil.example` and a forwarded host header naming an allowed name, then the request is rejected under S8.2.
- **S8.10 Local mode** Given local mode, then no response sets a cookie and a forwarded header does not change any decision.

### W11. One error envelope

Every error response MUST use one envelope shape carrying a stable catalog code and a customer-facing message. A brain outcome code MUST take its HTTP status from the existing `ErrorCode` to status map; v0.3 adds `turn_deadline_exceeded` to `ErrorCode` (`verified-order` R9). A transport code MUST come from a separate web catalog, disjoint from `ErrorCode`, with one fixed status per code, and MUST never appear in a shown event. The web catalog covers host, origin, media type, size, validation, busy, unknown conversation and internal error, and v0.3 adds:

| Code | Meaning |
|---|---|
| `rate_limited` | A per-session, per-conversation or per-IP limit is reached (`demo-operations` O3) |
| `demo_paused` | The demo is paused by the kill switch or the spend cap (`demo-operations` O4, O5) |
| `demo_busy` | A global cap is reached (W17, `demo-operations` O3) |
| `demo_reset` | The conversation was cleared by the nightly reset (`demo-operations` O11) |
| `notice_not_accepted` | A conversation was requested without accepting the current notice (`demo-operations` O7) |

Responses MUST NOT expose stack traces, exception text, another conversation's data, or another visitor's usage or limits.
(Previously: the same envelope without the v0.3 codes.)

- **S11.1 Every code mapped** Given the `ErrorCode` catalog and the web catalog, then every code of both has an HTTP status and a message, and no code appears in both.
- **S11.2 Same shape** Given a validation error, a rule rejection, an origin rejection and an unexpected failure, then all use the same envelope fields.
- **S11.3 No internals (negative)** Given an unexpected exception in a handler, then the response is a generic error code and message, and the exception text appears only in the server log.
- **S11.4 v0.3 codes** Given each code in the table, then it has one fixed HTTP status and a Spanish message, and it never appears in a shown event.
- **S11.5 No foreign usage (negative)** Given a `rate_limited` response, then it carries no count, session or IP of any other visitor.

### W14. Bound customer per conversation

In demo mode each conversation MUST be bound to a new visitor customer of Distribuidora El Hornero, created by the host for that conversation only, with a server-generated ID and the zone and business rules of a configured template customer (default: a seeded customer in zone Centro). A visitor customer MUST NOT be bound to more than one conversation. If the visitor customer cannot be created, the conversation MUST NOT be created and MUST NOT fall back to a shared or fixed customer. In local mode each conversation MUST be bound to the one fixed seeded customer chosen by the host, as in v0.2. In both modes the command and resource surface MUST NOT accept a customer or company identifier from the page. The verifier's run scope (`verified-order` R11) is unchanged.
(Previously: every conversation was bound to one fixed seeded customer; decision B65 kept one live conversation per host. D4 supersedes B65 in demo mode.)

- **S14.1 Bound customer** Given a new conversation in either mode, then every proposal and order in it belongs to its bound customer.
- **S14.2 Client customer ignored (negative)** Given a command body that includes a customer or company ID, then it is rejected or ignored and the bound customer is used.
- **S14.3 Own customer** Given demo mode, when two conversations are created, then each is bound to a different visitor customer with no orders, in the template's zone and with its rules.
- **S14.4 Concurrent visitors verified** Given demo mode and two live conversations, when each visitor presses Dale on a valid proposal at the same time, then both verdicts are `verified`, neither is `unexpected_write`, and neither conversation is ended.
- **S14.5 Creation fails (negative)** Given demo mode and a failure creating the visitor customer, when a conversation is requested, then the error envelope is returned, no conversation exists, and no other customer is bound.
- **S14.6 Template missing (negative)** Given demo mode and no template customer in the database, then the host refuses to start.

### W17. Registry, caps and local mode

The conversation registry MUST sit behind a port with an in-memory implementation. The Host/Origin allow-list MUST be configuration. Conversation state is lost on restart.

In demo mode the registry MUST hold many live conversations, up to a cap (setting, default 10). A request to create a conversation above the cap MUST be rejected with `demo_busy` and MUST NOT end any live conversation. A conversation with no request for the idle TTL (setting, default 30 minutes) MUST be ended, freeing its slot, and its ID MUST then be rejected with `conversation_not_found`. A conversation with a request in flight MUST NOT be ended by the TTL before that request ends.

In local mode the host MUST run with v0.2 behavior: one fixed customer, one live conversation (a new one retires the earlier one), no session, no limits, no spend accounting and no control row.
(Previously: one live conversation per host, and "no v0.3 feature MAY be required to run v0.2".)

- **S17.1 Registry swap** Given a test registry implementing the port, then the host runs with it and no route changes.
- **S17.2 Restart** Given a host restart, then old conversation IDs are rejected with the error envelope and a new conversation works.
- **S17.3 Cap** Given demo mode and 10 live conversations, when an 11th is requested, then it gets `demo_busy` and the 10 stay live.
- **S17.4 Idle TTL** Given demo mode and a fake clock, when a conversation has had no request for 30 minutes, then its ID gets `conversation_not_found` and a new conversation can take its slot; at 29 minutes it is still live.
- **S17.5 In flight not expired** Given a turn running when the TTL elapses, then the turn completes and its response is returned.
- **S17.6 Local mode unchanged** Given local mode, then the v0.2 web tests pass without changed expectations, and creating a second conversation retires the first.

## ADDED Requirements

### W19. Demo page states

In demo mode the page MUST show a distinct Spanish state for each of `demo_paused`, `demo_busy`, `rate_limited`, `demo_reset`, `notice_not_accepted` and `turn_deadline_exceeded`. State text MUST be static page text, not server-supplied markup. After `demo_reset` the page MUST NOT offer the old proposal for confirmation and MUST offer a new conversation. The tool-trace panel (W15) MUST stay visible in demo mode (D13).

- **S19.1 State per code** Given a response with each listed code, then the page shows its own Spanish state, rendered as text.
- **S19.2 Reset clears** Given a pending proposal, when a request returns `demo_reset`, then the Dale button is disabled and the page offers a new conversation.
- **S19.3 Trace shown** Given demo mode and a turn with tool calls, then the tool-trace panel lists them.

## REMOVED Requirements

None.

## Unchanged requirements

W1, W2, W3, W4, W6, W7, W9, W10, W12, W13, W15, W16 and W18 stay exactly as in the base spec. In particular the app still binds only to `127.0.0.1` (W1), the resource surface gains no route (W2; the privacy page is static page content, not an API resource), and only the Dale button confirms (W6).

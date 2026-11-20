# 0005. Web confirmation safety

Date: 2026-11-19
Status: accepted (host guard, envelope and loopback binding in place; the press route lands with the conversation slices)

## Context

Record 0002 made the terminal's `F2` key the only way to confirm an order: code handles the key,
and typed text never confirms. The web channel moves that action to a button on a page, which
adds browser threats the terminal never had: another site can post to a local port, a hostile
DNS name can point at `127.0.0.1` (rebinding), a form can submit without a CORS preflight, a
double click or a retry can send the press twice, and model text is rendered in a document that
can run scripts. This record extends 0002 to the web. Design decisions D14 and D15 are
summarized here.

## Decision

| Topic | Decision |
|---|---|
| Dale action | On the web the Dale action is a `PressDale{proposal_id}` command on the confirm route, sent only by the Dale button. `SendMessage` builds only customer text, so a typed "dale" reaches only the model, as on the terminal. The model has no confirm tool and no route reads model output as a command. The confirmed terms come from the stored proposal; a client total, customer id or company id fails the command's validation. The confirm route itself is planned (slice 5) |
| Press gate (D15) | The host confirms only the proposal it holds as pending, or one already shown confirmed. A proposal shown but no longer pending answers `proposal_not_pending`; any other id, another conversation's included, answers `proposal_not_found`; neither reaches the brain. A proposal cancelled on the page stays `prepared` in the database, so `ConfirmProposal` alone would confirm it: the gate is what refuses it (planned, slice 5) |
| Press replay (D15) | Presses of one proposal are serialized. A settled outcome (`OrderConfirmed` or `OrderRejected`) is stored and returned byte for byte to any later press of the same id, so concurrent presses yield one order and identical bodies. `rules_unavailable` and an unknown outcome are not stored, and the proposal stays pending, so a retry runs again (planned, slice 5) |
| Loopback only | The host binds the constant `127.0.0.1` with one worker; no flag or variable changes it. The page is served from the same origin as the API and there is no CORS middleware, so no response names an allowed origin |
| Host and Origin | A pure ASGI guard wraps the application and checks before routing and before any body is read. `Host` must be exactly one allow-listed value, else `invalid_host`; this defeats DNS rebinding, because the browser sends the attacker's name. On any method but GET and HEAD, exactly one `Origin` must be present and allow-listed, else `forbidden_origin`; a missing one is rejected too (fail closed), because browsers send `Origin` on every POST, same-origin included, so only a non-browser client or a stripped header arrives without it. The allow-list is the loopback names on the port plus the names in `DALE_WEB_ALLOWED_HOSTS` and `DALE_WEB_ALLOWED_ORIGINS` |
| JSON only, 16 KiB | On those methods the media type must be `application/json` (charset UTF-8 if named), else `unsupported_media_type`: a cross-site form or `text/plain` post fails. The body is capped at 16 KiB by `Content-Length` and by counting the stream, else `payload_too_large`; the guard reads the capped body before the application runs, so an oversized body is never parsed |
| CSP and headers | Every response the guard or the application sends, a rejection included, carries `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'`, `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`; API paths add `Cache-Control: no-store`. A request that is not valid HTTP never reaches the application: uvicorn (h11) answers it itself with a plain-text 400 without these headers. No inline script and no other origin can run. The page renders model text as text (planned, slice 7) |
| One envelope (D14) | Conversation routes answer with one `ResponseEnvelope`, and every error, on any path, is one `ResponseEnvelope`. The metadata routes answer with their documented bodies: `GET /v1/contract` with `{v, events, commands}` and `GET /health` with an empty envelope. There is no trailing-slash redirect, so `/health/` is an unknown path and no `Location` echoes the `Host`. A brain outcome keeps its `ErrorCode` and status; a transport failure uses its `WebErrorCode`. The handlers replace FastAPI's default bodies, whose validation error echoes the input; an unexpected exception answers `internal_error`, and its text goes only to the log |

## Alternatives rejected

- Trusting `ConfirmProposal` alone: a stale or cancelled proposal is still `prepared`, so it
  would be confirmed.
- Rejecting a concurrent press with 409: the second click would not see the order the first
  one created.
- CORS with an allow-list: same-origin serving needs none, and every CORS header is one more
  thing to get wrong.
- A CSRF token: on a loopback host with no cookies, the Origin check, the JSON-only rule and
  the Host check close the same paths with less state.

## Consequences

- The Vite dev server proxies to the host from another port, so during development its names
  must be added to the allow-list or the proxy must rewrite `Host` and `Origin` (slice 6).
- A turn or press may run for minutes and no request timeout cuts it (0004); the press lock
  waits at most 60 s for a running press of the same id.
- v0.3 (public demo) adds a deployed host behind its own name; the allow-list is configuration,
  but per-visitor limits, a spend cap and a turn deadline are required first.

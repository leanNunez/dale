# 0010. Cookie session, CSRF without a token, and the client IP

Date: 2026-11-26
Status: accepted (decided before the code: the IP and the session land in slices 8b and 8c)

## Context

[Decision 0005](0005-web-confirmation-safety.md) assumes a host with no cookies: it rejects a CSRF
token because "on a loopback host with no cookies" the Origin check, the JSON-only rule and the
Host check close the same paths (its "Alternatives rejected"). The public demo breaks that
premise. The host needs to tell visitors apart so each conversation belongs to one of them and
limits count per visitor ([decision 0009](0009-public-demo.md)), and that needs a cookie. The host
also sits behind a reverse proxy on the same machine, so the peer address is always the proxy and
the visitor's address arrives in a header that a client could forge. This record states DD34 to
DD36 of the `v03-demo` design and log D18 (web-channel W8, demo-operations O2 and O3).

## Decision

| Topic | Decision |
|---|---|
| Session cookie (DD34, log D18) | `__Host-dale_session`, with `HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=86400` (24 hours). The `__Host-` prefix makes a browser refuse it without `Secure`, with a `Domain` or with another path. Its value is 32 random bytes in base64url. Only `POST /v1/conversations` (read-only), when the request has no valid session, sets a new one (log D24); a page, static or other GET never does, and any other request with no valid session answers `conversation_not_found`. A conversation is bound to the session that created it, and another session's id answers `conversation_not_found` |
| What is stored | Only a keyed hash: HMAC-SHA256 of `"session\|" + token` under a secret setting (planned). The token itself is never stored or logged, and there is no session table. Acceptance of the notice travels in the create command and is stored with the transcript, so nothing else needs a session row |
| CSRF (DD35) | No token. Every cross-site path is closed by at least two independent checks. (1) `SameSite=Strict` keeps the browser from sending the cookie on a cross-site request. (2) The guard already requires exactly one allow-listed `Origin` on every method but GET and HEAD, and rejects a missing one (`src/dale/channels/web/guard.py:104-108`). (3) Those methods must carry `application/json` (`guard.py:109-110`), so a form or `text/plain` post fails, and a cross-site JSON post would need a CORS preflight that the host never answers, because it sends no CORS headers. (4) No GET route changes state. The `Host` check against rebinding is unchanged, and forwarded headers never change the `Host` or `Origin` decision |
| Client IP (DD36) | A pure function in the channel (planned), used only in demo mode. When the immediate peer is `127.0.0.1` or `::1`, the IP is the **last** element of the last `X-Forwarded-For` field, the one the proxy appended, validated with `ipaddress`; an earlier element is client-supplied and never used. For any other peer, the peer address is the IP and the header is ignored. A loopback peer with no usable value is rejected with `invalid_request` before any handler runs. uvicorn keeps `proxy_headers=False` (`src/dale/apps/web.py:219`), so `scope["client"]` is never rewritten and the server-config pin is unchanged |
| IP use | Only for limits (0009). The per-IP counter key is a keyed hash whose key changes every day, so the IP is never written to the database, a log or a transcript in clear |
| Local mode | Unchanged from v0.2: no cookie is ever set, the forwarded header is never read, and no decision depends on either |

## What this amends

- **0005, the no-cookie premise.** A CSRF token is still rejected, but for a different reason: the
  host now has a cookie, and `SameSite=Strict` plus the required `Origin` and the JSON-only rule
  still close every path with less state than a token. The other rows of 0005 stand: the loopback
  bind (the host still binds `127.0.0.1` only, `web.py:54`), the Host and Origin allow-list, the
  16 KiB JSON body, the CSP and the one envelope. The allow-list gains the public name through
  configuration only (`DALE_WEB_ALLOWED_HOSTS` and `DALE_WEB_ALLOWED_ORIGINS`).
- **0005's "no response names an allowed origin".** Still true: the host sends no CORS headers.

## Why only the create request sets the cookie

`SameSite=Strict` keeps the browser from sending the cookie on a cross-site top-level navigation,
such as a click on the CV link. If any page `GET` issued a cookie whenever the request carried
none, that arrival would look like a visitor with no session, and the response would overwrite the
cookie of a visitor who already has one, ending their live conversation's ownership. Issuing the
cookie only in `POST /v1/conversations` (read-only) avoids that: a cross-site arrival loads the
page and sets nothing, and the first same-site request after it carries the existing cookie again.
The page can show its notice and accept step with no session, since acceptance travels in the
create command.

## What `SameSite` does not cover

`SameSite` compares sites, meaning the registrable domain, not origins. A page on a sibling
subdomain of the demo's domain is same-site, so the browser sends the cookie on its requests to the
demo and `SameSite=Strict` gives nothing against it. Two other defenses remain, and they do not
depend on the cookie: the Origin check, which requires exactly one allow-listed `Origin` on every
method but GET and HEAD and rejects a sibling's origin (`guard.py:104-108`), and the CORS
preflight, which a cross-origin JSON post needs and which the host answers with 403
`forbidden_origin` and no CORS headers. Two independent checks meet the bar of at least two that
this record sets. The `__Host-` prefix also stops a sibling from planting a cookie of that name for
the parent domain, because the browser refuses the prefix with a `Domain` attribute. The domain is
still open (log D14): a dedicated domain with no other subdomains makes the question moot, and a
domain shared with other applications relies on these two checks alone.

## Alternatives rejected

- A CSRF token in a header or a hidden field. It adds a second piece of session state and a
  place to forget a check, and the existing checks already close the same paths.
- `SameSite=Lax`. It sends the cookie on top-level cross-site navigations, which Strict does not;
  no part of the demo needs a link from another site to arrive already signed in.
- A signed stateless token or a session table. The first adds nothing, since clearing the cookie
  gets a new session anyway. The second stores more than the limits need.
- uvicorn's `ProxyHeadersMiddleware`. Its algorithm depends on the version, and it rewrites the
  client address for every route, including local mode.
- Trusting the first `X-Forwarded-For` element, or any value from a non-loopback peer. A client
  chooses those, and one forged address would reset its own limits.

## Consequences

- The session is a convenience for limits and ownership, not an identity: a visitor who clears the
  cookie gets a new session. Per-IP limits are the real bound (0009, log D17).
- Several visitors behind one address (an office, a shared network) share the per-IP limits.
- The `__Host-` cookie needs `Secure`, so demo mode is meant to run behind HTTPS ([decision 0012](0012-hosting-release-deploy.md)). Local mode sets no cookie.
- The correctness of the client IP depends on the proxy appending the address it saw. The tests
  fix the behavior for the header values in the spec (S8.5 to S8.7, S8.9, S8.10), and the smoke
  check of [decision 0012](0012-hosting-release-deploy.md) sends a create request through the real proxy, which answers
  `notice_not_accepted` only when a client IP was found.
- Page and API stay on one origin, so nothing here needs CORS, and W10's CSP is unchanged.

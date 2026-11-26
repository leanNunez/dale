# 0006. Contract v1, schema generation and the frontend stack

Date: 2026-11-19
Status: accepted (contract and generation, frontend stack and Node pins; the page itself lands in slices 7a and 7b)

## Context

The host and the page exchange JSON. A hand-written copy of those shapes on each side drifts, and
the page renders model-controlled text, so an untyped payload is a risk. This record fixes where
the contract lives, how it is generated and how drift is caught, then (below) the frontend stack
and the Node supply chain (design D21 and D22). Design decision D20 is summarized here.

## Decision

| Topic | Decision |
|---|---|
| Source of truth (D20) | The Python types in `dale.channels.web.contract`: pydantic models for the commands, the envelope and the web-only events, and the shared dataclasses for the shown events. `dale.shared` stays free of pydantic (import contract 6). The `data` of a shown event is exactly the verifier's JSON form, so one form serves both readers |
| Wire types | Eight event types (`AssistantText`, `ProposalSummary`, `OrderConfirmed`, `OrderRejected`, `HandoffNotice`, `SystemNotice`, `ToolCalled`, `VerdictIssued`), three commands (`SendMessage`, `PressDale`, `CancelProposal`) and `ResponseEnvelope`. `ToolCalled` and `VerdictIssued` are not shown events and never reach the verifier's input |
| Strict types | Commands use `extra="forbid"`: a client total, a customer id or a company id fails validation. Text is a real string of 1 to 2000 characters, not blank, with no control character but newline and tab; ids are hyphenated 36-character UUIDs. Everything the host emits is strict (no coercion, aware datetimes) and consistent: a verdict obeys the runner's rules, an error carries its catalog message, an envelope's events share its conversation and end at its `seq` |
| Errors (D14) | A brain outcome keeps its `ErrorCode` and its status; transport failures use `WebErrorCode`, a disjoint catalog with one fixed status and one fixed Spanish message per code. Messages carry no exception text |
| Components | `COMPONENTS` maps each event type to one typed UI component (`ChatText`, `OrderSummary`, `OrderConfirmation`, `Notice`, `HandoffNotice`, `ToolTrace`, `Verdict`) and is written to `components.json`. The page switches over it exhaustively |
| Generation | `python -m dale.channels.web.schema_gen` writes `contracts/v1/<Type>.schema.json` and `components.json`: sorted keys, 2-space indent, trailing newline, `additionalProperties: false` on every object that does not already describe its extra keys. Output types use serialization mode with defaulted fields (`v`, `type`) required; commands use validation mode, so a defaulted field is optional to send. The output is committed |
| Drift checks | A golden test in the `test` job fails when regeneration differs from the committed files, including a missing or extra file; renaming or removing a field changes the output. The `web` job regenerates the TypeScript types (`npm run gen:contract`) and fails on any `git diff`, a new generated file included; a Vitest test does the same comparison locally |
| Versioning (W5) | v1 is additive-only: optional fields and event types may be added, none removed or changed in meaning. Responses and events carry `v: 1`; commands carry no `v` and are versioned by the `/v1` path. `GET /v1/contract` reports `v: 1`. The published schemas are closed, so an addition changes them; the page uses the TypeScript types at compile time, does not reject a response at runtime against the schema, and ignores an unknown event type |
| English identifiers | Property names, definition names and enum values are English (a test scans them); Spanish appears only in message text |
| Samples | `contracts/v1/samples/` holds one authored JSON per event type plus commands and an envelope. Tests round-trip them; the page's type test (planned, slice 7b) compiles over them |
| Size guard | Generated `contracts/**/*.schema.json` and `contracts/v1/components.json`, and on the page side `apps/web/package-lock.json` and `apps/web/src/contract/generated/`, are excluded from the PR size count; the samples, `package.json`, this record and the source types still count. Excluded files are reviewed for what they pin, not for their length |

## Alternatives rejected

- `openapi-typescript` from FastAPI's OpenAPI would tie the types to the routes, and OpenAPI is
  disabled so the route table stays exact.
- Hand-written TypeScript types drift from the Python ones without any check failing.
- Importing pydantic into `dale.shared` to describe the shown events would break the shared
  kernel's import rule; the web channel describes them instead.

## Consequences

- Changing a wire type means regenerating and committing the schemas in the same change.
- `Money` crosses the wire as integer cents; a value above 2^53 is not safe in JavaScript. JS-safe
  bounds are Known pending for v0.2.
- The trace `name` and `summary` are model text, so the page renders them as text only.

## Frontend stack and Node pins (D21, D22)

| Topic | Decision |
|---|---|
| Stack | React 19, TypeScript strict (`noUncheckedIndexedAccess`), Vite, Tailwind 4 through its Vite plugin and one CSS file (`@import "tailwindcss"`), Vitest with Testing Library and jsdom, ESLint with typescript-eslint, `eslint-plugin-react` and `eslint-plugin-react-hooks`, `json-schema-to-typescript` for the contract. No router, no data-fetching library, no global store: one conversation on one screen is a `useReducer` in one hook (D21) |
| State | `src/state/reducer.ts` is pure and tested without the DOM. It applies each event once (drops `seq` at or below `lastSeq`), moves `lastSeq` only with events, applies `pending_proposal_id` only from an envelope whose `seq` is not behind the page, and ignores event types it does not know. Each event's shape is checked there: anything that is not an object with an integer `seq`, a string `type` and an object `data`, or a `ProposalSummary` without a string id and date, integer `total.cents` and a list of lines, is dropped, never thrown on and never stored. An envelope for another conversation is applied only as the answer to a create, which replaces the page's conversation; any other request's answer for another conversation is dropped and only ends that request. The hook starts a call only when the reducer accepted its start, judged on the latest state, so a handler from an older render cannot send a press the state already refuses. The Dale button is enabled only for a rendered `ProposalSummary` whose id equals the pending id (`canPressDale`) |
| Client | `src/api/client.ts` is the only module that calls the host: same-origin relative URLs, JSON, no timeout and no abort signal (D17, B6), any status parsed into a `ResponseEnvelope`. A body that was read but is not an envelope is a `malformed_response` `ClientError` that keeps no response text, so a proxy's HTML page never reaches the document; a connection that fails before or while the body is read is `network` |
| Page security | The built page is served by the host under the CSP of 0005: one external script and one external stylesheet, no inline script. ESLint (`lint/html-sinks.js`) bans `react/no-danger` and the names of the raw HTML sinks (`innerHTML`, `outerHTML`, `insertAdjacentHTML`, `dangerouslySetInnerHTML`, `srcdoc`, `setHTMLUnsafe`, `parseHTMLUnsafe`, `createContextualFragment`, `DOMParser`, `parseFromString`) anywhere in the source: as an identifier, a JSX attribute on any element, a property key or a string in any case, which covers member and computed access, `setAttribute`, `Reflect.set` and `Object.defineProperty`. `document` may be used only as `document.<name>`, so `document.write`, `writeln`, `window.document`, `document["write"]` and an alias all fail; `no-eval`, `no-implied-eval` and `no-new-func` cover `eval`, `new Function` and a string `setTimeout`. A key built at run time is not checked statically; the CSP is the second line. The fixture marks one line per banned form and a test proves each marked line is reported, and that the rules apply to `src` (S10.3) |
| Dev server | `npm run dev` proxies `/v1` and `/health` to the host (`DALE_WEB_PORT`, default 8000) with `changeOrigin` (the `Host` becomes the host's) and, only when the request's `Origin` names the dev server itself, an `Origin` rewritten to the host's. The host's allow-list stays unchanged and needs no entry for the dev port. A request from another site keeps its own `Origin` and the host rejects it (403), so the proxy cannot launder a cross-site post; the dev server answers only to `server.allowedHosts` = `localhost` and `127.0.0.1` (and IP addresses, which Vite always accepts), never `true`, so a rebinding `Host` gets 403; a test starts the dev server and proves it. The proxy sets no timeout (D17) |
| Supply chain (D22) | Exact versions only: `.npmrc` has `save-exact`, `engine-strict` and `ignore-scripts`; `engines.node` and `.nvmrc` name the same exact Node; the lockfile is committed and CI installs with `npm ci --ignore-scripts`. `tests/unit/test_web_pins.py` fails on a range, a tag, an override, an install-type script, a lockfile that disagrees with the manifest, a locked package that is not an npm registry tarball with a sha512 hash, a `link` entry, or an install script in any locked package but `fsevents`. Every locked package, transitive ones included, is at least two weeks old (see Versions) |
| Install scripts | None needed. Vite 8 (Rolldown), Lightning CSS and Tailwind's Oxide ship their native code as prebuilt optional packages selected by platform (`@rolldown/binding-*`, `lightningcss-*`, `@tailwindcss/oxide-*`), and none has an install script. The only package in the lockfile with one is `fsevents`, macOS only and prebuilt in its tarball, and the pin test keeps it the only one. The install, type check, lint, tests and build were run with scripts ignored. No exception is granted |

### Node

Node 24.22.2 (LTS "Krypton", released 2026-10-27) in `.nvmrc` and `engines`, and used by the `web` job through `node-version-file`. It is the newest 24.x release published at least two weeks before 2026-11-20 (checked against `https://nodejs.org/dist/index.json`) and carries the security fixes of 24.22.1 (2026-10-20); the install, type check, lint, tests and build were run on it. 24.22.3 (2026-11-10, a security release) is under two weeks old; move to it once it is, with `.nvmrc`, `engines` and the checks in the same change. Every dependency's `engines` accepts it (the narrowest is Vitest 5, `^22.12 || ^24 || >=26`). Node 26 became LTS in October 2026 but was not available to verify here; moving up is a deliberate change of `.nvmrc`, `engines` and `@types/node` together.

### Versions

Chosen on 2026-11-20 as stable releases published at least two weeks earlier, checked with `npm view <package> time`. The cutoff is 2026-11-06 and it applies to the whole lockfile, not only to the direct pins: the lockfile is regenerated with

```
cd apps/web && rm -rf node_modules package-lock.json && npm install --before=2026-11-06 --ignore-scripts
```

and every resolved package's publish time is then checked against the registry (`time[<version>]` of its metadata). On 2026-11-20 all 409 locked versions were published on or before 2026-11-05 (the newest, `caniuse-lite` 1.0.30001822, at 2026-11-05T11:32Z). Moving the cutoff is a deliberate change: a new date, the same command and the same check.

| Package | Version | Published |
|---|---|---|
| react, react-dom | 19.3.1 | 2026-10-14 |
| vite | 8.3.6 | 2026-11-05 |
| @vitejs/plugin-react | 6.2.1 | 2026-11-02 |
| tailwindcss, @tailwindcss/vite | 4.3.4 | 2026-11-02 |
| typescript | 6.0.3 | 2026-04-16 |
| vitest | 5.1.0 | 2026-11-02 |
| jsdom | 30.1.3 | 2026-10-15 |
| @testing-library/react | 16.3.3 | 2026-08-27 |
| @testing-library/dom | 10.4.2 | 2026-09-13 |
| eslint, @eslint/js | 9.39.5 | 2026-07-10 |
| typescript-eslint | 8.72.1 | 2026-10-26 |
| eslint-plugin-react | 7.37.5 | 2025-04-03 |
| eslint-plugin-react-hooks | 7.1.1 | 2026-04-17 |
| globals | 17.14.0 | 2026-11-01 |
| json-schema-to-typescript | 16.0.0 | 2026-08-28 |
| @types/react, @types/react-dom | 19.3.0 | 2026-09-09 |
| @types/node | 24.19.2 | 2026-10-09 |

Choices that are not "the newest":

- TypeScript 6.0.3, not 7: typescript-eslint 8.72.1 accepts `typescript >=4.8.4 <6.1.0`.
- ESLint 9.39.5, not 10: `eslint-plugin-react` 7.37.5, the only release, accepts ESLint up to 9, and the task needs its `react/no-danger`. npm reports ESLint 9 as no longer supported; moving to 10 waits for that plugin.
- Vite 8.3.6, not 8.3.8: 8.3.7 and 8.3.8 are under two weeks old.
- jsdom 30.1.3, not 31: 31.0.0 (2026-11-05) is inside the cutoff, but it is a new major and its first fix, 31.0.1 (2026-11-13), is under two weeks old. Moving to 31 waits for 31.0.1 to age, with the tests rerun.
- No `@testing-library/jest-dom`, `user-event` or MSW yet: slice 6 needs none. Slice 7a may add the first two with the same rules.

### Known advisory

`npm audit` reports 7 moderate findings, all one issue: a denial of service in `minimatch` 7 to 11 reached through typescript-eslint 8.72.1, which uses it to match globs from our own ESLint config. It runs only in development and CI on repository files, never in the built page; typescript-eslint 8.73.0 (2026-11-16) fixes it and is under two weeks old. Update it to 8.73.0 or later once it is old enough, with the lockfile in the same change.

### Alternatives rejected

- Caret ranges with a lockfile only: `npm install` would move versions without a diff in `package.json`.
- TanStack Query or Zustand: there is no server cache to manage and no state shared across screens.
- `overrides` to pin a vulnerable transitive package: it hides a version change from the manifest, which the pin test forbids.

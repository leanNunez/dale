# 0006. Contract v1, schema generation and the frontend stack

Date: 2026-11-19
Status: accepted (contract and generation); the frontend and Node section lands with the page scaffold

## Context

The host and the page exchange JSON. A hand-written copy of those shapes on each side drifts, and
the page renders model-controlled text, so an untyped payload is a risk. This record fixes where
the contract lives, how it is generated and how drift is caught. The frontend stack and the Node
pins (design D21 and D22) are appended when the page is scaffolded. Design decision D20 is
summarized here.

## Decision

| Topic | Decision |
|---|---|
| Source of truth (D20) | The Python types in `dale.channels.web.contract`: pydantic models for the commands, the envelope and the web-only events, and the shared dataclasses for the shown events. `dale.shared` stays free of pydantic (import contract 6). The `data` of a shown event is exactly the verifier's JSON form, so one form serves both readers |
| Wire types | Eight event types (`AssistantText`, `ProposalSummary`, `OrderConfirmed`, `OrderRejected`, `HandoffNotice`, `SystemNotice`, `ToolCalled`, `VerdictIssued`), three commands (`SendMessage`, `PressDale`, `CancelProposal`) and `ResponseEnvelope`. `ToolCalled` and `VerdictIssued` are not shown events and never reach the verifier's input |
| Strict types | Commands use `extra="forbid"`: a client total, a customer id or a company id fails validation. Text is a real string of 1 to 2000 characters, not blank, with no control character but newline and tab; ids are hyphenated 36-character UUIDs. Everything the host emits is strict (no coercion, aware datetimes) and consistent: a verdict obeys the runner's rules, an error carries its catalog message, an envelope's events share its conversation and end at its `seq` |
| Errors (D14) | A brain outcome keeps its `ErrorCode` and its status; transport failures use `WebErrorCode`, a disjoint catalog with one fixed status and one fixed Spanish message per code. Messages carry no exception text |
| Components | `COMPONENTS` maps each event type to one typed UI component (`ChatText`, `OrderSummary`, `OrderConfirmation`, `Notice`, `HandoffNotice`, `ToolTrace`, `Verdict`) and is written to `components.json`. The page switches over it exhaustively |
| Generation | `python -m dale.channels.web.schema_gen` writes `contracts/v1/<Type>.schema.json` and `components.json`: sorted keys, 2-space indent, trailing newline, `additionalProperties: false` on every object that does not already describe its extra keys. Output types use serialization mode with defaulted fields (`v`, `type`) required; commands use validation mode, so a defaulted field is optional to send. The output is committed |
| Drift checks | A golden test in the `test` job fails when regeneration differs from the committed files, including a missing or extra file; renaming or removing a field changes the output. TypeScript generation and its `git diff --exit-code` check arrive with the page |
| Versioning (W5) | v1 is additive-only: optional fields and event types may be added, none removed or changed in meaning. Responses and events carry `v: 1`; commands carry no `v` and are versioned by the `/v1` path. `GET /v1/contract` reports `v: 1`. The published schemas are closed, so an addition changes them; the page uses the TypeScript types at compile time, does not reject a response at runtime against the schema, and ignores an unknown event type (planned, slice 7) |
| English identifiers | Property names, definition names and enum values are English (a test scans them); Spanish appears only in message text |
| Samples | `contracts/v1/samples/` holds one authored JSON per event type plus commands and an envelope. Tests round-trip them; the page's type test (planned, slice 7) compiles over them |
| Size guard | Generated `contracts/**/*.schema.json` and `contracts/v1/components.json` are excluded from the PR size count; the samples, this record and the source types still count |

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

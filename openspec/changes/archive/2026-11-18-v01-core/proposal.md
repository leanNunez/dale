# Proposal: Dale v0.1 "El núcleo"

## Intent

v0.1 delivers a verified wholesale order taken by chat in the terminal. The model proposes and code confirms. An independent verifier checks the result against PostgreSQL. Its headline number is **verified orders / attempted orders, with zero false confirmations**, plus cost per verified order, from a published eval suite.

Sources: the internal plan §3–6 and the kickoff (both private). Decisions closed there are not reopened.

## Scope

### In Scope

| Area | Deliverable |
|---|---|
| Repo | Public, MIT, README in English and Spanish, fiction notice |
| CI | Lint, strict types, tests against real Postgres, secret scanning, architecture rules |
| Service | One Python service with three modules behind interfaces: management (`erp-sim`), `brain`, `verifier`. The modules must be splittable in v0.5 |
| Data | "Distribuidora El Hornero" (fictitious): customers, zones, catalog of invented brands, price list, orders. `company_id` column from day one |
| Rules in DB | Minimum purchase amount and delivery by zone and cutoff (see Business rules) |
| Brain | Own loop on `claude-haiku-5-5` with five tools: search products, check prices, check delivery, prepare order, request human handoff. Prompt caching from the start: the prompt is ordered by change frequency |
| Confirmation | Dale is a terminal key handled by code, never by the model |
| Verifier | Separate process with a read-only DB role |
| Evals | 15–20 frozen-state cases, including 4–5 gauchadas, 3 runs each. Recorded responses for CI |
| Report | Verified orders, false confirmations, cost per verified order |

### Out of Scope

Web page, second model, multiple companies, current account, platform, Telegram, admin panel, live demo, and stock management.

### Known pending items

- RLS policies and two-company isolation tests (v0.4).
- Signed inter-service contract, inbox and outbox (v0.5).
- Prompt caching tuning and hit-rate targets, OpenTelemetry and Langfuse. (Caching itself is in scope from v0.1: the prompt is ordered by change frequency, per plan §3.)
- Customer memory.

## Session decisions (user-approved)

| # | Decision |
|---|---|
| 1 | Distributor: "Distribuidora El Hornero". Brands are invented |
| 2 | The prepared order is a **proposal owned by the brain** (plan §4.2), with a server-generated ID. On the Dale key, code sends it to management. Management revalidates the rules and creates the confirmed order. The proposal ID is the idempotency key. The verifier compares what was confirmed with the DB |
| 3 | Model `claude-haiku-5-5`. It has no server-side refusal fallback, so code MUST handle `stop_reason: "refusal"`. The client is `Anthropic()` with no arguments (profile `dale`). Never `ANTHROPIC_API_KEY`, never a `.env` with keys, never touch `~/.config/anthropic/`. CI runs without the API |
| 4 | The minimum purchase is an **amount in pesos**: the sum of line totals computed from server-side prices |
| 5 | Each customer belongs to a zone with fixed weekdays. An order makes the next delivery only if it is received before the cutoff hour on the previous day |
| 6 | **Deviation from plan (four tools become five):** a handoff tool writes a request with a reason to the DB, and the agent tells the customer that a person will contact them |

## Order journey (terminal, adapted from plan §4.4)

1. The customer types: "mandame 5 packs de la cola de dos y cuarto".
2. The session identifies the company and customer, then passes the message to the brain.
3. The brain uses tools to get products and prices. If anything is ambiguous, it asks.
4. `prepare_order` checks the rules (first check) and stores a proposal with a server ID.
5. The terminal shows a summary built from the proposal data, plus the Dale key prompt.
6. On the key press, code calls management `confirm(proposal_id)`.
7. Management revalidates the rules (second check). It either confirms the order or rejects it with a catalog code.
8. The customer sees a message built from management's response.
9. The verifier compares the confirmation with the DB. Only then does the order count as verified.

## Design rules

| Rule | Meaning in v0.1 |
|---|---|
| The model proposes, code executes | Confirmation is code driven by the proposal ID |
| Typed text approves nothing | Typing "dale" never confirms; only the key does |
| Limits are checked twice | At prepare and at confirm, with an idempotency key |
| Data only from tools | The agent uses only IDs and prices returned in that conversation |
| Tools are denied by default | A closed tool list and a turn limit |
| Customer text is data | It is never treated as an instruction |
| Grade the final state | Evals inspect the DB and what was shown, not the path taken |
| One negative case per positive | Gauchadas: the agent must not promise an exception |

## Capabilities

### New Capabilities
- `verified-order`: the single v0.1 spec. It covers catalog and rules, the brain tools and loop, the proposal and confirmation, handoff, the verifier, evals and the report.

### Modified Capabilities
None.

## Approach

Each module is hexagonal and exposes ports. Imports are enforced by import-linter. The clock is injectable, so frozen-state cases fix "now" for the cutoff rule. The eval harness runs on pytest. It replays recorded model responses in CI and calls the live model before release.

## Affected Areas

| Path (planned) | Impact |
|---|---|
| One service (plan §4.5: a single service in early versions, with the modules inside) | New. Exact layout is decided in design |
| Management module (`erp-sim`) | New: schema, migrations, seed, rules, confirm |
| Brain module | New: loop, tools, proposals, handoff, terminal session |
| Verifier module | New: read-only comparison, run as a separate process. It shares code with the eval harness (plan §4.2) and is not a service |
| `evals/` | New: cases, recordings, report |
| `.github/workflows/`, `README*.md`, `LICENSE` | New |

## Success Criteria

- [ ] Verified / attempted is reported for each run. False confirmations = 0.
- [ ] Cost per verified order is reported.
- [ ] 15–20 cases (4–5 gauchadas) pass^3. pass^1 is also published.
- [ ] A gauchada passes only if a handoff exists, no order was created and no exception was applied.
- [ ] CI is green with no API calls.

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| A one-week timebox | High | Slip days. Never cut the verifier or the evals |
| Haiku refusals or wrong tool use | Med | Handle `refusal` explicitly; eval-gated |
| A recorded response drifts from the live model | Med | Run the live suite before each release |
| Credential leak in a public repo | Low | Secret scanning; `Anthropic()` with no arguments |

## Rollback Plan

The project is greenfield, with demo data only. Each chained PR is revertible on its own. Migrations are forward-only. To roll back the DB, drop it and reseed. The v0.1 tag is published only after the report passes.

## Size forecast (rough; tasks will refine it)

About 2,600 authored lines, which means roughly 7–8 chained PRs. **400-line budget risk: High.** Possible slices: skeleton and CI, schema and seed, rules and confirm, brain and tools, terminal and key, verifier, evals, report and README.

## Open questions for design

1. Who owns the handoff record in v0.1, given that the platform owns "who attends" and does not exist yet?
2. How does the terminal session identify the company and the customer?
3. Is the minimum amount set per distributor or per zone?
4. At confirm, how are a price change or a missed cutoff handled: reject, or re-quote?
5. Which key confirms, and how is it kept apart from text input?
6. Where are proposals stored: brain tables in the same DB, or in memory?

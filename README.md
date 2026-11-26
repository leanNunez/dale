# Dale

[Español](README.es.md)

An AI agent that takes wholesale orders by chat and checks each one against the
business database before anything is called "confirmed".

> **Fiction notice.** Dale's demo company, "Distribuidora El Hornero", its
> customers, brands and products are invented. No real company, brand or
> customer data is used anywhere in this repository.

**Status: v0.2, a web page and the terminal.** Claude Haiku 5.5 stays the default model after a
pre-registered comparison with Claude Sonnet 5.5 (see [Results](#results)).

## What Dale does

A customer writes in Spanish; the model finds products, quotes server prices and
prepares a proposal. The customer confirms by pressing Dale (the `F2` key in the
terminal, the Dale button on the web page), not by typing a word. A separate process then re-reads the database and compares
each confirmation shown with the stored order and proposal and with its own
rules. It also flags model text that claims a confirmation, by matching a phrase
list: it can miss a paraphrase (an LLM judge is still pending). Prices and
dates written as free text are not checked. The model never writes an order.

## The five tools

| Tool | What it does | What it cannot do |
|---|---|---|
| `search_products` | Searches the catalog | Return prices |
| `get_prices` | Current unit prices | Invent or change a price |
| `check_delivery` | Next delivery date, cutoff, minimum | Grant a date or an exception |
| `prepare_order` | Prepares a proposal at server prices | Confirm it |
| `request_human_handoff` | Asks a person to take over | Grant an exception |

Confirmation lives in code, outside the model: the Dale key confirms a pending
proposal, and typed text never does ([decision 0002](docs/decisions/0002-confirm-key.md)).

## Modules

| Module | Role |
|---|---|
| `dale.erp_sim` | The simulated business: catalog, prices, zones, orders. `brain`, `channels` and `verifier` reach it only through `erp_sim.public` (import-linter contracts in `pyproject.toml`) |
| `dale.brain` | The model loop, tools and proposals |
| `dale.verifier` | A separate process with a read-only database role; it checks each confirmation shown to the customer |
| `dale.channels.terminal` | The chat screen and the keys |
| `dale.channels.web` | The HTTP API of the web page and its JSON contract (`contracts/v1/`) |
| `apps/web` | The page: React and TypeScript, built with Vite; it types its API from the generated contract |
| `evals/` | The case suite, replay and live runs, the release report |

Import rules are enforced by `lint-imports`.

## Run it

Needs Linux or macOS (the terminal uses `termios`), Python 3.13,
[uv](https://docs.astral.sh/uv/) and a local PostgreSQL 17 (the repository ships
no compose file). The dev roles have no password, so the server must trust local
connections (see the header of `db/roles.sql`). `psql -f db/roles.sql` and
`createdb` run as a superuser. Replace the URLs with your own.

```bash
uv sync
psql -v ON_ERROR_STOP=1 -f db/roles.sql                # as a superuser
createdb --owner=dale_owner dale
DALE_OWNER_DATABASE_URL=postgresql+psycopg://dale_owner@127.0.0.1/dale uv run alembic upgrade head

export DALE_APP_DATABASE_URL=postgresql+psycopg://dale_app@127.0.0.1/dale
export DALE_VERIFIER_DATABASE_URL=postgresql+psycopg://dale_verifier@127.0.0.1/dale
uv run python -m dale.erp_sim.infrastructure.seed      # seeds Distribuidora El Hornero

ant auth login                                         # the SDK reads the active profile (ant auth status)
DALE_TERMINAL_COMPANY=el-hornero uv run python -m dale.apps.terminal --customer C-001
```

In the chat: `F2` confirms the pending proposal (the Dale key), `F3` drops it,
`Ctrl-C` clears the line, `Ctrl-D` exits. `F2` is ignored when there is text in the
buffer (a hint is shown), when no proposal is pending, in a paste or multi-key
burst, and for 1 s after a paste. After each confirmation the verifier prints its verdict. Logs go
to `DALE_TERMINAL_LOG` (default `~/.local/state/dale/terminal.log`), never into
the chat. `F2` is checked inside tmux and Zellij
([decision 0002](docs/decisions/0002-confirm-key.md)).

### The web page

Needs Node 24.22.2 (`apps/web/.nvmrc`) on top of the setup above. The host serves the API and the
built page on `127.0.0.1` only (port `DALE_WEB_PORT`, default 8000), with one worker:
conversations live in memory and are lost on restart. The customer is fixed by
`DALE_WEB_CUSTOMER` (default `C-001`).

```bash
(cd apps/web && npm ci --ignore-scripts && npm run build)   # writes apps/web/dist
DALE_WEB_COMPANY=el-hornero uv run python -m dale.apps.web  # with the two URLs exported above
# open http://127.0.0.1:8000
```

For page work, `cd apps/web && npm run dev` serves the page with Vite and proxies the API to the
host on `DALE_WEB_PORT`.

The page shows the chat with the proposal, the **Dale, confirmar pedido** button (the only
thing that confirms the pending proposal; typed text never does) and **Cancelar propuesta**.
Next to the chat (below it on a narrow screen), three panels show what happened behind the
reply:

| Panel | What it shows |
|---|---|
| Tools used (Herramientas usadas) | Each tool the model called in this conversation, in order, and whether it returned or failed with which error |
| Stored order (Pedido guardado en la base) | The order as the verifier read it from the database, not as the chat showed it |
| Verifier verdict (Veredicto del verificador) | The verifier's verdict after each press: verified, not verified with the fields that differ, nothing confirmed, or could not verify |

The verifier alone: `uv run python -m dale.verifier` reads a JSON request on stdin
and prints a verdict as JSON.

## Tests and evals

```bash
uv run pytest tests/unit   # no database
uv run pytest              # needs Postgres; see below
```

The database tests use `DALE_TEST_ADMIN_URL` (default
`postgresql+psycopg://postgres@127.0.0.1:5432/postgres`): a superuser URL on a
local server that trusts local connections. They drop and recreate a database
named `dale_test`; the `dale` database above is not touched.

Two models are compared, and each has its own recordings under `evals/recordings/<model>/`:
`claude-haiku-5-5` (the shipped default) and `claude-sonnet-5-5`. Both come from the v0.2
record runs on commit `f9db72a` (2026-11-26, 40 cases x 3 runs). CI replays each model in its own
`evals (<model>)` job.

```bash
# replay (recorded model, no network, no key); needs Postgres
uv run pytest evals --model claude-haiku-5-5
uv run pytest evals --model claude-sonnet-5-5
uv run pytest evals --live --model <id>   # calls the live model, spends money
```

A run that fails is committed as recorded, not re-run until it passes:
`evals/recordings/<model>/known_misses.toml` lists it with its reason and the sha256 of its
recording, and replay checks that it still fails the same way and never confirms anything.

A record run (after `ant auth login`) spends money, so it follows a fixed procedure:

1. On the run day, re-check both price tables against the live pricing page, update
   `evals/pricing.toml` (`retrieved` and the notes) and commit it before any record run. That is
   the record commit, unless a fix forces a re-record that day: then it is the fix's head, with
   `evals/pricing.toml` unchanged. In v0.2 the prices were checked in `7d3a4f0` and both models
   recorded on `f9db72a`, after the claim detector fix.
2. Record both models on that commit, the same day, with nothing committed in between (a record
   run ignores only `evals/recordings/` and `evals/reports/` when it checks for a clean tree):

   ```bash
   uv run pytest evals --live --record --report v0.2 --model claude-haiku-5-5
   uv run pytest evals --live --record --report v0.2 --model claude-sonnet-5-5
   ```

3. `uv run python -m evals.harness.compare v0.2` applies the comparison rule to the two reports
   and writes `evals/reports/v0.2-comparison.{json,md}`, or refuses and writes nothing.

## Results

### v0.2: the model comparison

The rule that picks the default model was committed before any Sonnet recording existed
([decision 0007](docs/decisions/0007-model-comparison-rule.md)) and is applied by code. Both
models recorded the same 40 cases x 3 runs on one commit, the same day, at effort medium.
Report: [`evals/reports/v0.2-comparison.md`](evals/reports/v0.2-comparison.md).

| Model | Hard gates (false confirmations, disallowed writes, unverifiable runs, gauchada exceptions) | pass^3 | Verified orders | Cost, all 120 runs | Cost per verified order |
|---|---|---|---|---|---|
| `claude-haiku-5-5` | pass, all 0 | 37 / 40 | 38 | USD 0.062 | USD 0.0016 |
| `claude-sonnet-5-5` | pass, all 0 | 40 / 40 | 39 | USD 0.94 | USD 0.024 |

Outcome: `select:claude-haiku-5-5`. A pass^3 difference of 3 is below the minimum meaningful
difference of 4, so it is a tie, and Haiku is far more than 20% cheaper per verified order.
`MODEL_SETTINGS` does not change ([decision 0008](docs/decisions/0008-default-model-after-comparison.md)).
Costs are token counts at the list prices checked on the run day, not billed amounts.

A first Haiku record run was discarded: its 4 false confirmations were all the claim detector
misreading correct, negated replies such as "No es un pedido confirmado todavía.". The detector
was fixed, and both models were then recorded on the fixed commit.

### v0.1: the release run

From the release run `evals/reports/v0.1-run4.md` (2026-11-16, `claude-haiku-5-5`,
18 cases x 3 runs, live and recorded):

| Metric | v0.1 |
|---|---|
| Verified / attempted (attempted: the 15 runs whose case expects an order) | 14 / 15 |
| pass^3 (a case counts only if its runs 1, 2 and 3 all passed) | 17 / 18 |
| pass^1 (the share of runs that passed) | 53 / 54 (98.1%) |
| False confirmations (in these 54 runs, as the verifier and its phrase list count them) | 0 |
| Model refusals (the API stopped with `stop_reason` refusal) | 0 |
| Cost per verified order (token counts at Anthropic list prices retrieved 2026-11-16, `evals/pricing.toml`; not a billed amount) | USD 0.0018 (USD 0.025 for all 54 runs) |

The one failed run (`order-cola-ok` run 1) asked the customer before preparing the
order, so nothing was proposed or confirmed; it is kept as recorded.

It took four live runs to get there, and every report is committed:

| Run | Report | Gate | What it found |
|---|---|---|---|
| 1 | `evals/reports/v0.1.md` | FAIL, 3 false confirmations | The live run kept no transcripts, so the three could not be read: their cause is unknown, and they may have been real |
| 2 | `evals/reports/v0.1-run2.md` | FAIL, 2 | Both were false alarms: one reply said no order was confirmed ("no quedó ningún pedido confirmado"), the other said the order would be confirmed once the key was pressed ("una vez que lo aprietes, queda confirmado"); the prompt now bans the claim words in any form |
| 3 | `evals/reports/v0.1-run3.md` | FAIL, 1 | "No hay pedido confirmado todavía" read as a claim; the claim check now reads a negated "no hay [ningún] pedido" at the end of a clause, or before todavía/aún/hasta, as no order, from closed word lists |
| 4 | `evals/reports/v0.1-run4.md` | PASS, 0 | The release run above |

A false confirmation is the verifier's count of confirmations shown without a
verified order behind them, and of model text that the phrase list reads as a
confirmation with no verified one shown right before it, plus one for any run that
showed a confirmation whose verdict is not `verified`. The phrase list can miss a
paraphrase, so 0 is what these 54 runs measured, not a guarantee. The report carries a release-gate flag that blocks on
false confirmations, unexpected writes, unverifiable runs and runs that raised.

## How Claude Code was used

- Spec-driven development: proposal, spec, design and tasks live in `openspec/`.
- Stacked slices of at most 400 authored lines, each its own branch.
- A separate, blind "what breaks" review per slice; each fix is folded into the
  commit that introduced the defect.
- Mutation checks: each guard was shown to fail when its code is broken; they are
  recorded in the decision log and the apply-progress notes.
- A decision log records every choice and why:
  `openspec/changes/archive/2026-11-18-v01-core/decision-log.md` (v0.1) and
  `openspec/changes/archive/2026-11-26-v02-web/decision-log.md` (v0.2).

## License

MIT, see [LICENSE](LICENSE).

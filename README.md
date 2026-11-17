# Dale

[Español](README.es.md)

An AI agent that takes wholesale orders by chat and checks each one against the
business database before anything is called "confirmed".

> **Fiction notice.** Dale's demo company, "Distribuidora El Hornero", its
> customers, brands and products are invented. No real company, brand or
> customer data is used anywhere in this repository.

**Status: v0.1, terminal only.** The release results are not in yet (see
[Results](#results)).

## What Dale does

A customer writes in Spanish; the model finds products, quotes server prices and
prepares a proposal. The customer confirms by pressing the Dale key (`F2`), not
by typing a word. A separate process then re-reads the database and compares
each confirmation shown with the stored order and proposal and with its own
rules. It also flags model text that claims a confirmation, by matching a phrase
list: it can miss a paraphrase (an LLM judge is planned for v0.2). Prices and
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
the chat. `F2` is checked inside tmux; Zellij is still pending
([decision 0002](docs/decisions/0002-confirm-key.md)).

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

```bash
# replay (recorded model, no network, no key); needs Postgres; CI runs this on every PR
uv run pytest evals
uv run pytest evals --live            # calls the live model, spends money
uv run pytest evals --live --record   # also writes the recordings
# release run (after `ant auth login`); replaces any existing report of that version
uv run pytest evals --live --report v0.1   # writes evals/reports/v0.1.{json,md}
```

The recordings in `evals/recordings/` come from the first live run (2026-11-16,
`claude-haiku-5-5`). A run that failed live is kept as recorded, never re-recorded until
it passes: `evals/recordings/known_misses.toml` lists it with its reason, and replay
checks that it still fails the same way and never confirms anything.

## Results

Filled from `evals/reports/v0.1.md` when the release run is done.

| Metric | v0.1 |
|---|---|
| Verified / attempted | pending the v0.1 release run |
| pass^3 (a case counts only if its runs 1, 2 and 3 all passed) | pending the v0.1 release run |
| pass^1 (the share of runs that passed) | pending the v0.1 release run |
| False confirmations | pending the v0.1 release run |
| Model refusals | pending the v0.1 release run |
| Cost per verified order | pending the v0.1 release run |

A false confirmation is the verifier's count of confirmations shown without a
verified order behind them, plus one for any run that showed a confirmation whose
verdict is not `verified`. The report carries a release-gate flag that blocks on
false confirmations, unexpected writes, unverifiable runs and runs that raised.

## How Claude Code was used

- Spec-driven development: proposal, spec, design and tasks live in `openspec/`.
- Stacked slices of at most 400 authored lines, each its own branch.
- A separate, blind "what breaks" review per slice; each fix is folded into the
  commit that introduced the defect.
- Mutation checks: each guard was shown to fail when its code is broken; they are
  recorded in the decision log and the apply-progress notes.
- A decision log records every choice and why:
  `openspec/changes/v01-core/decision-log.md`.

## License

MIT, see [LICENSE](LICENSE).

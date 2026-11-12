# Apply progress: v01-core

Mode: Standard (strict_tdd false). Delivery: feature-branch-chain, integration branch `dev`.

## Slice 1 (two chained PRs; history rewritten locally after the blind review)

| PR | Branch | Base | Commits | Authored lines (limit 400) |
|---|---|---|---|---|
| 1a | `slice-01a-scaffold` | `dev` | docs(openspec), docs, build, ci (workflow) | 399 |
| 1b | `slice-01b-ci` | `slice-01a-scaffold` | ci (API key and PR size guards), ci (secrets and size jobs) | 398 |

Completed: 1.0 to 1.7 and the blind-review fixes below. Pending: 1.8 (gated on the user's explicit yes; the repo must use merge commits, no squash, so stacked diffs stay correct), 1.9 (PR bodies).

### Work Unit Evidence

| Evidence | Result |
|---|---|
| Focused test command | `uv run pytest` on each branch: 15 passed on 1a, 57 passed on 1b |
| Runtime harness | Per branch: `uv sync --locked`, `ruff check`, `ruff format --check`, `mypy` (strict), `lint-imports` (9 contracts kept), `check_pr_size.py` against the base: all green; `ci.yml` parsed with pyyaml, every job has `timeout-minutes` |
| Rollback boundary | 1b: `scripts/`, the three guard tests, the `secrets` and `size` jobs. 1a: the scaffold and the lint/types/arch/test/pr-base/tracked-files jobs |

### Blind-review fixes (slice 1)

- Import-linter contracts are written by exclusion: `anthropic` is forbidden for all of `dale` except `brain.infrastructure`; `brain` reaches `erp_sim` only through `erp_sim.public`; `shared` forbids `dale.*` (covers future packages), sqlalchemy, pydantic and anthropic. Probes on a throwaway copy of each reported gap now break the contracts.
- `.gitignore` keeps `.env.example` trackable; CI fails on tracked `.atl/` or `.env*` files and on a PR into `main` that is not same-repository `dev`.
- The API key guard scans tracked code and config repo-wide, case-insensitive, prints file names only, fails on read errors, and an AST test rejects any argument to `Anthropic(...)` under `src/`.
- The PR size guard exempts only same-repository `dev` into `main`, fails closed on a malformed numstat line and surfaces git's stderr.

### Deviations and risks

- Contract ids: 3 became 3a/3b and 7 became 7a/7b (the tool has no single contract for those shapes); nine contracts in total.
- `src/dale/apps/verifier.py` is an empty placeholder so contract 4 can resolve its source module; slice 10 fills it.
- Known pending: GitHub Actions are pinned by tag, not by SHA (needs network); `gitleaks-action` permissions and the `setup-uv@v6` and `gitleaks-action@v2` tags are unverified until the first CI run; `actionlint` is not installed (workflow checked with pyyaml only); no committed regression test runs the contract probes (the probes were run ad hoc); the AST test does not see dynamic construction such as `getattr(anthropic, "Anthropic")(...)`.

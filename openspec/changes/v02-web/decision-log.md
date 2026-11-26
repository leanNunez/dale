# Decision log: v02-web

This is a dated record of the decisions made while building Dale v0.2 "Se ve". The build runs as in v0.1: each slice is implemented, reviewed against the spec and design, reviewed blind, and fixed; when a decision comes up, the recommended option is taken and logged here. User hard gates (see `tasks.md`) still wait for the user.

Entries marked **user** were chosen by the user. Entries marked **auto** were taken by the orchestrator under that rule.

## Planning (2026-11-19, all chosen by the user)

| # | Decision | Choice | Source |
|---|---|---|---|
| P1 | Release order | Build v0.2 in full before the v0.3 live demo; v0.2 must not block v0.3 | user |
| P2 | Recordings | No video or recording in any release | user |
| P3 | SDD preflight | Interactive mode, hybrid artifact store, ask-on-risk, 400-line review budget | user |
| P4 | Exploration recommendations | All six accepted: request/response with an SSE-ready envelope; the order panel shows the stored order the verifier read; one fixed seeded customer; compare only the model (Haiku 5.5 vs Sonnet 5.5, effort medium); one retroactive founding-decisions record; a required Node `web` CI job with lockfile and generated files excluded from the size guard | user |
| P5 | Proposal | Accepted with the pre-registered comparison rule and the four question-round assumptions (proposal.md) | user |
| P6 | Spec and design | Accepted; the orchestrator aligned spec W11 (separate web error catalog) and W12 (a press of the same proposal waits and gets the settled response) with design D14-D16, and added S7.6 (a cancelled proposal cannot be pressed) | user |
| P7 | Delivery | 14 chained PRs (slices 0-10 in `tasks.md`), each based on the previous slice, integrated on `dev`, one release PR `dev` to `main` | user |
| P8 | Build loop | Slices implemented by agents (Sonnet high; Opus high for 5a and 5b; Opus for blind reviews), commits kept local; no push or PR until the user asks | user |

## Build

| # | Date | Decision | Options | Choice | Reason | Source |
|---|---|---|---|---|---|---|
| B1 | 2026-11-19 | Task 0.1 says `dev` must equal `main` | Make them equal; keep them as they are | Keep: `dev` is ahead of `main` by the archive docs (#65, #66) and `main` holds only the release merge commit 85fdb96, whose tree came from `dev`. Code is identical | The integration branch is meant to lead `main`; the release PR reconciles them | auto |
| B2 | 2026-11-19 | `strict_tdd` | Turn on now that pytest exists; keep off | Keep `false`, as in v0.1. Every behavior task still names its test and lands with it | The tasks already pair each change with its test; strict TDD would add ceremony without changing what lands | auto |
| B3 | 2026-11-19 | Contract 10 in design §2 is one contract with two parts (independence plus `common` forbidden) | One id "10"; ids "10a" and "10b" | "10a" (independence of terminal and web) and "10b" (`common` imports neither), as 3a/3b and 7a/7b do | The tool expresses each contract type separately | auto |
| B4 | 2026-11-19 | Slice 1 commit order: task 1.4 (pins) before 1.3 (contracts) | Follow task numbering; pins first | Pins first | Contract 9 puts `fastapi`, `starlette` and `uvicorn` in `root_packages`, which needs them installed, so each commit passes `lint-imports` on its own | auto |
| B5 | 2026-11-19 | The moved `step` logged "terminal step %s failed" | Keep the word "terminal"; say "channel" | "channel step %s failed" | The function now serves the web channel too; no test reads the message, so the move stays behavior-neutral | auto |
| B6 | 2026-11-19 | Slice 1 blind review: the D17 worst case of 19.5 min is wrong | Keep the number; correct it | No fixed bound: without `retry-after` a turn takes up to about 18.5 min (6 x 3 x 60 s + 30 s), and the `anthropic` SDK waits as long as `retry-after` asks. The stack configures no request timeout and a test pins that; a turn deadline in the brain is pending and required before v0.3 | A test that pins "above 19.5 min" would pin a false bound | auto |
| B7 | 2026-11-19 | Slice 1 blind review: Starlette 1.10's `TestClient` imports `httpx2` first, so the `httpx` dev pin was unused | Keep `httpx`; pin `httpx2` | Pin `httpx2==2.16.0` (dev) and drop `httpx` | The pin must name the library that actually runs | auto |
| B8 | 2026-11-19 | Slice 1 blind review: contract 9 allowed only top-level `fastapi`/`starlette`/`uvicorn` imports, left `evals` free, and nothing kept `prompt_toolkit` out of `common` | Leave as is; widen and add | Contract 9 also allows their submodules and `dale.apps.web.**`, and covers `evals`; new contract 12: `prompt_toolkit` only in `dale.channels.terminal` (an allow-list). Probes: submodule imports from `channels.web` and `apps.web` pass; `prompt_toolkit` in `common` and `fastapi.testclient` in `evals` fail | The next web slice needs `fastapi.responses`; a deny-list missed the terminal UI library | auto |
| B9 | 2026-11-19 | Slice 1 blind review: `starlette` is imported directly but was pinned only through `fastapi` | Transitive; direct pin | Direct pin `starlette==1.10.0` with its own ADR 0001 row | ADR 0001 pins every directly imported dependency | auto |

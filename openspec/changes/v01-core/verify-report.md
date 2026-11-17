```yaml
schema: gentle-ai.verify-result/v1
evidence_revision: sha256:05e4acee76ecc661df3db46050f9bebf0cd82767b3e7831d470ddaab7ed8a0f3
verdict: fail
blockers: 5
critical_findings: 0
requirements: 10/15
scenarios: 37/43
test_command: DALE_TEST_ADMIN_URL=postgresql+psycopg://postgres@127.0.0.1:55432/postgres uv run pytest
test_exit_code: 0
test_output_hash: sha256:672f96db3ba4a6054a2ae9a5820ce76c13c58f6429310d2604bebc13797f344c
build_command: uv run mypy
build_exit_code: 0
build_output_hash: sha256:866f135eda15a6396df37bd084c95fd89cee94239a37fcd17a9f9b0eb3878445
```

## Verification Report

**Change**: v01-core (Dale v0.1 "El núcleo")
**Version**: spec `verified-order` (R1-R15, 43 scenarios)
**Mode**: Standard (strict_tdd false)
**Candidate**: branch `slice-15a-readme`, HEAD `4742a3a`, plus working-tree `tasks.md`, `apply-progress.md` (modified) and `decision-log.md` (untracked). `evidence_revision` is the sha256 of `git rev-parse HEAD`, `git diff HEAD` and `decision-log.md`.

### Verdict

| Scope | Verdict |
|---|---|
| Offline (everything that can run without the live model or the user) | **PASS WITH WARNINGS**: every check is green, 1011 tests pass, no defect found, 0 CRITICAL |
| Archive readiness | **NOT READY** (envelope `verdict: fail`). 5 scenarios can only be proven by the gated live runs (14.1/14.9, 15.2). User checks 11.6 (Zellij) and 15.5, and publication gates 1.8 and 15.6, are still open |

`blockers: 5` counts the deferred-by-gate scenarios. These are gates, not defects: no code change is expected to clear them.

The validator was not available. `gentle-ai sdd-verify-validate` does not exist in gentle-ai 3.3.0 (`unknown command`), so this report is written without native admission, as the orchestrator asked.

### Checks run

| Check | Result |
|---|---|
| `uv sync --locked` | exit 0 (50 resolved, 47 checked) |
| `uv run ruff check` | exit 0, "All checks passed!" |
| `uv run ruff format --check` | exit 0, 180 files already formatted |
| `uv run mypy` (strict, src/scripts/tests/migrations/evals) | exit 0, no issues in 169 files |
| `uv run lint-imports` | exit 0, 10 contracts kept, 0 broken (contract 2: 4 ignored imports, all `brain -> erp_sim.public`; 7b: 1 ignored, `brain.infrastructure -> anthropic`) |
| `bash scripts/check_no_api_key.sh` | exit 0 |
| Throwaway DB | `postgres:17` on 127.0.0.1:55432. `db/roles.sql` ran twice, exit 0 both times (idempotent). `createdb --owner=dale_owner dale` exit 0 (psql/createdb run through `docker exec`; no host psql). `alembic upgrade head` exit 0, at `0005 (head)` |
| `uv run alembic check` | exit 0, "No new upgrade operations detected." |
| `uv run pytest` (full, `DALE_TEST_ADMIN_URL` set) | exit 0, **1011 passed**, 0 skipped, 0 failed (60.5 s) |
| `uv run pytest tests/integration/test_harness.py tests/integration/test_report.py` | exit 0, 23 passed |
| `uv run pytest evals` | exit 1, **54 failed** (18 cases x 3 runs). Every failure is `ReplayError: evals/recordings/<case>/run-N.jsonl: no recording (record it with --record)`, chained from `FileNotFoundError`. No other failure mode. This is the expected result until 14.9 |
| Container cleanup | `dale-verify-pg` removed. No other container was touched |
| Not available | Coverage (no pytest-cov installed). GitHub CI (no remote, so gitleaks, `setup-uv`/`gitleaks-action` tags and psql on the runner were never exercised). Live/record runs (forbidden). Zellij |

### Requirement and scenario coverage

Classes: **C** covered (code plus a passing test), **D** deferred-by-gate, **X** contradicted (the code or a decision disagrees with the spec text). No scenario is covered-by-design-only or missing.

| Scen. | Class | Implementation | Passing test(s) (file::test) |
|---|---|---|---|
| S1.1 | C | `brain/domain` GroundingLedger, `tools.py` prepare_order through `quote` | `unit/brain/test_tools.py::test_it_stores_quoted_prices_and_shows_the_stored_proposal`, `::test_reads_ground_only_what_the_server_returned_in_this_conversation`, `integration/test_catalog.py::test_search_finds_the_cola_by_its_spoken_size_and_lists_every_ambiguous_match`, `integration/test_harness.py::test_the_positive_case_ends_in_one_verified_order_each_run` |
| S1.2 | C | tool schemas have no price field; prices only from `quote` | `test_tools.py::test_tools_are_closed_strict_and_require_every_property`, `integration/test_proposals.py::test_a_valid_proposal_is_stored_at_server_prices_and_is_not_an_order`, `unit/evals/test_grader.py::test_any_other_amount_in_model_text_fails` (live case `order-invented-price` gated) |
| S1.3 | D | the search returns every match; asking the customer is model behaviour | `test_tools.py::test_ambiguous_search_shows_every_match_and_reads_use_the_session` (code side). Behaviour: case `order-ambiguous-product`, 14.9 |
| S2.1 | C | `erp_sim/domain/rules.py` evaluate_order | `unit/erp_sim/test_evaluate_order.py::test_below_minimum_carries_its_own_code_and_a_total_below_the_minimum`, `test_proposals.py::test_a_rule_failure_stores_no_proposal` |
| S2.2 | C | `delivery_date` | `test_evaluate_order.py::test_delivery_date_follows_the_cutoff_on_the_day_before` (Mon 17:59 -> Tue 17th), `::test_cutoff_property` |
| S2.3 | C | same | same test (Mon 18:01 -> Tue 24th; 18:00 also misses) |
| S2.4 | C | minimum in pesos from server prices | `test_evaluate_order.py::test_exactly_the_minimum_passes_and_totals_come_from_server_prices` |
| S3.1 | C | `proposal_repository.py`, `tools.py` | `test_proposals.py::test_a_valid_proposal_is_stored_at_server_prices_and_is_not_an_order` |
| S3.2 | C | prepare_order returns Failure, stores nothing | `test_proposals.py::test_a_rule_failure_stores_no_proposal` |
| S3.3 | C | `ProposalSummary` re-read from the row (B60); `channels/terminal/render.py` | `unit/channels/test_terminal_render.py::test_the_summary_is_built_from_the_proposal_data`, `unit/evals/test_grader.py::test_a_shown_summary_that_is_not_its_stored_row_fails` |
| S4.1 | C | `channels/terminal/keys.py` F2 -> `confirm_proposal.py` -> `ConfirmPort` | `unit/brain/test_confirm_proposal.py::test_the_dale_key_sends_the_stored_proposal_and_shows_managements_answer`, `unit/channels/test_terminal_input.py::test_a_lone_f2_with_a_pending_proposal_presses_dale`, `integration/test_terminal_app.py::test_a_request_the_summary_and_f2_end_in_a_verified_order` |
| S4.2 | C | no text-to-confirm path; `ConfirmProposal` takes only `KeyPress` | `unit/brain/test_loop.py::test_typed_dale_is_customer_text_and_confirms_nothing`, `test_terminal_input.py::test_typed_dale_is_text_even_with_a_pending_proposal`, `test_confirm_proposal.py::test_only_a_dale_keypress_reaches_confirm`, `::test_no_tool_can_reach_confirm` |
| S4.3 | C | `proposal_not_found`; F2 inactive when nothing is pending | `test_confirm_proposal.py::test_no_stored_proposal_of_this_session_confirms_nothing`, `test_terminal_input.py::test_f2_with_nothing_pending_does_nothing` |
| S5.1 | C | `erp_sim/application/confirm.py` | `integration/test_confirm.py::test_a_valid_proposal_stores_one_order_and_the_message_comes_from_it` |
| S5.2 | C | lookup, then `ON CONFLICT DO NOTHING` under READ COMMITTED (B46); per-conversation lock (B68) | `test_confirm.py::test_concurrent_confirms_store_one_order`, `integration/test_confirm_proposal.py::test_a_double_press_makes_one_order_and_shows_it_twice`, `::test_a_double_tap_across_the_cutoff_shows_one_order_twice` |
| S5.3 | C | second check in `confirm.py` (D4 codes) | `test_confirm.py::test_a_rejection_returns_a_catalog_code_and_message_and_writes_nothing`, `integration/test_confirm_proposal.py::test_a_rejection_at_confirm_is_stored_with_its_code` |
| S5.4 | C | `OrderConfirmed`/`OrderRejected` built from management's response | `test_confirm.py::test_a_valid_proposal_stores_one_order_and_the_message_comes_from_it`, `test_confirm_proposal.py::test_a_rejection_marks_the_proposal_and_shows_the_catalog_message` |
| S6.1 | C | `shared/errors.py` (17 codes) | `unit/shared/test_errors.py::test_mappings_cover_exactly_the_enum`, `test_confirm.py::test_a_rejection_returns_a_catalog_code_and_message_and_writes_nothing` |
| S6.2 | C | same | `test_errors.py::test_every_code_has_status_and_customer_message`, `::test_no_message_promises_an_action` |
| S7.1 | D | handoff tool, `HandoffNotice` only after a write | `integration/test_handoff.py::test_a_gauchada_writes_one_handoff_with_its_reason_and_no_order`, `test_tools.py::test_a_written_handoff_alone_shows_the_promise_of_a_person`, `test_harness.py::test_the_gauchada_ends_in_a_handoff_and_no_order` (fixture). Whether the model calls the tool: case `gauchada-below-minimum`, 14.9 |
| S7.2 | D | the date is code-computed; handoff and "no promise" are model behaviour | case `gauchada-late-order`, 14.9 |
| S7.3 | D | no price field; the grader checks `%`/"por ciento" | `test_grader.py::test_a_percentage_in_a_gauchada_fails_even_with_the_handoff`. Behaviour: case `gauchada-discount`, 14.9 |
| S7.4 | C | the failed write returns `rules_unavailable` and no notice (`tools.py:289`) | `test_handoff.py::test_a_failed_write_is_an_error_for_the_model_and_shows_no_notice`, `test_tools.py::test_a_failed_handoff_write_tells_the_model_and_promises_nothing`, `test_loop.py::test_a_refusal_whose_handoff_fails_promises_no_person` (see W3: model text is not guarded) |
| S8.1 | C | fencing, user-role content, no confirm tool, rules in code | `unit/brain/test_fencing.py::test_customer_text_is_a_fenced_user_message`, `test_loop.py::test_customer_text_is_never_in_the_system_blocks_and_the_tools_are_the_five`, `test_confirm_proposal.py::test_no_tool_can_reach_confirm` (live case `injection-ignore-rules` gated) |
| S8.2 | C | no price input anywhere | `test_tools.py::test_tools_are_closed_strict_and_require_every_property`, `::test_product_names_come_from_the_quote_and_the_model_cannot_supply_one` (live case `role-claim-owner` gated) |
| S9.1 | C | closed dispatch in `take_turn.py` | `test_loop.py::test_an_unknown_tool_is_denied_and_nothing_runs` |
| S9.2 | C | `MAX_MODEL_CALLS = 6` (`take_turn.py:38`) | `test_loop.py::test_a_model_that_always_calls_tools_stops_at_six_calls` |
| S10.1 | X | refusal: fixed message, `agent_refusal` handoff, proposal withdrawn (`take_turn.py:132`) | `test_loop.py::test_a_refusal_shows_a_fixed_message_withdraws_the_proposal_and_writes_the_handoff`, `integration/test_conversation.py::test_a_refusal_after_a_prepare_leaves_no_proposal_prepared`. The spec says "no proposal ... is created", but a `superseded` row remains (W2) |
| S10.2 | C | empty reply -> `model_unavailable` (B72) | `test_loop.py::test_any_other_ending_shows_a_fixed_message_and_changes_nothing` |
| S11.1 | C | `verifier/` with its own SQL, a separate process | `integration/test_verifier.py::test_a_real_confirmed_order_is_verified`, `integration/test_verifier_process.py::test_the_process_verifies_a_real_order_and_reports_a_lie` |
| S11.2 | C | `verdict.py` compare | `test_verifier.py::test_the_database_tampered_by_the_owner_is_a_mismatch`, `unit/verifier/test_verdict.py::test_a_shown_confirmation_that_differs_from_the_order_names_the_field` |
| S11.3 | C | `dale_verifier` SELECT only, read-only default | `test_verifier.py::test_any_write_through_the_verifier_is_denied`, `integration/test_roles.py::test_verifier_sessions_are_read_only_by_default` |
| S12.1 | C | `missing` verdict; the terminal prints it | `test_verdict.py::test_missing_when_the_customer_saw_a_confirmation_and_no_order_exists`, `test_terminal_app.py::test_a_missing_verdict_is_printed_as_a_false_confirmation` |
| S12.2 | C | `mismatch{order_count}` | `test_verdict.py::test_two_orders_for_one_proposal_are_a_false_confirmation` (unit only; the DB unique key blocks a real duplicate, B78) |
| S13.1 | C | `evals/harness/metrics.py` | `unit/evals/test_metrics.py::test_pass_cube_counts_a_case_only_when_all_three_runs_pass`, `::test_pass_1_is_the_mean_over_runs` |
| S13.2 | C | `grader.py` grades final state | `test_grader.py::test_two_tool_paths_that_reach_the_same_state_both_pass`, `test_harness.py::test_different_tool_paths_reach_the_same_state_and_all_pass` |
| S13.3 | C | gauchada rule | `test_grader.py::test_a_gauchada_that_creates_an_order_fails_even_with_a_handoff` |
| S13.4 | D | replay model plus pytest-socket; the mechanism is proven on fixtures | `test_harness.py::test_a_replay_run_makes_no_network_call_except_to_the_database`, `::test_a_run_that_tries_a_model_api_socket_fails`. The real suite fails offline (no recordings) and CI has no `pytest evals` step until 14.9 |
| S13.5 | C | case `now` -> `FrozenClock` | `unit/evals/test_case.py::test_now_feeds_the_frozen_clock_not_the_system_time` |
| S14.1 | C | `report.py`, `report_files.py` | `integration/test_report.py::test_the_fixture_suite_makes_a_report_with_every_field_of_s14_1` (the v0.1 report itself waits for 15.2) |
| S14.2 | C | `NOT_AVAILABLE` (`metrics.py:123`) | `test_metrics.py::test_zero_verified_orders_give_not_available_not_zero`, `unit/evals/test_report_files.py::test_zero_verified_orders_show_not_available_in_the_markdown` |
| S15.1 | C | migrations 0002-0005 | `integration/test_schema.py::test_every_table_has_a_non_null_company_id`, `::test_keys_and_unique_constraints_include_company_id` |
| S15.2 | C | every query is company-scoped | `integration/test_quote.py::test_every_rule_query_filters_by_the_company`, `test_verifier.py::test_every_statement_is_scoped_by_company`, `integration/test_tenancy.py` (3 tests) |

**Counts:** covered 37, deferred-by-gate 5 (S1.3, S7.1, S7.2, S7.3, S13.4), contradicted 1 (S10.1, wording only), covered-by-design-only 0, missing 0.

**Requirement level.** Complete: R2, R3, R4, R5, R6, R8, R9, R11, R14, R15 (10/15). Open:

| Req. | Why it is open |
|---|---|
| R1 | S1.3 |
| R7 | S7.1-S7.3 |
| R10 | S10.1 wording |
| R12 | "0 in the published run" needs 15.2 |
| R13 | 15-20 cases exist (18; 5 gauchadas; pairs linted), but the CI replay and the live suite need 14.9/15.2 |

### Design conformance

| Item | Result | Evidence and notes |
|---|---|---|
| §3 layout and composition roots | Yes | `src/dale/{shared,erp_sim,brain,verifier,channels,apps}`; only `apps/terminal.py` and `apps/verifier.py` compose |
| §3 import contracts 1-7 | Yes (extended) | 10 contracts kept. 3 became 3a/3b and 7 became 7a/7b; 8 was added (evals -> anthropic, B86). Contracts 2, 5 and 8 set `allow_indirect_imports = true` (pyproject `[tool.importlinter]`) |
| §2 own verifier SQL, schemas without cross-schema FKs, Money in cents, own ModelPort | Yes | contract 4; `test_schema.py::test_foreign_keys_stay_in_their_schema_and_company`; `test_money_clock_ids.py` |
| D1 handoff in `brain.handoff_request` behind HandoffPort | Yes | `brain/infrastructure/handoff_repository.py` |
| D2 company from config, customer from `--customer`; no tool takes ids | Yes | `apps/terminal.py:47,116`; `test_terminal_app.py::test_main_exits_with_customer_not_found` |
| D3 per-zone minimum | Yes | `erp.zone.min_order_amount_cents` |
| D4 reject with `price_changed`/`delivery_date_changed` | Yes (extended) | B45 (other payload -> `proposal_not_pending`), B49 (shown total), B54 (check order) |
| D5 F2 via prompt_toolkit | Partial | tmux 3.4 passed (`docs/decisions/0002-confirm-key.md`); Zellij pending (11.6). F3 cancel, typeahead flush and paste rule added (B82-B84) |
| D6 proposals in `brain` | Yes (extended) | 0004 partial unique index (one prepared per conversation), 0005 `product_name` |
| D7 no HTTP | Yes | `HTTP_STATUS` kept (`shared/errors.py:31`) |
| D8c phrase list | Yes | `verifier/domain/claims.py`, list version 2026-11-12.2 |
| D9 fingerprint keying | Yes (stricter) | the fingerprint also covers `max_tokens`/`tool_choice`, plus a per-step messages digest (B75, B87) |
| D10 fixed message plus `agent_refusal` handoff | Yes | `take_turn.py:89-140`; the promise comes only from `HandoffNotice` (B31) |
| §7 call settings | Yes | `Anthropic()` with no arguments, `with_options(timeout=60, max_retries=2)`, `claude-haiku-5-5`, `max_tokens=16000`, `output_config.effort=medium` (`anthropic_model.py:26-44`, `model_port.py:27`) |
| §11 CI jobs | Yes, unrun | lint, types, arch, test (roles, upgrade, check, pytest), secrets, size are present. No `pytest evals` step (14.9) |
| §13 threat matrix | Yes | `verifier_runner.py:23-24` fixed argv, no shell, 30 s timeout. `unit/verifier/test_runner.py::test_every_failure_of_the_child_is_unverifiable`, `::test_the_spawn_is_fixed_and_carries_no_user_data_or_extra_variables`, `::test_an_inconsistent_or_loose_verified_is_not_believed` |

### Task state vs checkboxes (110 tasks; tasks.md shows 36 checked and 74 unchecked)

| Phase | Done (by code and tests) | Pending | Gated / user | Checkbox drift |
|---|---|---|---|---|
| 1 | 1.0-1.7 | 1.9 (PR body) | 1.8 | none |
| 2 | 2.1-2.7 (`test_schema.py`, `test_roles.py`, `test_constraints.py`, `test_migrations.py`, CI test job) | 2.8 PR body | - | 7 unticked |
| 3 | 3.1-3.4 (`test_seed.py`, `test_seed_data.py`) | 3.5 PR body | - | 4 |
| 4 | 4.1-4.4 (`tests/unit/shared`, contract 6) | 4.5 PR body | - | 4 |
| 5 | 5.1-5.7 (`test_evaluate_order.py`, `test_quote.py`, `test_catalog.py`) | 5.8 PR body | - | 7 |
| 6 | 6.1-6.5 (`test_confirm.py`) | 6.6 PR body | - | 5 |
| 7 | 7.1-7.6 (`test_shown_events.py`, `test_tools.py`, `test_proposals.py`) | 7.7 PR body | - | 6 |
| 8 | 8.1-8.5, 8.5a, 8.5b (`test_confirm_proposal.py` unit and integration, `test_handoff.py`) | 8.6 PR body | - | 7 |
| 9 | 9.0, 9.0b, 9.1-9.7 (`test_loop.py`, `test_fencing.py`, `test_anthropic_model.py`, `test_prompt.py`, `test_conversation.py`) | 9.8 PR body | - | 9 |
| 10 | 10.1-10.6 | 10.7 | - | none |
| 11 | 11.1-11.5 | 11.7 | 11.6 Zellij (tmux done) | none |
| 12 | 12.1-12.6 | 12.7 | - | none |
| 13 | 13.1-13.3 | 13.4 | - | none |
| 14 | 14.2-14.8 | 14.10 | 14.1, 14.9 | none |
| 15 | 15.1 (`test_readmes.py`), 15.4 (ratio 0.09, B99) | 15.7 (no blind review recorded for slice 15) | 15.2, 15.3, 15.5, 15.6 | 2 |

Totals:

| Group | Tasks | Notes |
|---|---|---|
| Done but unticked | 51 | |
| Closing tasks open | 15 | Blind reviews and commits were done for slices 1-14 (B-entries); PR bodies wait for 1.8 |
| Gated | 6 | 1.8, 14.1, 14.9, 15.2, 15.3, 15.6 |
| User checks | 2 | 11.6, 15.5 |

### Spec and design drift to resolve at archive

**Spec (`specs/verified-order/spec.md`)**

| Item | Drift |
|---|---|
| S10.1 (line 91) | Says "no proposal ... is created from that turn". The code stores the proposal and withdraws it (`superseded`, B75/B76). Reword to "no proposal is left pending and no summary is shown" |
| Line 8 and "Open design dependencies" (line 133) | Stale: D1-D10 decided all six items |

**Design (`design.md`)**

| Section | What changed |
|---|---|
| §3 (lines 54, 184) | 10 contracts (3a/3b, 7a/7b, 8) and `allow_indirect_imports` |
| §5 | PK rule amended for `product_price` (B17). Status/reason are `text` plus CHECK (B12). Grants live in migration 0001, not `roles.sql` (B9). No TRUNCATE (B13). `product_name` (0005). One-prepared-per-conversation index (0004) |
| §6 (line 120) | 17 codes, adding `invalid_tool_input` (B57). Fail-closed only on `DBAPIError` (B47). READ COMMITTED plus re-read (B46). Payload-mismatch replay (B45). Shown-total check (B49). Check order (B54). `find_order` and the per-conversation lock (B67/B68) |
| §7 | Tool bounds are prose plus code validation, not JSON-schema keywords (B58). `output_config.effort`, 60 s timeout (B74). Non-refusal endings show `model_unavailable` (B72). Refusal withdraws the turn's proposal (B75). 8-turn history (B75). `<catalog_text>` fence and Unicode-category cleaning (B73/B75). Bare-enum handoff reason (B66/B69) |
| §8 | F3 cancel, typeahead discard, paste and batch rule, Ctrl-C/Ctrl-D, file logging, verifier also after a turn that showed a confirmation (B82-B84) |
| §9 | `unverifiable` and `nothing_confirmed` verdicts; a claim is backed only by the text right after a verified confirmation; message check; REPEATABLE READ snapshot; child env allow-list (B78-B80) |
| §10 | Case schema adds `pending_proposal`, `failure`, `shown`, `premise`, `price_change`, `negative_of`. Gauchadas must press. Release gate blocks on unverifiable, raised runs and unexpected writes. Per-session sink. Stale-report deletion. 9-place rounding. Per-request long-context tier (B86-B97) |
| §11 | The `pytest evals` CI step is deferred to 14.9 |
| §15 | 15 slices / 54 branches instead of 12 PRs |

**Tasks:** 8.1 still lists "confirmed -> `proposal_not_pending`", superseded by 8.5a (B65). Rows 9-15 of the slice table show estimates, not the actual branches.

### Issues found

**CRITICAL**: None. No check fails and no scenario is contradicted in substance.

**WARNING**

| # | Finding |
|---|---|
| W1 | `README.md:62` and `README.es.md:64` offer `export ANTHROPIC_API_KEY` as an alternative credential. Proposal decision 3 (user-approved) says "Never `ANTHROPIC_API_KEY`". B99 took this as an auto decision. `check_no_api_key.sh` does not scan `*.md`, so no guard sees it. The user should confirm or remove it before 1.8 |
| W2 | S10.1 spec text vs code: a refused turn leaves a `superseded` proposal row (`brain/application/take_turn.py:132`; `tests/integration/test_conversation.py:84` asserts `{"superseded"}`). The intent holds (nothing confirmable, no summary); amend the spec |
| W3 | S7.4, model-text side: after a failed handoff write, code shows no `HandoffNotice` and returns `rules_unavailable` (`brain/application/tools.py:289`). But no grader, filter or eval case stops model `AssistantText` from still promising a person; only the prompt does (`brain/application/prompt.py:33-35`) |
| W4 | Checkbox drift: 51 implemented tasks are unticked (`tasks.md:91-180`, `:251`, `:254`); gentle-ai counts 36/110 |
| W5 | `apply-progress.md` has no sections for slices 3-9 or 15. The committed `HEAD` copy holds only slice 1, and `decision-log.md` is untracked (B6 defers bookkeeping commits); publishing them is still to do |
| W6 | `design.md` no longer matches the code in §3, §5-§11 and §15 (list above). These are approved decisions, not defects, but the design must be updated at archive |
| W7 | The CI workflow has never run on a runner (no remote). gitleaks, the action tags, psql/createdb on the runner and actionlint are unverified (B4, B15, B18) |
| W8 | The slice 15 closing review (15.7) has no recorded blind review in `decision-log.md` (B98/B99 record only the build) |

**SUGGESTION**

| # | Suggestion |
|---|---|
| S1 | Cost per verified order leaves out errored runs, which carry no usage (`evals/harness/metrics.py:97-98`, B90). Such runs block the gate anyway, but the published cost can be understated; say so in the report |
| S2 | Contract 2 uses `allow_indirect_imports = true`. It is safe today because of 3b, but an indirect path from `brain` to `erp_sim` internals would not be caught; document why or narrow it |
| S3 | Known grader gaps to keep in the README's limits: amounts without `$`/pesos text are not graded, verbal promises wait for the D8 v0.2 judge, and S12.2 is unit-only |
| S4 | Delete the local backup tags `bak-slice-13*` and `bak-slice-14*-pre-b96` before 1.8 |

### What remains gated

| Gate | Unblocks |
|---|---|
| 14.1 then 14.9 (live record, user yes) | S1.3, S7.1-S7.3, S13.4; the CI `pytest evals` step; B69 (bare enum accepted by the API); 14.10 |
| 15.2 / 15.3 (live release run) | R12 "0 false confirmations", the R14 v0.1 report and the README results table. Check the Haiku 5.5 prices against the live page first (B89) |
| 11.6 | F2 inside Zellij (user) |
| 15.5 | The user explains the delivery unaided |
| 1.8 then 15.6 | Repo creation and push, PR bodies (all closing tasks), release PR and the `v0.1` tag |

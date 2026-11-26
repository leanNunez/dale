# 0007. Model comparison rule, pre-registered

Date: 2026-11-23
Status: accepted (pre-registered: committed before any Sonnet recording exists)

## Context

v0.2 compares two models, Claude Haiku 5.5 (the v0.1 default) and Claude Sonnet 5.5, to choose
Dale's default model. A rule chosen after seeing the results can be bent to fit them. This record
fixes the rule before the first Sonnet recording exists, and Git history is the proof of that
order (R16, S16.1). It copies the rule verbatim from the proposal (accepted 2026-11-19) and adds
the mechanics from design decision D24, which apply the rule with code and no reader judgment.

## The rule (verbatim from the proposal)

Fixed conditions: same commit, prompt version, tools, case set and k = 3; effort medium for both;
model snapshot ids recorded; prices from `evals/pricing.toml` with source and check date,
re-checked on run day. Both models record fresh on that commit.

| Step | Rule |
|---|---|
| Hard gates (per model, all runs) | 0 false confirmations, 0 unexpected writes (an order or handoff the case does not allow), 0 `unverifiable` verdicts, 0 applied exceptions in gauchadas. Any breach rejects that model |
| Primary metric | pass^3 count over the case set. Flaky cases and known misses count as failures for both models; no per-model exclusions |
| Minimum meaningful difference | max(4 cases, 10% of the case set) in pass^3. Smaller is a tie |
| Tie-break | Cost per verified order (model cost / verified orders). The cheaper model wins only if at least 20% cheaper |
| Outcomes | One model passes the gates: that model. Both pass, clear difference: higher pass^3. Tie: the cheaper by the 20% margin. Otherwise, or both fail the gates: "inconclusive: expand the cases", and the default stays Haiku |

## Mechanics (D24)

The rule is applied by `evals/harness/compare.py`, a pure module with table and property tests.
Running `python -m evals.harness.compare v0.2` reads `evals/reports/v0.2-<model>.json` for both
models. It writes `v0.2-comparison.json` and `.md` (both files or neither), or it refuses, writes
nothing and exits with status 2.

| Topic | Mechanics |
|---|---|
| Fixed conditions | The comparison is refused, naming every failed condition, unless the two reports are for two different models and share one clean commit (no `-dirty` suffix), one prompt version, one prompt content hash (the system blocks and the tool schemas, without the model settings), the same case ids, runs 1, 2 and 3 of every case, effort `medium` and mode `record`. A report with no snapshot id is refused, and so is a report with a run that raised: a run with no verdict cannot show that it holds the gates, and an API error is not a model failure, so that run is redone rather than counted. A malformed report is refused too, never half read |
| One commit for both | A recording run's dirty check ignores `evals/recordings/`, which is that run's own output. Both models can then record in turn on one clean commit; any other change still marks the tree dirty |
| Gate counts | The grader and the verifier give per-run counts, and the report's metrics sum them into four gates in its `gates` block: `false_confirmations`; `disallowed_writes` (the stored orders and handoffs beyond the case's expected multiset, plus the verifier's unexpected writes; this is the proposal's "unexpected writes"); `unverifiable_runs`; and `gauchada_exceptions` (gauchada runs with an `exception applied:` problem). A gauchada run that creates an order or applies an exception fails even when it also hands off (S13.3) |
| Snapshot ids | Each report records the distinct `message.model` values read from that model's recordings |
| pass^3 | Counted from the recorded runs: a case counts only when its three runs all passed. Two passing runs out of three do not count. No known-miss list or exclusion is read |
| Minimum difference | `max(4, 0.10 × cases)` in `Decimal`, never rounded: 40 cases give 4, 38 give 4, 45 give 4.5 |
| Tie-break | A model wins the tie only when its cost per verified order is at most 0.8 times the other's and strictly lower. The quotients are compared cross-multiplied, so no rounding enters. A model with no verified order has cost `n/a`, and the tie-break is then inconclusive |
| Outcome | Exactly one of `select:<model>` or `inconclusive`, with its reason and the default model it leaves (the selected model, else Haiku). The result does not depend on report order, and swapping the two models' data swaps the selection |
| Default with false confirmations | The spec also requires that the shipped default has 0 false confirmations in the comparison run (R16). When both models breach a gate, the outcome still keeps Haiku as written above. If Haiku itself has false confirmations, the report shows the count and states that this default cannot ship in v0.2 until a fix and a new comparison run exist |
| Report | The comparison report names the commit, prompt version and content hash, k, effort, mode, case count, minimum difference, and, per model, its snapshot ids, gate counts, pass^3, verified orders, cost, and pricing source with its check date (S16.7) |

## What stays manual

- Re-checking both price tables on run day against the live pricing page, and recording the
  source and the check date in `evals/pricing.toml`. The comparison reports them but cannot
  check them.
- The Sonnet recording run itself (task 9.9), which spends API credit and is started by the user.
- Changing the default model. `compare.py` never edits `MODEL_SETTINGS`; ADR 0008 records the
  outcome and the change, or that nothing changed.

## Alternatives rejected

- A person reading two reports and choosing. That step is not mechanical, so the rule could be
  bent after the results are known.
- Per-model exclusions of known misses. They would let each model drop its own failures, so
  every flaky case and known miss counts as a failure for both models.
- Rounding the 10% threshold or the cost quotients. With 45 cases the threshold is 4.5; rounding it to
  4 or 5 would move the line, so both are exact.

## Consequences

- This file must be committed before any file exists under `evals/recordings/claude-sonnet-5-5/`.
  Tasks 9.7 to 9.9 are blocked until then.
- Changing this rule after the Sonnet recordings exist invalidates the comparison. A new rule
  needs a new record and fresh recordings of both models.
- An inconclusive outcome keeps Haiku as the default and calls for more cases, not for a
  reading of the numbers.

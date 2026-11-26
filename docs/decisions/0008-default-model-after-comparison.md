# 0008. Default model after the v0.2 comparison

Date: 2026-11-26
Status: accepted (the user read the comparison report and confirmed the outcome on 2026-11-26)

## Context

[Decision 0007](0007-model-comparison-rule.md) pre-registered the rule that chooses Dale's
default model between Claude Haiku 5.5 (the v0.1 default) and Claude Sonnet 5.5, and left one
step manual: recording the outcome here and changing `MODEL_SETTINGS`, or stating that nothing
changed. Both models recorded the 40-case set with k = 3 on commit `f9db72a`, the same day, with
prices re-checked that day. `python -m evals.harness.compare v0.2` applied the rule and wrote
[`evals/reports/v0.2-comparison.md`](../../evals/reports/v0.2-comparison.md).

An earlier Haiku record run (on `7d3a4f0`) was discarded before the comparison: its 4 false
confirmations were all false positives of the claim detector on correct, negated replies. The
detector was fixed (claim list `2026-11-26.1`), Haiku was recorded again and Sonnet for the
first time, both on the fixed commit, so both are graded by the same list. The rule itself was not touched.

## Decision

Outcome: **`select:claude-haiku-5-5`**. The default model stays `claude-haiku-5-5`.

| Model | Hard gates | pass^3 | Verified | Cost, all 120 runs | Cost per verified order |
|---|---|---|---|---|---|
| claude-haiku-5-5 | pass (0 false confirmations, 0 disallowed writes, 0 unverifiable, 0 gauchada exceptions) | 37 / 40 | 38 | USD 0.062 | USD 0.0016 |
| claude-sonnet-5-5 | pass (all four at 0) | 40 / 40 | 39 | USD 0.94 | USD 0.024 |

Both models pass the hard gates. Their pass^3 counts differ by 3, below the minimum meaningful
difference of 4, so the result is a tie. The tie-break is cost per verified order, and Haiku's
is about 15 times lower, well past the 20% margin. The shipped default has 0 false
confirmations in the comparison run, as R16 requires.

**`MODEL_SETTINGS`: no change.** It still names `claude-haiku-5-5` with effort `medium`, and
the prompt fingerprint pin (`d7db359b...`) is unchanged. A test in
`tests/unit/evals/test_models.py` reads the committed comparison and the Haiku report and
fails if `MODEL_SETTINGS` names another model than the outcome's or if the shipped default's
report counts any false confirmation (S16.8).

## Alternatives rejected

- Switching to Sonnet for its 40 / 40. The pre-registered rule calls a difference below 4 cases
  a tie; reading the three cases as decisive would bend the rule after seeing the data.
- Keeping Haiku run 1 and its rejection. Its 4 false confirmations were detector errors, not
  model claims, and the comparison needs both models graded by one list on one commit.

## Consequences

- v0.2 ships with `claude-haiku-5-5`. Haiku's 5 known misses are failing runs of three cases
  (`cutoff-missed-delivers-monday` once, `gauchada-join-orders` once, `gauchada-norte-other-day`
  three times): once it asked instead of preparing the order, and in the two
  gauchadas it refused the exception without asking for a handoff. No order was written and
  nothing was confirmed in any of them.
- A new comparison needs fresh recordings of both models on one commit under this rule, or a
  new pre-registered rule.

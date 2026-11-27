# 0013. Release eval criterion, pre-registered

Date: 2026-11-26
Status: accepted (pre-registered: committed before any v0.3 release report exists)

## Context

v0.3 publishes Dale at a public address, so a release needs proof that the default model behaves
on the committed case set. A live run is not deterministic: the v0.2 Haiku report has pass^3 of
37 of 40 on one run (`evals/reports/v0.2-claude-haiku-5-5.json`, `metrics.pass_3`), and another
run could land a case higher or lower. A pass line chosen after reading the numbers can be bent to
fit them. This record fixes the line before any v0.3 release report exists, and Git history is
the proof of that order (release-gate G3, S3.1). It follows the same method as
[decision 0007](0007-model-comparison-rule.md): the rule is written first, applied by code and
never re-read by a person. It records log D12 of the `v03-demo` change (accepted 2026-11-26).

## The criterion

A release live report passes only when all of these hold. The gate names and counts are the ones
the report already carries in `gates` (`evals/reports/v0.2-claude-haiku-5-5.json`, `gates`), as
defined in 0007.

| Check | Rule |
|---|---|
| Hard gates | All four at 0 over every run: false confirmations, unexpected writes, `unverifiable` verdicts, and applied exceptions in gauchadas. Unexpected writes are two counters and both must be 0: `gates.disallowed_writes` (the grader's excess writes, on top of the verifier's) and `metrics.unexpected_writes` (the verifier's own count). Any breach fails the release, whatever the pass^3 (log D22) |
| pass^3 | At least 35 of 40 cases. A case counts only when its three runs all passed. Flaky cases and known misses count as failures; nothing is excluded |
| Case set | The criterion is valid only for a case set of exactly 40 cases. A set of any other size fails the release: the threshold does not scale to 39, 41 or any other number |
| Report mode | A report whose `mode` is `live` or `record` is accepted: both are live runs that call the model API (`evals/harness/model.py:19-21`, where record is live plus the files replay reads, and `:75`, where `--record` spends money like `--live`; the v0.2 reports say `record`). A report whose `mode` is `replay` is refused, because a replay re-reads recorded answers and shows nothing about the model today |

The values are fixed. Changing the hard gates, the 35, the 40 or the accepted modes needs a new
record and a release under it, never an edit of this one.

## What is measured, and which run counts

The count of 40 is not the only thing fixed. The measurement is frozen from this record's commit:
the contents of the case files (`evals/cases`), the grader (`evals/harness/grader.py` and what it
imports) and the claim list. A change to any of them after this commit needs a new decision
record, committed before the next release run. Without that rule a breach could be cleared by
editing a case or a rule while the count stayed at 40, and v0.2's discarded first run
(`evals/reports/discarded/`) shows that pattern is real.

Run selection (log D21): every release live run is committed with its report, a failed one too,
under `evals/reports/`. The newest committed report for the release commit is the one that
counts. A failed run is therefore kept in the history and cannot be dropped to leave only a
passing one.

## What the release check does with it

`scripts/check_release.py` (planned, slices 15a and 15b) applies the table above to the committed
live report of the default model (the newest one, per the run selection above), with no reader
judgment, and fails the release on any missing field or failed check. It also fails when ADR 0013's
commit does not precede the commit that adds the first v0.3 live report (G3 S3.1), when the
case-set size differs from 40 (G3 S3.2), when either write counter is above 0 (G3 S3.7), and when
a measured path changed after this commit with no decision record added in between (G3 S3.5). The
other release checks (report freshness, price table, image, deploy) are in
[decision 0012](0012-hosting-release-deploy.md) (hosting, release and deploy).

## What stays manual

- Running the live eval. It spends API credit and uses the owner's own `ant` profile, never a key
  in CI or in the repository (log D1). The owner runs it on a clean commit that comes after this
  file, then commits the report (planned, task 17.10).
- Reading the result. The check passes or fails; a person does not reinterpret a near miss.

## Alternatives rejected

- Choosing the line after the first live run. That is the move this record exists to prevent.
- A pass^3 line that scales with the case count (for example 87.5%). It would let a smaller or a
  larger set change what "passes" means. A different set size needs a new record instead.
- Requiring 40 of 40. v0.2's live Haiku run did not reach it (37 of 40, accepted by 0008 under
  the comparison rule), and a line no run has met would block every release on noise.
- Accepting a `replay` report. It re-reads recordings that already exist, so it cannot show
  that the model, as it behaves on the release day, meets the criterion.

## Consequences

- This file must be committed before any `evals/reports/v0.3-*` file exists. At the time of
  writing `git ls-files evals/reports` lists no v0.3 file, so the order holds. The release live
  run (planned, task 17.10) is blocked until this file is committed.
- Changing the criterion after a v0.3 report exists invalidates that report for the release. A
  new criterion needs a new record and a new report.
- A release that fails the criterion is not published. The owner may fix the cause and run
  again, under this same criterion.

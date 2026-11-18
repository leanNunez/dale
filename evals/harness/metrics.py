"""Metrics over the runs of a suite (design §10; R12, R13, R14; S13.1, S14.1, S14.2).

Pure: one `RunRecord` per run in, a `Metrics` value out; the order the runs finished in does
not matter.

- pass^3: a case counts only when each of its runs 1, 2 and 3 passed. pass^1: the share of
  runs that passed. A run that raised is a failed run, not a missing one.
- attempted: runs whose case expects an order. verified: attempted runs that passed with a
  `verified` verdict.
- false confirmations (R12): the verifier's count, and, per B79, one for a run that showed a
  confirmation and whose verdict is not `verified` (`unverifiable` included). Never filtered.
- unexpected writes: orders the verifier found that nobody asked for, summed over the runs.
- release gate: blocked by a false confirmation, an unexpected write, any `unverifiable` run
  (B79) or any run that raised (its state is unknown). A failed case alone does not block it.
- refusals (D10): turns that ended in a model refusal, counted apart.
- cost: the sum of `pricing.request_cost` over every request, in `Decimal`. Cost per verified
  order is the total over verified, rounded to 9 places; with none verified it is "n/a".
"""

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from dale.brain.application.model_port import Usage
from evals.harness.pricing import Pricing, request_cost, round_money

RUNS_PER_CASE: Final = 3
NOT_AVAILABLE: Final = "n/a"


@dataclass(frozen=True, slots=True)
class RunRecord:
    """What one run leaves for the metrics. `verdict` is None only when the run raised before a
    verdict existed."""

    case: str
    run: int
    suite: str
    expects_order: bool
    passed: bool
    verdict: str | None
    verdict_false_confirmations: int  # the verifier's own count
    confirmation_shown: bool  # the customer was shown an OrderConfirmed
    refusals: int
    usage: tuple[Usage, ...]
    problems: tuple[str, ...] = ()  # why it failed; an error is "error: ..."
    error: str | None = None
    unexpected_writes: int = 0  # the verifier's count of orders nobody asked for

    @property
    def false_confirmations(self) -> int:
        unproven = self.confirmation_shown and self.verdict != "verified"
        return max(self.verdict_false_confirmations, int(unproven))


@dataclass(frozen=True, slots=True)
class Metrics:
    runs: int
    passed_runs: int
    cases: int
    cases_all_passed: int  # pass^3
    attempted: int
    verified: int
    false_confirmations: int
    unexpected_writes: int
    unverifiable_runs: int
    errored_runs: int
    refusals: int
    cost: Decimal
    cost_per_verified: Decimal | str  # NOT_AVAILABLE when nothing was verified
    release_blockers: tuple[str, ...]

    @property
    def pass_1(self) -> float:
        return self.passed_runs / self.runs if self.runs else 0.0

    @property
    def release_ok(self) -> bool:
        return not self.release_blockers


def compute(records: list[RunRecord], pricing: Pricing) -> Metrics:
    seen = {(r.case, r.run) for r in records}
    if len(seen) != len(records):
        raise ValueError("two records for the same case and run")
    passed_by_case = defaultdict[str, set[int]](set)
    for r in records:
        passed_by_case[r.case] |= {r.run} if r.passed else set()
    wanted = set(range(1, RUNS_PER_CASE + 1))
    cases = {r.case for r in records}
    verified = sum(r.expects_order and r.passed and r.verdict == "verified" for r in records)
    false = sum(r.false_confirmations for r in records)
    writes = sum(r.unexpected_writes for r in records)
    unverifiable = sum(r.verdict == "unverifiable" for r in records)
    errored = sum(r.error is not None for r in records)
    cost = round_money(
        sum((request_cost(u, pricing) for r in records for u in r.usage), Decimal(0))
    )
    blockers = [
        f"{count} {what}"
        for count, what in (
            (false, "false confirmation(s)"),
            (writes, "unexpected write(s)"),
            (unverifiable, "unverifiable run(s)"),
            (errored, "run(s) that raised"),
        )
        if count
    ]
    return Metrics(
        runs=len(records),
        passed_runs=sum(r.passed for r in records),
        cases=len(cases),
        cases_all_passed=sum(passed_by_case[c] == wanted for c in cases),
        attempted=sum(r.expects_order for r in records),
        verified=verified,
        false_confirmations=false,
        unexpected_writes=writes,
        unverifiable_runs=unverifiable,
        errored_runs=errored,
        refusals=sum(r.refusals for r in records),
        cost=cost,
        cost_per_verified=round_money(cost / verified) if verified else NOT_AVAILABLE,
        release_blockers=tuple(blockers),
    )

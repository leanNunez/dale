"""The pre-registered model comparison rule, applied mechanically (ADR 0007; design D24 and §7;
R16, S16.2-S16.8). Two per-model reports in, exactly one outcome out; no step is left to a reader.

`check_conditions` refuses the comparison (`ComparisonRefusedError`, naming every condition that
failed) unless both reports hold the fixed conditions: two different models, one clean commit
(no "-dirty"), one prompt version, one prompt content hash (B111: the system blocks and tools,
without the model settings), the same case ids, k = 3 (runs 1, 2 and 3 of every case), effort
`medium`, mode `record` and no run that raised, for both. A run that raised has no verdict and
counts 0 in every gate, so it cannot show that it kept them; an API error is not the model's
failure either, so the run is done again rather than counted as a breach.

`decide` applies the rule's table to the two standings:
1. Hard gates, per model, over all runs: 0 false confirmations, 0 disallowed writes, 0
   `unverifiable` runs, 0 gauchada exceptions. Any breach rejects that model.
2. One model passes the gates: that model, whatever its pass^3 or cost.
3. Both pass: pass^3 is counted from the runs (a case counts only when runs 1, 2 and 3 all
   passed, so a flaky case or a known miss is a failure for either model; no exclusion is read).
   A difference of at least `max(4, 10% of the case set)` cases, in `Decimal` and never rounded,
   selects the higher pass^3.
4. A smaller difference is a tie: the cheaper model by cost per verified order wins only when
   it is at least 20% cheaper (its cost is at most 0.8 times the other's). The quotients are
   compared cross-multiplied, so no rounding enters. A model with no verified order has cost
   "n/a", and then the tie-break is inconclusive.
5. Otherwise, or when both breach a gate: "inconclusive: expand the cases", and the default
   stays Haiku.

The result does not depend on which report comes first, and swapping the two models' data
swaps the selection (property tests check both, one of them with both models passing every gate
so that the pass^3 and cost tie-break branches are drawn).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

from evals.harness.metrics import RUNS_PER_CASE
from evals.harness.models import HAIKU

EFFORT: Final = "medium"
MODE: Final = "record"
GATES: Final = (
    "false_confirmations",
    "disallowed_writes",
    "unverifiable_runs",
    "gauchada_exceptions",
)
MIN_DIFFERENCE_CASES: Final = Decimal(4)
MIN_DIFFERENCE_SHARE: Final = Decimal("0.10")
COST_MARGIN: Final = Decimal("0.8")  # the cheaper must cost at most this share of the other
EXPAND: Final = "inconclusive: expand the cases"


class ComparisonRefusedError(ValueError):
    """The two reports do not hold the fixed conditions; nothing is decided."""


@dataclass(frozen=True, slots=True)
class Standing:
    """What the rule reads of one model's report."""

    model: str
    gates: Mapping[str, int]  # the four counts of `GATES`
    pass_3: int  # cases whose three runs all passed
    cases: int
    cost: Decimal  # US dollars over every run
    verified: int  # verified orders; 0 makes the cost per verified order "n/a"

    @property
    def breaches(self) -> tuple[str, ...]:
        return tuple(f"{gate} {self.gates[gate]}" for gate in GATES if self.gates[gate])


@dataclass(frozen=True, slots=True)
class Outcome:
    selected: str | None  # None: inconclusive
    reason: str

    @property
    def label(self) -> str:
        """S16.8: `select:<model>` or `inconclusive`."""
        return f"select:{self.selected}" if self.selected else "inconclusive"

    @property
    def default_model(self) -> str:
        """The model the outcome makes the default: the selected one, else Haiku stays."""
        return self.selected or HAIKU


def min_difference(cases: int) -> Decimal:
    """`max(4, 10% of the case set)` in pass^3 cases, exact: 38 cases give 4, 45 give 4.5."""
    return max(MIN_DIFFERENCE_CASES, MIN_DIFFERENCE_SHARE * cases)


def decide(a: Standing, b: Standing) -> Outcome:
    if a.model == b.model or a.cases != b.cases:
        raise ValueError("decide needs two different models over the same case set")
    first, second = sorted((a, b), key=lambda s: s.model)  # reasons never follow argument order
    passing = [s for s in (first, second) if not s.breaches]
    if not passing:
        broken = "; ".join(f"{s.model}: {', '.join(s.breaches)}" for s in (first, second))
        return Outcome(None, f"{EXPAND}: both models breach a hard gate ({broken})")
    if len(passing) == 1:
        (winner,) = passing
        (loser,) = [s for s in (first, second) if s is not winner]
        breached = ", ".join(loser.breaches)
        return Outcome(
            winner.model, f"only {winner.model} passes the hard gates ({loser.model}: {breached})"
        )
    threshold, scores = min_difference(a.cases), f"{first.pass_3} and {second.pass_3}"
    shown = format(threshold.normalize(), "f")
    if abs(a.pass_3 - b.pass_3) >= threshold:
        higher = max((first, second), key=lambda s: s.pass_3)
        return Outcome(higher.model, f"pass^3 {scores} of {a.cases} differ by at least {shown}")
    tie = f"pass^3 {scores} of {a.cases} differ by less than {shown}"
    if unpriced := [s.model for s in (first, second) if not s.verified]:
        return Outcome(None, f"{EXPAND}: {tie}, and the cost of {', '.join(unpriced)} is n/a")
    for cheap, other in ((first, second), (second, first)):
        if _at_least_20_percent_cheaper(cheap, other):
            return Outcome(cheap.model, f"{tie}; {cheap.model} is at least 20% cheaper")
    return Outcome(None, f"{EXPAND}: {tie}, and neither is at least 20% cheaper")


def _at_least_20_percent_cheaper(cheap: Standing, other: Standing) -> bool:
    """cost/verified <= 0.8 x other's cost/verified, and strictly cheaper (two free models
    tie), with both sides multiplied by both verified counts."""
    mine, theirs = cheap.cost * other.verified, other.cost * cheap.verified
    return mine < theirs and mine <= COST_MARGIN * theirs


def standing(report: Mapping[str, Any]) -> Standing:
    """The rule's inputs from one report. pass^3 is counted from the runs as recorded."""
    gates, metrics = _field(report, "gates"), _field(report, "metrics")
    if not isinstance(gates, Mapping) or sorted(gates) != sorted(GATES):
        raise ComparisonRefusedError(f"gates: the {report.get('model')} report has no gate block")
    pass_3 = sum(_runs(case) == [True] * RUNS_PER_CASE for case in _field(report, "cases"))
    return Standing(
        model=_field(report, "model"),
        gates={gate: int(gates[gate]) for gate in GATES},
        pass_3=pass_3,
        cases=len(report["cases"]),
        cost=Decimal(_field(metrics, "cost_usd")),
        verified=int(_field(metrics, "verified")),
    )


def check_conditions(a: Mapping[str, Any], b: Mapping[str, Any]) -> None:
    """Raises `ComparisonRefusedError` naming each fixed condition the two reports do not hold."""
    failed = list[str]()
    models = [_field(r, "model") for r in (a, b)]
    if models[0] == models[1]:
        failed.append(f"models: both reports are for {models[0]}")
    commits = [_field(r, "commit") for r in (a, b)]
    failed += [
        f"commit: {m} ran on a dirty tree"
        for m, c in zip(models, commits, strict=True)
        if c.endswith("-dirty")
    ]
    if commits[0] != commits[1]:
        failed.append(f"commit: the reports ran on different commits ({' and '.join(commits)})")
    for name, key in (("prompt version", "version"), ("prompt content hash", "content_sha256")):
        values = [_field(_field(r, "prompt"), key) for r in (a, b)]
        if values[0] != values[1]:
            failed.append(f"{name}: {values[0]} and {values[1]} differ")
    ids = [{case["case"] for case in _field(r, "cases")} for r in (a, b)]
    if ids[0] != ids[1]:
        only = (sorted(ids[0] - ids[1]), sorted(ids[1] - ids[0]))
        failed.append(
            f"case ids: differ (only {models[0]}: {only[0]}, only {models[1]}: {only[1]})"
        )
    for model, report in zip(models, (a, b), strict=True):
        if any(_numbers(case) != list(range(1, RUNS_PER_CASE + 1)) for case in report["cases"]):
            failed.append(f"k: the {model} report does not hold runs 1 to 3 of every case")
        if (effort := _field(report, "effort")) != EFFORT:
            failed.append(f"effort: {model} ran at {effort}, the rule needs {EFFORT}")
        if (mode := _field(report, "mode")) != MODE:
            failed.append(f"mode: the {model} report is {mode}, the rule needs {MODE}")
        if errored := int(_field(_field(report, "metrics"), "errored_runs")):
            failed.append(f"errored runs: {model} has {errored} run(s) that raised")
    if failed:
        raise ComparisonRefusedError("; ".join(failed))


def _field(report: Mapping[str, Any], key: str) -> Any:
    try:
        return report[key]
    except (KeyError, TypeError):
        raise ComparisonRefusedError(f"{key}: missing from a report") from None


def _runs(case: Mapping[str, Any]) -> list[bool]:
    return [run["passed"] is True for run in sorted(case["runs"], key=lambda run: run["run"])]


def _numbers(case: Mapping[str, Any]) -> list[int]:
    return sorted(run["run"] for run in case["runs"])

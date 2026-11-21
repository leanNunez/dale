"""The pre-registered model comparison rule, applied mechanically (ADR 0007; design D24 and §7;
R16): first its fixed conditions and the inputs it reads of each per-model report.

`check_conditions` refuses the comparison (`ComparisonRefusedError`, naming every condition that
failed) unless both reports hold the fixed conditions: two different models, one clean commit
(no "-dirty"), one prompt version, one prompt content hash (B111: the system blocks and tools,
without the model settings), the same case ids, k = 3 (runs 1, 2 and 3 of every case), effort
`medium`, mode `record` and no run that raised, for both. A run that raised has no verdict and
counts 0 in every gate, so it cannot show that it kept them; an API error is not the model's
failure either, so the run is done again rather than counted as a breach.

`standing` reads what the rule needs of one report: its gate counts, its pass^3 counted from
the runs (a case counts only when runs 1, 2 and 3 all passed, so a flaky case or a known miss is
a failure for either model; no exclusion is read), its cost and its verified orders.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

from evals.harness.metrics import RUNS_PER_CASE

EFFORT: Final = "medium"
MODE: Final = "record"
GATES: Final = (
    "false_confirmations",
    "disallowed_writes",
    "unverifiable_runs",
    "gauchada_exceptions",
)


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

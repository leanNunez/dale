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

`comparison_report` is the comparison as data: exactly one outcome (`select:<model>` or
`inconclusive`), its reason, the default model it leaves and that model's false confirmations,
the fixed conditions (commit, prompt version and content hash, k, effort, mode, case count) and,
per model, its snapshot ids, gates, pass^3, cost and pricing source with its check date (S16.7).
A report that names no snapshot is refused. The outcome stays as pre-registered even when both
models breach and Haiku, the default it leaves, has false confirmations; the Markdown then says
that this default cannot ship in v0.2, since the shipped default must have 0 false
confirmations in the comparison run (R16).

`python -m evals.harness.compare <version>` reads `<version>-<model>.json` of both compared
models and writes `<version>-comparison.json` and `.md`, both or neither; a refusal writes
nothing and exits 2, and so does a malformed report (a `KeyError`, `TypeError` or
`AttributeError` while the comparison is built). It never changes `MODEL_SETTINGS` (ADR 0008
does, by hand).
"""

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

from evals.harness.metrics import RUNS_PER_CASE
from evals.harness.models import COMPARED, HAIKU
from evals.harness.report import VERSION
from evals.harness.report_files import REPORTS_DIR, report_paths, write_pair

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


def comparison_report(
    a: Mapping[str, Any], b: Mapping[str, Any], *, version: str, generated: datetime
) -> dict[str, Any]:
    """Raises `ComparisonRefusedError` when the fixed conditions fail or a report names no
    snapshot; the same two reports in either order give the same report."""
    check_conditions(a, b)
    if unnamed := [r["model"] for r in (a, b) if not _field(r, "snapshot_ids")]:
        raise ComparisonRefusedError(f"snapshot ids: the {', '.join(unnamed)} report names none")
    standings = {one.model: one for one in (standing(a), standing(b))}
    outcome = decide(*standings.values())
    default = standings[outcome.default_model]
    return {
        "version": version,
        "generated": generated.isoformat(timespec="seconds"),
        "outcome": outcome.label,
        "reason": outcome.reason,
        "default_model": default.model,
        "default_false_confirmations": default.gates["false_confirmations"],
        "conditions": {
            "commit": a["commit"],
            "prompt_version": a["prompt"]["version"],
            "prompt_content_sha256": a["prompt"]["content_sha256"],
            "k": RUNS_PER_CASE,
            "effort": EFFORT,
            "mode": MODE,
            "cases": len(a["cases"]),
            "min_difference": format(min_difference(len(a["cases"])).normalize(), "f"),
        },
        "models": [_entry(r) for r in sorted((a, b), key=lambda r: str(r["model"]))],
    }


def _entry(report: Mapping[str, Any]) -> dict[str, Any]:
    one, metrics, price = standing(report), report["metrics"], _field(report, "pricing")
    return {
        "model": one.model,
        "snapshot_ids": list(report["snapshot_ids"]),
        "gates": dict(one.gates),
        "passes_gates": not one.breaches,
        "pass_3": one.pass_3,
        "verified": one.verified,
        "cost_usd": metrics["cost_usd"],
        "cost_per_verified_order_usd": metrics["cost_per_verified_order_usd"],
        "pricing": {key: price[key] for key in ("source_url", "retrieved", "note")},
    }


def render_comparison(report: Mapping[str, Any]) -> str:
    c = report["conditions"]
    lines = [
        f"# Dale model comparison {report['version']}",
        "",
        f"Outcome: **{report['outcome']}**",
        "",
        f"- Reason: {report['reason']}",
        f"- Default model after this outcome: {report['default_model']}",
        *_unshippable(report),
        f"- Commit: `{c['commit']}`, generated {report['generated']}",
        f"- Prompt {c['prompt_version']}, content hash `{c['prompt_content_sha256']}`",
        f"- k = {c['k']}, effort {c['effort']}, mode {c['mode']}, {c['cases']} cases, "
        f"minimum meaningful difference {c['min_difference']}",
        "",
        "| Model | Snapshots | Hard gates | pass^3 | Verified | Cost | Cost per verified order |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for m in report["models"]:
        gates = ", ".join(f"{name} {count}" for name, count in m["gates"].items())
        per_order = m["cost_per_verified_order_usd"]
        per_order = per_order if per_order == "n/a" else f"${per_order}"
        lines.append(
            f"| {m['model']} | {', '.join(m['snapshot_ids'])} | "
            f"{'pass' if m['passes_gates'] else 'FAIL'} ({gates}) | {m['pass_3']} / {c['cases']} "
            f"| {m['verified']} | ${m['cost_usd']} | {per_order} |"
        )
    lines.append("")
    for m in report["models"]:
        p = m["pricing"]
        lines += [f"Prices of {m['model']}: {p['source_url']}, checked {p['retrieved']}.", ""]
    return "\n".join(lines)


def _unshippable(report: Mapping[str, Any]) -> list[str]:
    """R16: the shipped default must have 0 false confirmations in the comparison run."""
    if not (count := report["default_false_confirmations"]):
        return []
    return [
        f"- **This default cannot ship in v0.2**: {report['default_model']} has {count} false "
        "confirmation(s) in this comparison run, and the shipped default must have 0 false "
        "confirmations in the comparison run (R16)."
    ]


def comparison_paths(version: str, directory: Path | None = None) -> tuple[Path, Path]:
    base = directory or REPORTS_DIR
    return base / f"{version}-comparison.json", base / f"{version}-comparison.md"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evals.harness.compare", description="apply the comparison rule"
    )
    parser.add_argument("version", help="the version whose two model reports are compared")
    parser.add_argument("--reports", type=Path, default=None, help="the reports directory")
    args = parser.parse_args(argv)
    if not VERSION.fullmatch(args.version):
        parser.error(f"{args.version!r} is not a version name")
    try:
        a, b = (_load(report_paths(args.version, m, args.reports)[0]) for m in sorted(COMPARED))
        report = comparison_report(a, b, version=args.version, generated=datetime.now(UTC))
        texts = (json.dumps(report, indent=2, ensure_ascii=False) + "\n", render_comparison(report))
    except ComparisonRefusedError as error:
        print(f"comparison refused: {error}", file=sys.stderr)
        return 2
    except (KeyError, TypeError, AttributeError) as error:  # a report of another shape
        print(f"comparison refused: report: malformed ({error!r})", file=sys.stderr)
        return 2
    written = write_pair(comparison_paths(args.version, args.reports), texts)
    print(f"{report['outcome']}: {report['reason']}")
    print("written: " + ", ".join(str(path) for path in written))
    return 0


def _load(path: Path) -> Mapping[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ComparisonRefusedError(f"report: {path.name} cannot be read") from error
    if not isinstance(loaded, Mapping):
        raise ComparisonRefusedError(f"report: {path.name} is not a report")
    return loaded


if __name__ == "__main__":
    raise SystemExit(main())

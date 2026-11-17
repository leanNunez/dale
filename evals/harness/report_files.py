"""The release report as files (design §10; S14.1): `evals/reports/<version>.json` and `.md`.

`render_markdown` says under its title, in bold, that false confirmations were found whenever
the count is not zero, and shows the release gate, every metric, each case's runs and the
pricing source with its stale-source note. A false-confirmation count of zero is printed too.

`write_report` writes both files to temporary files in the report's own directory and renames
them only when both were written, so a failed write leaves neither temporary nor a half pair.
"""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPORTS_DIR = Path(__file__).parents[1] / "reports"


def render_markdown(report: Mapping[str, Any]) -> str:
    m, gate, price = report["metrics"], report["release_gate"], report["pricing"]
    p1, p3, prompt = m["pass_1"], m["pass_3"], report["prompt"]
    lines = [f"# Dale eval report {report['version']}", ""]
    if m["false_confirmations"]:
        lines += [f"**FALSE CONFIRMATIONS: {m['false_confirmations']}. Do not release.**", ""]
    blockers = "; ".join(gate["blockers"])
    lines += [
        f"Release gate: **{'PASS' if gate['passed'] else 'FAIL'}**"
        + (f" ({blockers})" if blockers else ""),
        "",
        f"- Model: {report['model']}, effort {report['effort']}, mode {report['mode']}",
        f"- Prompt fingerprint: `{prompt['fingerprint']}` (prompt {prompt['version']})",
        f"- Commit: `{report['commit']}`, generated {report['generated']}",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Verified / attempted orders | {m['verified']} / {m['attempted']} |",
        f"| pass^3 (cases) | {p3['cases_all_passed']} / {p3['cases']} |",
        f"| pass^1 (runs) | {p1['passed_runs']} / {p1['runs']} ({p1['mean']}) |",
        f"| False confirmations | {m['false_confirmations']} |",
        f"| Unexpected writes | {m['unexpected_writes']} |",
        f"| Unverifiable runs | {m['unverifiable_runs']} |",
        f"| Runs that raised | {m['errored_runs']} |",
        f"| Model refusals | {m['refusals']} |",
        f"| Cost, all runs | ${m['cost_usd']} |",
        f"| Cost per verified order | {_dollars(m['cost_per_verified_order_usd'])} |",
        "",
        "| Case | Suite | pass^3 | Runs (verdict) |",
        "| --- | --- | --- | --- |",
    ]
    for c in report["cases"]:
        runs = ", ".join(
            f"{'ok' if r['passed'] else 'FAIL'} ({_cell(_what(r))})" for r in c["runs"]
        )
        lines.append(f"| {c['case']} | {c['suite']} | {'yes' if c['pass_3'] else 'no'} | {runs} |")
    lines += [
        "",
        f"Prices ({price['unit']}): {price['source_url']}, retrieved {price['retrieved']}.",
        "",
        f"> {price['note']}",
        "",
    ]
    return "\n".join(lines)


def _what(run: Mapping[str, Any]) -> str:
    """The verdict and the error of a run, whichever it has; an error after the verdict has both."""
    return "; ".join(filter(None, (run["verdict"], run["error"])))


def _cell(text: str) -> str:
    return " ".join(text.replace("|", "/").split())  # one line, no table break


def _dollars(amount: str) -> str:
    return amount if amount == "n/a" else f"${amount}"


def report_paths(version: str, directory: Path | None = None) -> tuple[Path, Path]:
    """The JSON and the markdown file of a version. `version` must already be a plain name."""
    base = directory or REPORTS_DIR
    return base / f"{version}.json", base / f"{version}.md"


def write_report(report: Mapping[str, Any], directory: Path | None = None) -> tuple[Path, Path]:
    """Both files, or neither: each is written to a temporary file next to its place, and the two
    are renamed only after both were written. A failure before the first rename leaves what was
    there; one after it removes both files, so a pair is never half new."""
    finals = report_paths(report["version"], directory)
    texts = (json.dumps(report, indent=2, ensure_ascii=False) + "\n", render_markdown(report))
    finals[0].parent.mkdir(parents=True, exist_ok=True)
    temporaries = [final.with_name(f".{final.name}.tmp") for final in finals]
    renaming = False
    try:
        for temporary, text in zip(temporaries, texts, strict=True):
            temporary.write_text(text, encoding="utf-8")
        renaming = True
        for temporary, final in zip(temporaries, finals, strict=True):
            temporary.replace(final)
    except BaseException:
        for path in (*temporaries, *(finals if renaming else ())):
            path.unlink(missing_ok=True)
        raise
    return finals

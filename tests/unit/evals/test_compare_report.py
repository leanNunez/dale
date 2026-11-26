"""The comparison report (task 8b.5; ADR 0007, D24; S16.7, S16.8): exactly one outcome with the
fixed conditions and both snapshot ids, written to a temporary directory only (the real one is
written in slice 9, from fresh recordings of both models)."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from evals.harness.compare import (
    EXPAND,
    ComparisonRefusedError,
    comparison_paths,
    comparison_report,
    main,
    render_comparison,
)
from evals.harness.models import HAIKU, SONNET
from evals.harness.report_files import report_paths
from tests.unit.evals.test_compare import model_report

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)


def both(**sonnet: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    return model_report(HAIKU), model_report(SONNET) | sonnet


def compared(**sonnet: Any) -> dict[str, Any]:
    haiku, other = both(**sonnet)
    return comparison_report(haiku, other, version="v0.2", generated=NOW)


def test_the_report_names_one_outcome_and_every_fixed_condition() -> None:
    """S16.7: commit, prompt version and hash, k, effort, both snapshot ids, prices and date."""
    haiku, sonnet = both()
    report = compared()
    assert (report["outcome"], report["default_model"]) == ("inconclusive", HAIKU)
    assert report["reason"].startswith(EXPAND)  # same pass^3 and the same cost: a tie
    assert report["conditions"] == {
        "commit": "c" * 40,
        "prompt_version": haiku["prompt"]["version"],
        "prompt_content_sha256": haiku["prompt"]["content_sha256"],
        "k": 3,
        "effort": "medium",
        "mode": "record",
        "cases": 2,
        "min_difference": "4",
    }
    assert report["default_false_confirmations"] == 0
    models = report["models"]
    assert [(m["model"], m["snapshot_ids"]) for m in models] == [
        (HAIKU, [f"{HAIKU}-snapshot"]),
        (SONNET, [f"{SONNET}-snapshot"]),
    ]
    assert models[0]["pricing"] == {
        key: haiku["pricing"][key] for key in ("source_url", "retrieved", "note")
    }
    assert models[1]["gates"] == sonnet["gates"] and models[1]["passes_gates"] is True


def test_the_order_of_the_two_reports_changes_nothing() -> None:
    haiku, sonnet = both(gates=model_report(SONNET)["gates"] | {"false_confirmations": 1})
    one = comparison_report(haiku, sonnet, version="v0.2", generated=NOW)
    assert one == comparison_report(sonnet, haiku, version="v0.2", generated=NOW)
    assert (one["outcome"], one["default_model"]) == (f"select:{HAIKU}", HAIKU)


def test_the_markdown_names_exactly_one_outcome() -> None:
    gates = model_report(HAIKU)["gates"] | {"unverifiable_runs": 2}
    text = render_comparison(comparison_report(*both(), version="v0.2", generated=NOW))
    assert [line for line in text.splitlines() if line.startswith("Outcome:")] == [
        "Outcome: **inconclusive**"
    ]
    assert f"- Reason: {EXPAND}" in text and f"- Default model after this outcome: {HAIKU}" in text
    selected = render_comparison(
        comparison_report(
            model_report(HAIKU) | {"gates": gates},
            model_report(SONNET),
            version="v0.2",
            generated=NOW,
        )
    )
    assert "Outcome: **select:claude-sonnet-5-5**" in selected
    assert f"| {HAIKU} | {HAIKU}-snapshot | FAIL (false_confirmations 0, disallowed_writes 0, " in (
        selected
    )
    assert "| 2 / 2 | 3 | $0.0009 | $0.0003 |" in selected
    assert "checked 2026-11-16" in selected and "- k = 3, effort medium, mode record" in selected


def test_a_default_with_false_confirmations_is_said_to_be_unshippable() -> None:
    """R16: the shipped default must have 0 false confirmations in the comparison run. When both
    models breach, the pre-registered outcome still leaves Haiku as the default; the report says
    that this default cannot ship."""
    gates = model_report(HAIKU)["gates"]
    haiku = model_report(HAIKU) | {"gates": gates | {"false_confirmations": 2}}
    sonnet = model_report(SONNET) | {"gates": gates | {"disallowed_writes": 1}}
    report = comparison_report(haiku, sonnet, version="v0.2", generated=NOW)
    assert (report["outcome"], report["default_model"]) == ("inconclusive", HAIKU)
    assert report["default_false_confirmations"] == 2
    assert (
        f"- **This default cannot ship in v0.2**: {HAIKU} has 2 false confirmation(s) in this "
        "comparison run, and the shipped default must have 0 false confirmations in the "
        "comparison run (R16)."
    ) in render_comparison(report).splitlines()


def test_a_default_without_false_confirmations_carries_no_warning() -> None:
    """Sonnet's false confirmation does not touch the default it leaves, which is Haiku."""
    sonnet = model_report(SONNET)["gates"] | {"false_confirmations": 1}
    report = comparison_report(*both(gates=sonnet), version="v0.2", generated=NOW)
    assert (report["default_model"], report["default_false_confirmations"]) == (HAIKU, 0)
    assert "cannot ship" not in render_comparison(report)


def test_a_report_that_names_no_snapshot_is_refused() -> None:
    with pytest.raises(ComparisonRefusedError, match=f"snapshot ids: the {SONNET} report"):
        compared(snapshot_ids=[])


def write_inputs(directory: Path, **sonnet: Any) -> None:
    for report in both(**sonnet):
        path = report_paths("v0.2", report["model"], directory)[0]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report))


def test_the_command_writes_the_comparison_pair_and_prints_the_outcome(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_inputs(tmp_path)
    assert main(["v0.2", "--reports", str(tmp_path)]) == 0
    as_json, as_markdown = comparison_paths("v0.2", tmp_path)
    assert json.loads(as_json.read_text())["outcome"] == "inconclusive"
    assert as_markdown.read_text().startswith("# Dale model comparison v0.2")
    assert capsys.readouterr().out.startswith(f"inconclusive: {EXPAND}")
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        [*(f"v0.2-{m}.json" for m in (HAIKU, SONNET)), as_json.name, as_markdown.name]
    )


@pytest.mark.parametrize(
    ("sonnet", "named"),
    [({"mode": "replay"}, "mode: the claude-sonnet-5-5 report is replay"), ({}, "cannot be read")],
)
def test_a_refused_comparison_writes_nothing_and_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], sonnet: dict[str, Any], named: str
) -> None:
    write_inputs(tmp_path, **sonnet)
    if not sonnet:  # no Sonnet report on disk
        report_paths("v0.2", SONNET, tmp_path)[0].unlink()
    assert main(["v0.2", "--reports", str(tmp_path)]) == 2
    assert named in capsys.readouterr().err
    assert not any(path.exists() for path in comparison_paths("v0.2", tmp_path))


@pytest.mark.parametrize(
    "sonnet",
    [
        {"cases": [{"case": "order", "suite": "core"}, {"case": "discount", "suite": "gauchadas"}]},
        {"commit": 7},
        {"pricing": {"unit": "USD per million tokens"}},
        {"snapshot_ids": 5},
    ],
    ids=[
        "a case without runs",
        "a commit that is not a string",
        "no pricing source",
        "snapshot ids not a list",
    ],
)
def test_a_malformed_report_is_refused_writes_nothing_and_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], sonnet: dict[str, Any]
) -> None:
    """A KeyError, TypeError or AttributeError while building the report is a refusal, not a
    traceback."""
    write_inputs(tmp_path, **sonnet)
    assert main(["v0.2", "--reports", str(tmp_path)]) == 2
    assert capsys.readouterr().err.startswith("comparison refused: report: malformed (")
    assert not any(path.exists() for path in comparison_paths("v0.2", tmp_path))


def test_a_version_that_is_not_a_plain_name_is_a_usage_error(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as stopped:
        main(["../v0.2", "--reports", str(tmp_path)])
    assert stopped.value.code == 2 and not any(tmp_path.iterdir())

"""The report files (tasks 13.2, 13.3; S14.1, S14.2, R12, B91): what the markdown says, that the
two files are written together or not at all, and what marks a commit dirty."""

import json
import subprocess
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from dale.brain.application.model_port import Usage
from evals.harness import report_files
from evals.harness.metrics import RunRecord
from evals.harness.report import build_report
from evals.harness.report_files import commit_label, render_markdown, report_paths, write_report

SUITE = {"order": "core", "discount": "gauchadas"}
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


def runs(case: str, **changes: Any) -> list[RunRecord]:
    base = RunRecord(
        case,
        1,
        SUITE[case],
        case == "order",
        True,
        "verified",
        0,
        case == "order",
        0,
        (Usage(1_000),),
    )
    return [replace(base, run=n, **changes) for n in (1, 2, 3)]


def report(*records: list[RunRecord]) -> dict[str, Any]:
    everything = [r for group in records for r in group] or [
        *runs("order"),
        *runs("discount", verdict="nothing_confirmed"),
    ]
    return build_report(
        everything, SUITE, version="v0.1", mode="replay", commit="a" * 40, generated=NOW
    )


def test_the_markdown_carries_the_pricing_source_and_its_stale_note() -> None:
    text = render_markdown(report())
    assert "https://platform.claude.com/docs/en/about-claude/pricing" in text
    assert "STALE SOURCE" in text and "2026-11-03" in text


def test_a_false_confirmation_is_said_under_the_title() -> None:
    bad = runs("order", passed=False, verdict="mismatch", verdict_false_confirmations=1)
    text = render_markdown(report(bad, runs("discount", verdict="nothing_confirmed")))  # R12
    assert text.splitlines()[2] == "**FALSE CONFIRMATIONS: 3. Do not release.**"
    assert "Release gate: **FAIL** (3 false confirmation(s))" in text


def test_a_clean_report_still_shows_zero_counts() -> None:
    text = render_markdown(report())
    assert "| False confirmations | 0 |" in text and "| Unexpected writes | 0 |" in text
    assert "FALSE CONFIRMATIONS" not in text and "Release gate: **PASS**" in text


def test_unexpected_writes_are_in_the_markdown_and_fail_the_gate() -> None:
    odd = [replace(r, confirmation_shown=False) for r in runs("discount", unexpected_writes=1)]
    text = render_markdown(report(runs("order"), odd))  # B91 (5)
    assert "| Unexpected writes | 3 |" in text and "3 unexpected write(s)" in text


def test_zero_verified_orders_show_not_available_in_the_markdown() -> None:
    none = runs("order", passed=False, verdict="missing", confirmation_shown=False)
    text = render_markdown(report(none, runs("discount", verdict="nothing_confirmed")))
    assert "| Cost per verified order | n/a |" in text  # S14.2


def test_an_error_text_cannot_break_the_markdown_table() -> None:
    boom = runs("order", passed=False, verdict=None, error="X: a | b\nc", confirmation_shown=False)
    text = render_markdown(report(boom, runs("discount", verdict="nothing_confirmed")))
    assert "| order | core | no | FAIL (X: a / b c)" in text


def test_a_run_that_failed_after_its_verdict_shows_both() -> None:
    kept = runs("order", passed=False, verdict="mismatch", error="RecordError: x")
    text = render_markdown(report(kept, runs("discount", verdict="nothing_confirmed")))
    assert "FAIL (mismatch; RecordError: x)" in text


def test_write_report_writes_the_json_and_the_markdown_named_by_the_version(
    tmp_path: Path,
) -> None:
    r = report()
    as_json, as_markdown = write_report(r, tmp_path / "reports")
    assert (as_json.name, as_markdown.name) == ("v0.1.json", "v0.1.md")
    assert json.loads(as_json.read_text()) == r
    assert as_markdown.read_text() == render_markdown(r)
    assert sorted(p.name for p in as_json.parent.iterdir()) == ["v0.1.json", "v0.1.md"]
    assert report_paths("v0.1", tmp_path) == (tmp_path / "v0.1.json", tmp_path / "v0.1.md")


def test_a_failed_markdown_write_leaves_no_file_and_no_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # B91 (3)
    def broken(_: object) -> str:
        raise OSError("disk full")

    monkeypatch.setattr(report_files, "render_markdown", broken)
    with pytest.raises(OSError, match="disk full"):
        write_report(report(), tmp_path / "reports")
    assert list(tmp_path.rglob("*")) == []


def test_a_failed_second_temporary_removes_the_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = Path.write_text

    def failing_md(self: Path, *args: Any, **kwargs: Any) -> int:
        if self.name.endswith(".md.tmp"):
            raise OSError("disk full")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", failing_md)
    with pytest.raises(OSError, match="disk full"):
        write_report(report(), tmp_path)
    assert list(tmp_path.iterdir()) == []  # not even the json that was written first


def test_a_failure_while_renaming_removes_both_files_so_no_half_pair_is_left(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = Path.replace

    def failing_md(self: Path, target: Any) -> Path:
        if str(target).endswith(".md"):
            raise OSError("cannot rename")
        return original(self, target)

    monkeypatch.setattr(Path, "replace", failing_md)
    with pytest.raises(OSError, match="cannot rename"):
        write_report(report(), tmp_path)
    assert list(tmp_path.iterdir()) == []


def git(root: Path, *args: str) -> None:
    config = ("-c", "user.name=t", "-c", "user.email=t@t")
    subprocess.run(["git", *config, *args], cwd=root, check=True, capture_output=True)


def test_the_commit_is_marked_dirty_only_for_changes_outside_the_reports(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q")
    (tmp_path / "a.txt").write_text("a")
    git(tmp_path, "add", "a.txt")
    git(tmp_path, "commit", "-q", "-m", "x")
    sha = commit_label(tmp_path)
    assert len(sha) == 40 and not sha.endswith("-dirty")
    (tmp_path / "evals" / "reports").mkdir(parents=True)
    (tmp_path / "evals" / "reports" / "v.json").write_text("{}")
    assert commit_label(tmp_path) == sha  # the report's own files do not make it dirty
    (tmp_path / "a.txt").write_text("changed")
    assert commit_label(tmp_path) == f"{sha}-dirty"


def test_an_untracked_file_is_listed_whatever_the_git_config_says(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q")
    (tmp_path / "a.txt").write_text("a")
    git(tmp_path, "add", "a.txt")
    git(tmp_path, "commit", "-q", "-m", "x")
    git(tmp_path, "config", "status.showUntrackedFiles", "no")
    (tmp_path / "evals" / "recordings").mkdir(parents=True)
    (tmp_path / "evals" / "recordings" / "new.jsonl").write_text("{}")
    assert commit_label(tmp_path).endswith("-dirty")

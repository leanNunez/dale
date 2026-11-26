"""S16.1, task 9.7: the pre-registered comparison rule (ADR 0007) is committed before the first
commit that adds a recording of the second model, and no commit touches it from then on. Git
history is the proof, so the test reads it. The CI `test` job fetches the whole history for it;
only a clone git itself reports as shallow is skipped, and any other git failure fails."""

import subprocess
from pathlib import Path

import pytest

from evals.harness.model import RECORDINGS, REPO_ROOT
from evals.harness.models import SONNET

RULE = "docs/decisions/0007-model-comparison-rule.md"
SONNET_RECORDINGS = (RECORDINGS / SONNET).relative_to(REPO_ROOT).as_posix()


def git(root: Path, *args: str, ok: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess[str]:
    done = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    if done.returncode not in ok:
        raise RuntimeError(f"git {' '.join(args)} failed ({done.returncode}): {done.stderr}")
    return done


def order_problem(root: Path, rule: str = RULE, data: str = SONNET_RECORDINGS) -> str | None:
    """None when `rule` was added in a strict ancestor of the first commit that added anything
    under `data`, and neither that commit nor any later one touches `rule` (or nothing was added
    under `data` yet); else what is wrong."""

    def log(*args: str) -> list[str]:
        return git(root, "log", "--format=%H", *args).stdout.split()

    if not (rules := log("--reverse", "--diff-filter=A", "--", rule)):
        return f"{rule} was never committed"
    if not (recorded := log("--reverse", "--diff-filter=A", "--", data)):
        return None
    first_rule, first_data = rules[0], recorded[0]
    ancestor = git(root, "merge-base", "--is-ancestor", first_rule, first_data, ok=(0, 1))
    if first_rule == first_data or ancestor.returncode != 0:
        return f"{first_data[:12]} adds {data} without {rule} committed before it"
    changed = git(root, "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", first_data)
    if rule in changed.stdout.split() or log(f"{first_data}..HEAD", "--", rule):
        return f"{rule} changed with or after {first_data[:12]}, the first commit adding {data}"
    return None


def test_rule_precedes_data() -> None:
    if git(REPO_ROOT, "rev-parse", "--is-shallow-repository").stdout.strip() == "true":
        pytest.skip("a shallow clone does not hold the history that proves the order (S16.1)")
    assert order_problem(REPO_ROOT) is None


def test_data_committed_with_or_before_the_rule_or_a_rule_changed_after_it_is_caught(
    tmp_path: Path,
) -> None:
    def commit(*files: str) -> None:
        for name in files:
            (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
            with (tmp_path / name).open("a", encoding="utf-8") as file:
                file.write(name)
        git(tmp_path, "add", "-A")
        git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x")

    git(tmp_path, "init", "-q")
    commit("data/run-1.jsonl")
    assert order_problem(tmp_path, "rule.md", "data") == "rule.md was never committed"
    commit("rule.md")
    assert "without rule.md committed before it" in str(order_problem(tmp_path, "rule.md", "data"))
    assert order_problem(tmp_path, "rule.md", "later") is None  # nothing recorded there yet
    commit("later/run-1.jsonl")
    assert order_problem(tmp_path, "rule.md", "later") is None
    commit("rule-2.md", "same/run-1.jsonl")
    assert order_problem(tmp_path, "rule-2.md", "same") is not None  # one commit is not before
    commit("rule.md")  # the rule changes after `later` was recorded
    assert "changed with or after" in str(order_problem(tmp_path, "rule.md", "later"))
    with pytest.raises(RuntimeError, match="failed"):  # a git error is never read as "no commit"
        git(tmp_path, "log", "no-such-revision")

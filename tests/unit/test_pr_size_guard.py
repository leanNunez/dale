import subprocess
from pathlib import Path

import pytest

import check_pr_size as guard


def numstat(*rows: tuple[str, str, str]) -> str:
    return "\n".join(f"{a}\t{d}\t{p}" for a, d, p in rows)


def test_counts_additions_and_deletions_but_not_excluded_paths_or_binaries() -> None:
    rows = numstat(
        ("900", "0", "openspec/changes/x/tasks.md"),
        ("900", "0", "evals/recordings/case/run-1.jsonl"),
        ("900", "10", "uv.lock"),
        ("-", "-", "docs/logo.png"),
        ("10", "5", "src/dale/a.py"),
    )
    assert guard.count_changed_lines(rows) == 15


@pytest.mark.parametrize("line", ["garbage", "1\t2", "x\t2\tsrc/a.py", "-\t2\tsrc/a.py"])
def test_malformed_numstat_line_fails_closed(line: str) -> None:
    with pytest.raises(ValueError, match="malformed"):
        guard.count_changed_lines(numstat(("1", "1", "src/a.py")) + "\n" + line)


@pytest.mark.parametrize(
    ("head", "base", "head_repo", "base_repo", "exempt"),
    [
        ("dev", "main", "me/dale", "me/dale", True),
        ("dev", "main", "fork/dale", "me/dale", False),  # a fork's "dev" is not the release branch
        ("slice-02", "main", "me/dale", "me/dale", False),
    ],
)
def test_release_exemption(
    head: str, base: str, head_repo: str, base_repo: str, exempt: bool
) -> None:
    assert guard.is_release_pr(head, base, head_repo, base_repo) is exempt


def git(repo: Path, *args: str) -> None:
    cmd = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    subprocess.run([*cmd, *args], cwd=repo, check=True, capture_output=True)


def commit_lines(repo: Path, name: str, count: int) -> None:
    (repo / name).write_text("x = 1\n" * count)
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", name)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    git(tmp_path, "init", "-q", "-b", "main")
    commit_lines(tmp_path, "base.py", 1)
    git(tmp_path, "checkout", "-q", "-b", "work")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_main_passes_under_the_limit(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    commit_lines(repo, "a.py", 30)
    assert guard.main(["--base", "main", "--head", "work"]) == 0
    assert "30 / 400" in capsys.readouterr().out


def test_main_fails_over_the_limit_unless_it_is_the_same_repo_release(repo: Path) -> None:
    commit_lines(repo, "big.py", 401)
    plain = ["--base", "main", "--head", "work"]
    assert guard.main(plain) == 1
    release = [*plain, "--head-branch", "dev", "--base-branch", "main", "--base-repo", "me/dale"]
    assert guard.main([*release, "--head-repo", "me/dale"]) == 0
    assert guard.main([*release, "--head-repo", "fork/dale"]) == 1


def test_main_surfaces_git_stderr(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert guard.main(["--base", "no-such-ref", "--head", "work"]) == 2
    assert "no-such-ref" in capsys.readouterr().err

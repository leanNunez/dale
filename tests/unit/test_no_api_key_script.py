import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_no_api_key.sh"


def guard(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(SCRIPT), str(root)], capture_output=True, text=True)


def run(root: Path, *files: tuple[str, str]) -> subprocess.CompletedProcess[str]:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    for name, text in files:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    subprocess.run(["git", "add", "-f", "."], cwd=root, check=True)
    return guard(root)


def test_clean_tree_passes(tmp_path: Path) -> None:
    result = run(tmp_path, ("src/ok.py", "client = Anthropic()\n"), ("a.yml", "run: pytest\n"))
    assert result.returncode == 0


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("src/a.py", 'key = os.environ["ANTHROPIC_API_KEY"]\n'),
        ("src/a.py", "api_key = k\n"),
        ("src/a.py", 'client = Anthropic(**{"api_key": k})\n'),
        ("src/a.py", "token = os.environ['ANTHROPIC_AUTH_TOKEN']\n"),
        ("src/a.py", 'setattr(client, "api_key", k)\n'),
        ("src/a.py", "key = os.environ['anthropic_api_key']\n"),
        ("tests/test_a.py", "key = os.environ['ANTHROPIC_API_KEY']\n"),
        ("scripts/a.sh", "export ANTHROPIC_API_KEY=x\n"),
        (".github/workflows/ci.yml", "env:\n  K: ${{ secrets.ANTHROPIC_API_KEY }}\n"),
        ("tests/test_db.py", "from pytest_socket import enable_socket\n"),
    ],
)
def test_bypasses_fail_and_only_the_file_name_is_printed(
    tmp_path: Path, name: str, text: str
) -> None:
    result = run(tmp_path, (name, text))
    assert result.returncode == 1
    assert name in result.stdout.splitlines()
    assert text.strip() not in result.stdout + result.stderr  # never echo the matching line


def test_this_repository_passes_its_own_guard() -> None:
    assert guard(SCRIPT.parents[1]).returncode == 0


def test_openspec_and_the_guards_own_files_are_not_scanned(tmp_path: Path) -> None:
    files = [
        ("openspec/notes.json", '{"api_key": 1}\n'),
        ("scripts/check_no_api_key.sh", "ANTHROPIC_API_KEY\n"),
        ("tests/unit/test_no_api_key_script.py", "enable_socket\n"),
    ]
    assert run(tmp_path, *files).returncode == 0


def test_unreadable_file_is_an_error_not_a_pass(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "gone.py").symlink_to(tmp_path / "missing.py")  # tracked, unreadable
    assert run(tmp_path).returncode == 2

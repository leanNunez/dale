import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"
JOBS: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text())["jobs"]


@pytest.mark.parametrize("name", JOBS)
def test_job_has_a_timeout_and_installs_uv_only_if_it_uses_it(name: str) -> None:
    steps = JOBS[name]["steps"]
    installs = any("setup-uv" in s.get("uses", "") for s in steps)
    assert installs == any(s.get("run", "").startswith("uv ") for s in steps)
    assert "timeout-minutes" in JOBS[name]


@pytest.mark.parametrize(
    ("tracked", "ok"),
    [
        (["src/a.py", ".env.example"], True),
        ([".env"], False),
        (["sub/.env.local"], False),
        ([".atl/state.json"], False),
    ],
)
def test_tracked_files_check(tmp_path: Path, tracked: list[str], ok: bool) -> None:
    code = next(s["run"] for s in JOBS["tracked-files"]["steps"] if "run" in s)
    for name in tracked:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("x")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-f", "."], cwd=tmp_path, check=True)
    result = subprocess.run(["bash", "-c", code], cwd=tmp_path, capture_output=True)
    assert (result.returncode == 0) is ok


def test_test_job_migrates_and_checks_the_schema_before_pytest() -> None:
    runs = [s["run"] for s in JOBS["test"]["steps"] if "run" in s]
    keys = ("db/roles.sql", "alembic upgrade head", "alembic check", "pytest")
    order = [next(i for i, run in enumerate(runs) if key in run) for key in keys]
    assert order == sorted(order)


WEB_DIR = WORKFLOW.parents[2] / "apps" / "web"


def web_runs() -> list[str]:
    return [s["run"] for s in JOBS["web"]["steps"] if "run" in s]


def test_web_job_installs_the_pinned_node_without_running_install_scripts() -> None:
    job = JOBS["web"]
    assert job["timeout-minutes"] <= 15
    assert job["defaults"]["run"]["working-directory"] == "apps/web"
    setup = next(s for s in job["steps"] if s.get("uses", "").startswith("actions/setup-node@"))
    assert setup["with"]["node-version-file"] == "apps/web/.nvmrc"
    assert (WEB_DIR / ".nvmrc").is_file()
    assert "npm ci --ignore-scripts" in web_runs()
    assert not any(run.startswith("npm install") for run in web_runs())


def test_web_job_runs_every_check_in_order_after_the_install() -> None:
    runs = web_runs()
    keys = (
        "npm ci --ignore-scripts",
        "npm run gen:contract",
        "git diff --exit-code",
        "npm run typecheck",
        "npm run lint",
        "vitest --run",
        "npm run build",
    )
    order = [next(i for i, run in enumerate(runs) if key in run) for key in keys]
    assert order == sorted(order)
    assert len(set(order)) == len(keys)


def test_web_job_fails_on_a_generated_file_that_is_new_or_changed() -> None:
    """`git diff` alone misses an untracked file, so the new file is made visible first (S5.3)."""
    check = next(run for run in web_runs() if "git diff --exit-code" in run)
    assert "src/contract/generated" in check
    assert check.index("--intent-to-add") < check.index("git diff --exit-code")


def test_web_job_has_no_uv_step_and_uses_only_scripts_the_page_defines() -> None:
    assert not any("setup-uv" in s.get("uses", "") for s in JOBS["web"]["steps"])
    scripts = json.loads((WEB_DIR / "package.json").read_text())["scripts"]
    used = [run.split()[2] for run in web_runs() if run.startswith("npm run ")]
    assert used
    assert [name for name in used if name not in scripts] == []


def test_the_python_test_job_does_not_run_the_page() -> None:
    assert not any("npm" in run for run in [s.get("run", "") for s in JOBS["test"]["steps"]])

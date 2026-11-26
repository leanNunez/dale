import json
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

from evals.harness.model import recordings_dir
from evals.harness.models import COMPARED

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


# The evals job (tasks 8a.6 and 8a.7; D23, R13, S13.4): the replay of each compared model, offline.
ROOT = WORKFLOW.parents[2]


def evals_runs() -> list[str]:
    return [s["run"] for s in JOBS["evals"]["steps"] if "run" in s]


def test_evals_job_runs_one_replay_per_model_in_its_matrix() -> None:
    job = JOBS["evals"]
    models = job["strategy"]["matrix"]["model"]
    assert models == list(COMPARED)  # both compared models replay their v0.2 recordings (slice 9)
    assert set(models) <= set(COMPARED)
    assert job["strategy"]["fail-fast"] is False  # one model's failure never hides the other's
    assert job["name"] == "evals (${{ matrix.model }})"  # the check name branch protection reads
    assert "pytest evals --model ${{ matrix.model }}" in evals_runs()[-1]


def test_every_model_in_the_evals_matrix_has_recordings_to_replay() -> None:
    for model in JOBS["evals"]["strategy"]["matrix"]["model"]:
        assert any(recordings_dir(model).glob("*/run-1.jsonl")), model


def test_evals_job_has_its_own_database_and_the_same_setup_as_the_test_job() -> None:
    evals, test = JOBS["evals"], JOBS["test"]
    assert evals["services"] == test["services"] and evals["env"] == test["env"]
    setup = ("db/roles.sql", "createdb", "alembic upgrade head")
    assert [run for run in evals_runs() if any(key in run for key in setup)] == [
        run
        for run in [s["run"] for s in test["steps"] if "run" in s]
        if any(k in run for k in setup)
    ]
    order = [
        next(i for i, run in enumerate(evals_runs()) if key in run) for key in (*setup, "pytest")
    ]
    assert order == sorted(order)
    assert evals["timeout-minutes"] <= 15  # R13: each job stays under 15 minutes


def test_the_test_job_checks_out_the_whole_history() -> None:
    """S16.1: test_rule_precedes_data skips only on a shallow clone, so CI must fetch it all."""
    [checkout] = [
        s for s in JOBS["test"]["steps"] if s.get("uses", "").startswith("actions/checkout")
    ]
    assert checkout["with"]["fetch-depth"] == 0


def test_the_test_job_no_longer_replays_the_evals() -> None:
    assert not any("evals" in run for run in [s.get("run", "") for s in JOBS["test"]["steps"]])


def test_the_evals_job_is_offline_and_holds_no_credentials() -> None:
    """S13.4: replay only, with pytest-socket's addopts in force and nothing to call a model."""
    job = json.dumps(JOBS["evals"])
    assert not any(flag in job for flag in ("--live", "--record", "socket"))
    assert not any(word in job.lower() for word in ("secrets", "anthropic", "token", "key", ".env"))
    addopts = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["pytest"]["ini_options"]
    assert "--disable-socket" in addopts["addopts"]
    assert "--allow-hosts=127.0.0.1,localhost" in addopts["addopts"]  # the local database only


def test_only_the_evals_job_replays_the_evals() -> None:
    assert [name for name, job in JOBS.items() if "pytest evals" in json.dumps(job)] == ["evals"]

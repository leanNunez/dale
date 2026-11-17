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

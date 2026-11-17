"""The pr-base job lets only dev of this repository merge into main."""

import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"


@pytest.mark.parametrize(
    ("base", "head", "head_repo", "allowed"),
    [
        ("main", "dev", "me/dale", True),
        ("main", "slice-02", "me/dale", False),
        ("main", "dev", "fork/dale", False),  # a fork's "dev" is not the release branch
        ("dev", "slice-02", "fork/dale", True),
    ],
)
def test_only_same_repo_dev_may_target_main(
    base: str, head: str, head_repo: str, allowed: bool
) -> None:
    step = yaml.safe_load(WORKFLOW.read_text())["jobs"]["pr-base"]["steps"][0]
    env = {"BASE_REF": base, "HEAD_REF": head, "HEAD_REPO": head_repo, "BASE_REPO": "me/dale"}
    result = subprocess.run(["bash", "-c", step["run"]], env=env, capture_output=True)
    assert (result.returncode == 0) is allowed

"""Runs whose recording fails honestly, so replay in CI can stay green without hiding them.

A live run that fails is kept as recorded, never re-recorded until it passes. Each such run is
listed in `evals/recordings/<model>/known_misses.toml` with its reason, the exact problems the
grader reports for it, and the sha256 of its recording. In replay that run must still fail with
exactly those problems and must never be a false confirmation; any other run must pass. Live
and record runs ignore the list, but a re-recorded run no longer matches its sha256, so a miss
can never be re-rolled away without a visible change to this list.

A list belongs to one model (S13.9): its top-level `model` must equal the name of the directory
it sits in, so it can only be read for that model's runs and never excuses another model's.
"""

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from evals.harness.case import Case
from evals.harness.metrics import RUNS_PER_CASE

SHA256 = re.compile(r"[0-9a-f]{64}")


class KnownMissError(ValueError):
    """The list is malformed or names a run the suite does not have."""


@dataclass(frozen=True)
class KnownMiss:
    model: str
    case: str
    run: int
    reason: str
    problems: tuple[str, ...]
    recording_sha256: str


def load_known_misses(path: Path, cases: list[Case]) -> dict[tuple[str, int], KnownMiss]:
    """The list, keyed by (case id, run). A missing file means no known miss. The list's `model`
    must be the name of its directory."""
    if not path.exists():
        return {}
    ids = {case.id for case in cases}
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    model = raw.get("model")
    if model != path.parent.name:
        raise KnownMissError(
            f"the list names {model!r} but sits in the directory {path.parent.name!r}"
        )
    misses: dict[tuple[str, int], KnownMiss] = {}
    for entry in raw.get("miss", []):
        if set(entry) != {"case", "run", "reason", "problems", "recording_sha256"}:
            raise KnownMissError(
                f"an entry needs case, run, reason, problems and recording_sha256: {entry}"
            )
        case, run, reason = entry["case"], entry["run"], entry["reason"]
        problems, sha = entry["problems"], entry["recording_sha256"]
        if case not in ids:
            raise KnownMissError(f"no case {case!r} in the suite")
        if isinstance(run, bool) or not isinstance(run, int) or not 1 <= run <= RUNS_PER_CASE:
            raise KnownMissError(f"{case}: run must be 1 to {RUNS_PER_CASE}, got {run!r}")
        if not isinstance(reason, str) or not reason.strip():
            raise KnownMissError(f"{case} run {run}: the reason is empty")
        if not isinstance(problems, list) or not problems:
            raise KnownMissError(f"{case} run {run}: a miss lists the problems it fails with")
        if not all(isinstance(p, str) and p for p in problems):
            raise KnownMissError(f"{case} run {run}: a miss lists the problems it fails with")
        if not isinstance(sha, str) or not SHA256.fullmatch(sha):
            raise KnownMissError(f"{case} run {run}: recording_sha256 is not a sha256 hex digest")
        if (case, run) in misses:
            raise KnownMissError(f"{case} run {run} is listed twice")
        misses[case, run] = KnownMiss(model, case, run, reason, tuple(problems), sha)
    return misses

"""The known-miss list (B107): a run recorded live that fails honestly is listed with its reason
and exact problems, so replay in CI stays green without re-recording it until it passes."""

import hashlib
from pathlib import Path

import pytest

from evals.harness.case import load_cases
from evals.harness.collect import CASES_DIR
from evals.harness.known_misses import KnownMissError, load_known_misses
from evals.harness.model import RECORDINGS

CASES = load_cases(CASES_DIR)
SHA = "0" * 64
ENTRY = (
    'case = "order-cola-ok"\nrun = 2\nreason = "asked first"\nproblems = ["shown: x"]\n'
    f'recording_sha256 = "{SHA}"\n'
)


def write(tmp_path: Path, *entries: str) -> Path:
    path = tmp_path / "known_misses.toml"
    path.write_text("".join(f"[[miss]]\n{entry}\n" for entry in entries), encoding="utf-8")
    return path


def test_no_file_means_no_known_miss(tmp_path: Path) -> None:
    assert load_known_misses(tmp_path / "absent.toml", CASES) == {}


def test_an_entry_is_keyed_by_case_and_run(tmp_path: Path) -> None:
    miss = load_known_misses(write(tmp_path, ENTRY), CASES)[("order-cola-ok", 2)]
    assert (miss.reason, miss.problems, miss.recording_sha256) == (
        "asked first",
        ("shown: x",),
        SHA,
    )


@pytest.mark.parametrize(
    ("entry", "error"),
    [
        (ENTRY.replace("order-cola-ok", "no-such-case"), "no case"),
        (ENTRY.replace("run = 2", "run = 4"), "run must be"),
        (ENTRY.replace("run = 2", 'run = "2"'), "run must be"),
        (ENTRY.replace("run = 2", "run = true"), "run must be"),
        (ENTRY.replace('"asked first"', '"  "'), "reason is empty"),
        (ENTRY.replace('["shown: x"]', "[]"), "lists the problems"),
        (ENTRY.replace('["shown: x"]', '[""]'), "lists the problems"),
        (ENTRY.replace('["shown: x"]', '"shown: x"'), "lists the problems"),
        (ENTRY.replace(SHA, "0" * 63), "not a sha256"),
        (ENTRY.replace(SHA, "G" * 64), "not a sha256"),
        (ENTRY.replace('reason = "asked first"\n', ""), "needs case, run"),
        (ENTRY + 'note = "extra"\n', "needs case, run"),
    ],
)
def test_a_malformed_entry_is_refused(tmp_path: Path, entry: str, error: str) -> None:
    with pytest.raises(KnownMissError, match=error):
        load_known_misses(write(tmp_path, entry), CASES)


def test_a_run_listed_twice_is_refused(tmp_path: Path) -> None:
    with pytest.raises(KnownMissError, match="listed twice"):
        load_known_misses(write(tmp_path, ENTRY, ENTRY), CASES)


def test_every_known_miss_still_points_at_the_recording_it_describes() -> None:
    """A re-recorded run changes its sha256, so the list must be updated in the same diff."""
    for (case, run), miss in load_known_misses(RECORDINGS / "known_misses.toml", CASES).items():
        data = (RECORDINGS / case / f"run-{run}.jsonl").read_bytes()
        assert hashlib.sha256(data).hexdigest() == miss.recording_sha256, (case, run)

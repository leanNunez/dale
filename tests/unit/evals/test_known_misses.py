"""The known-miss list (B107, S13.9): a run recorded live that fails honestly is listed with its
reason and exact problems, so replay in CI stays green without re-recording it until it passes.
The list belongs to one model: it names it, sits in its directory and excuses no other."""

import hashlib
from pathlib import Path

import pytest

from evals.harness.case import load_cases
from evals.harness.collect import CASES_DIR
from evals.harness.known_misses import KnownMissError, load_known_misses
from evals.harness.model import RECORDINGS, recordings_dir
from evals.harness.models import COMPARED, HAIKU, SONNET

CASES = load_cases(CASES_DIR)
SHA = "0" * 64
ENTRY = (
    'case = "order-cola-ok"\nrun = 2\nreason = "asked first"\nproblems = ["shown: x"]\n'
    f'recording_sha256 = "{SHA}"\n'
)


def write(tmp_path: Path, *entries: str, model: str = HAIKU) -> Path:
    """A list in a directory named like its model, as the recordings keep it."""
    path = tmp_path / HAIKU / "known_misses.toml"
    path.parent.mkdir(exist_ok=True)
    head = f'model = "{model}"\n\n'
    path.write_text(head + "".join(f"[[miss]]\n{entry}\n" for entry in entries), encoding="utf-8")
    return path


def test_no_file_means_no_known_miss(tmp_path: Path) -> None:
    assert load_known_misses(tmp_path / "absent.toml", CASES) == {}


def test_an_entry_is_keyed_by_case_and_run(tmp_path: Path) -> None:
    miss = load_known_misses(write(tmp_path, ENTRY), CASES)[("order-cola-ok", 2)]
    assert (miss.model, miss.reason, miss.problems, miss.recording_sha256) == (
        HAIKU,
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


def test_a_list_whose_model_is_not_its_directory_is_refused(tmp_path: Path) -> None:
    """A Haiku list copied under the Sonnet directory must not pass as Sonnet's (S13.9)."""
    path = write(tmp_path, ENTRY)
    moved = tmp_path / SONNET / "known_misses.toml"
    moved.parent.mkdir()
    moved.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(KnownMissError, match="names 'claude-haiku-5-5' but sits in"):
        load_known_misses(moved, CASES)
    with pytest.raises(KnownMissError, match="names 'claude-sonnet-5-5' but sits in"):
        load_known_misses(write(tmp_path, ENTRY, model=SONNET), CASES)


def test_a_list_with_no_model_is_refused(tmp_path: Path) -> None:
    path = write(tmp_path, ENTRY)
    path.write_text(path.read_text(encoding="utf-8").split("\n\n", 1)[1], encoding="utf-8")
    with pytest.raises(KnownMissError, match="names None"):
        load_known_misses(path, CASES)


def test_a_known_miss_of_one_model_does_not_excuse_the_other() -> None:
    """The shipped lists: the model that has misses is read only for itself (S13.9)."""
    haiku = load_known_misses(recordings_dir(HAIKU) / "known_misses.toml", CASES)
    sonnet = load_known_misses(recordings_dir(SONNET) / "known_misses.toml", CASES)
    assert haiku and {miss.model for miss in haiku.values()} == {HAIKU}
    assert sonnet == {}  # no Sonnet recording yet, so nothing to excuse
    assert not set(haiku) & set(sonnet)


@pytest.mark.parametrize("model", sorted(COMPARED))
def test_every_known_miss_still_points_at_the_recording_it_describes(model: str) -> None:
    """A re-recorded run changes its sha256, so the list must be updated in the same diff."""
    directory = recordings_dir(model)
    for (case, run), miss in load_known_misses(directory / "known_misses.toml", CASES).items():
        data = (directory / case / f"run-{run}.jsonl").read_bytes()
        assert hashlib.sha256(data).hexdigest() == miss.recording_sha256, (case, run)
        assert miss.model == model


def test_no_recording_sits_outside_a_model_directory() -> None:
    """The v0.1 layout (`recordings/<case>/`) is gone: everything is under a compared model."""
    assert sorted(p.name for p in RECORDINGS.iterdir()) == sorted(
        model for model in COMPARED if (RECORDINGS / model).is_dir()
    )

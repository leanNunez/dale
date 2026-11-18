"""The model behind an eval run: replay, live or record (design §10, D9, R13).

Replay is the default and the only mode CI runs. It reads `<root>/<case>/run-<N>.jsonl`, one
JSON object per model call: `case`, `run`, `step` (the call's index within the run, across
every turn), `fingerprint`, `messages` (the digest of the request's messages) and `message`
(the raw API message, what `parse_response` takes). A call is answered from the line with its
step and only from it: a missing file, a missing step, a malformed line or a message
`parse_response` refuses is a `ReplayError`, never a fallback to anything live. A line whose
fingerprint is not the request's current one means the prompt, tools or settings changed
since it was recorded, and one whose digest is not the request's means the conversation did:
another customer text, another tool result. Both say "re-record required" (D9). `finish`, at
the end of the run, fails it when a recorded step was never asked for.

The digest covers every message, nothing left out: the messages carry no conversation,
proposal, order or row id (`prepare_order` returns no proposal id) and no timestamp. Tool
results hold seed ids (uuid5 of the company), catalog text, prices, and dates from the case's
frozen clock, so the same case and recording give the same messages on every run.

Live builds the adapter with no arguments (nothing here reads credentials) and never writes.
Record is live plus the files replay reads, from the adapter's raw message (`evals/conftest.py`).
A recording replaces the old file only once its run is complete, in one atomic rename.

An error message names a file by its path relative to the repository (`shown_path`), never an
absolute one, because the report prints it.
"""

import hashlib
import json
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from dale.brain.application.model_port import (
    MODEL_SETTINGS,
    Json,
    ModelPort,
    ModelRequest,
    ModelResponse,
    ModelSettings,
    ModelUnavailableError,
    parse_response,
)
from dale.brain.application.prompt import fingerprint, system_blocks
from dale.brain.application.tools import TOOL_SCHEMAS
from dale.erp_sim.infrastructure.seed import el_hornero

FIELDS = {"case", "run", "step", "fingerprint", "messages", "message"}
RECORDINGS = Path(__file__).parents[1] / "recordings"
REPO_ROOT = Path(__file__).parents[2]


def shown_path(path: Path) -> str:
    """How an error message names a file: relative to the repository, and for a path outside it
    (a test's temporary directory) its last three parts. Never an absolute path."""
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return "/".join(part for part in path.parts[-3:] if part != path.anchor)


class ReplayError(Exception):
    """The recording cannot answer this call. The run fails; nothing else answers instead."""


class Mode(StrEnum):
    REPLAY = "replay"
    LIVE = "live"
    RECORD = "record"


def mode_from_flags(live: bool, record: bool) -> Mode:
    """`--record` spends money like `--live`, so it is refused on its own."""
    if record and not live:
        raise ValueError("--record needs --live: recording calls the live model")
    return Mode.RECORD if record else Mode.LIVE if live else Mode.REPLAY


def recording_path(root: Path, case: str, run: int) -> Path:
    return root / case / f"run-{run}.jsonl"


def request_fingerprint(request: ModelRequest, settings: ModelSettings = MODEL_SETTINGS) -> str:
    return fingerprint(settings, request.system, request.tools)


def prompt_fingerprint(settings: ModelSettings = MODEL_SETTINGS) -> str:
    """The fingerprint of the real request prefix: the settings, the system blocks and the tools."""
    return fingerprint(settings, system_blocks(el_hornero.NAME), TOOL_SCHEMAS)


def messages_digest(request: ModelRequest) -> str:
    """sha256 of the request's messages as canonical JSON: sorted keys, no spaces."""
    text = json.dumps(request.messages, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()


class ReplayModel:
    def __init__(self, root: Path, case: str, run: int, settings: ModelSettings = MODEL_SETTINGS):
        self._path, self._case, self._run = recording_path(root, case, run), case, run
        self._shown, self._settings = shown_path(self._path), settings
        self._steps: dict[int, tuple[Json, ModelResponse]] | None = None
        self._next = 0

    def complete(self, request: ModelRequest) -> ModelResponse:
        step, self._next = self._next, self._next + 1
        if (recorded := self._load().get(step)) is None:
            raise ReplayError(f"{self._shown}: no recorded step {step} (record it with --record)")
        entry, response = recorded
        if entry["fingerprint"] != request_fingerprint(request, self._settings):
            raise ReplayError(f"re-record required: {self._shown} step {step} is stale (D9)")
        if entry["messages"] != messages_digest(request):
            where = f"{self._shown} step {step}"
            raise ReplayError(f"{where}: recording does not match this request; re-record required")
        return response

    def finish(self) -> None:
        """The run is over: a recorded step it never asked for means its path changed."""
        if unused := sorted(step for step in self._load() if step >= self._next):
            raise ReplayError(f"{self._shown}: steps {unused} were never asked for; re-record")

    def _load(self) -> dict[int, tuple[Json, ModelResponse]]:
        if self._steps is None:
            try:
                lines = self._path.read_text(encoding="utf-8").splitlines()
            except OSError as error:
                raise ReplayError(
                    f"{self._shown}: no recording (record it with --record)"
                ) from error
            self._steps = {}
            for number, line in enumerate(lines, 1):
                entry = self._entry(line, number)
                try:
                    response = parse_response(entry["message"])
                except ModelUnavailableError as error:  # never a failed turn: a broken file
                    raise ReplayError(f"{self._shown}:{number}: malformed message") from error
                self._steps[entry["step"]] = (entry, response)
        return self._steps

    def _entry(self, line: str, number: int) -> Json:
        where = f"{self._shown}:{number}"
        try:
            entry = json.loads(line)
        except ValueError as error:
            raise ReplayError(f"{where}: not JSON") from error
        if not isinstance(entry, dict) or set(entry) != FIELDS:
            raise ReplayError(f"{where}: needs exactly {sorted(FIELDS)}")
        if (entry["case"], entry["run"]) != (self._case, self._run):
            raise ReplayError(f"{where}: belongs to another case or run")
        if type(entry["step"]) is not int or entry["step"] in (self._steps or {}):
            raise ReplayError(f"{where}: the step is not a new integer")
        texts = (entry["fingerprint"], entry["messages"])
        if not all(isinstance(t, str) for t in texts) or not isinstance(entry["message"], dict):
            raise ReplayError(f"{where}: malformed fingerprint, digest or message")
        return entry


class RawModel(ModelPort, Protocol):
    """The live adapter: it keeps the raw message of its last call."""

    settings: ModelSettings
    last_raw: Json | None


class RecordError(Exception):
    """A live call of the run failed, so its recording is not written."""


class RecordingModel:
    """Passes each call to the live adapter and keeps what it answered. `finish`, once the
    whole run is over, writes the lines to a temporary file next to the recording and renames
    it into place: until then, and after any failed run, the old recording is untouched."""

    def __init__(self, inner: RawModel, root: Path, case: str, run: int) -> None:
        self._inner, self._case, self._run = inner, case, run
        self._path, self._lines, self._failed = recording_path(root, case, run), list[str](), False
        self._shown = shown_path(self._path)

    def complete(self, request: ModelRequest) -> ModelResponse:
        try:
            response = self._inner.complete(request)
        except ModelUnavailableError:  # the turn fails; the recording would miss this step
            self._failed = True
            raise
        entry: dict[str, Any] = {"case": self._case, "run": self._run, "step": len(self._lines)}
        entry["fingerprint"] = request_fingerprint(request, self._inner.settings)
        entry |= {"messages": messages_digest(request), "message": self._inner.last_raw}
        self._lines.append(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
        return response

    def finish(self) -> None:
        if self._failed:
            raise RecordError(f"{self._shown}: a live call failed, so nothing was recorded")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(f".{self._path.name}.tmp")
        temporary.write_text("".join(self._lines), encoding="utf-8")
        temporary.replace(self._path)  # atomic: the old file or the new one, never half of it


def model_factory(mode: Mode, root: Path, case: str, run: int) -> Callable[[], ModelPort]:
    """What `compose` calls once the customer is resolved. Replay never builds the adapter."""
    if mode is Mode.REPLAY:
        return lambda: ReplayModel(root, case, run)
    from dale.brain.infrastructure.anthropic_model import AnthropicModel  # live modes only

    if mode is Mode.LIVE:
        return AnthropicModel  # no arguments: the environment holds the credentials
    return lambda: RecordingModel(AnthropicModel(), root, case, run)

"""The replayed model behind an eval run (design §10, D9, R13).

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
"""

import hashlib
import json
from pathlib import Path

from dale.brain.application.model_port import (
    MODEL_SETTINGS,
    Json,
    ModelRequest,
    ModelResponse,
    ModelSettings,
    ModelUnavailableError,
    parse_response,
)
from dale.brain.application.prompt import fingerprint

FIELDS = {"case", "run", "step", "fingerprint", "messages", "message"}


class ReplayError(Exception):
    """The recording cannot answer this call. The run fails; nothing else answers instead."""


def recording_path(root: Path, case: str, run: int) -> Path:
    return root / case / f"run-{run}.jsonl"


def request_fingerprint(request: ModelRequest, settings: ModelSettings = MODEL_SETTINGS) -> str:
    return fingerprint(settings, request.system, request.tools)


def messages_digest(request: ModelRequest) -> str:
    """sha256 of the request's messages as canonical JSON: sorted keys, no spaces."""
    text = json.dumps(request.messages, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()


class ReplayModel:
    def __init__(self, root: Path, case: str, run: int, settings: ModelSettings = MODEL_SETTINGS):
        self._path, self._case, self._run = recording_path(root, case, run), case, run
        self._settings = settings
        self._steps: dict[int, tuple[Json, ModelResponse]] | None = None
        self._next = 0

    def complete(self, request: ModelRequest) -> ModelResponse:
        step, self._next = self._next, self._next + 1
        if (recorded := self._load().get(step)) is None:
            raise ReplayError(f"{self._path}: no recorded step {step} (record it with --record)")
        entry, response = recorded
        if entry["fingerprint"] != request_fingerprint(request, self._settings):
            raise ReplayError(f"re-record required: {self._path} step {step} is stale (D9)")
        if entry["messages"] != messages_digest(request):
            where = f"{self._path} step {step}"
            raise ReplayError(f"{where}: recording does not match this request; re-record required")
        return response

    def finish(self) -> None:
        """The run is over: a recorded step it never asked for means its path changed."""
        if unused := sorted(step for step in self._load() if step >= self._next):
            raise ReplayError(f"{self._path}: steps {unused} were never asked for; re-record")

    def _load(self) -> dict[int, tuple[Json, ModelResponse]]:
        if self._steps is None:
            try:
                lines = self._path.read_text(encoding="utf-8").splitlines()
            except OSError as error:
                raise ReplayError(
                    f"{self._path}: no recording (record it with --record)"
                ) from error
            self._steps = {}
            for number, line in enumerate(lines, 1):
                entry = self._entry(line, number)
                try:
                    response = parse_response(entry["message"])
                except ModelUnavailableError as error:  # never a failed turn: a broken file
                    raise ReplayError(f"{self._path}:{number}: malformed message") from error
                self._steps[entry["step"]] = (entry, response)
        return self._steps

    def _entry(self, line: str, number: int) -> Json:
        where = f"{self._path}:{number}"
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

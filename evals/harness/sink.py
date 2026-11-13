"""Where the records of one pytest session are kept until its report is built (task 13.2).

One directory per session, with one file per run, named by case and run and written by rename:
a rerun replaces its own file and a half-written file is never read. The order the tests finish
in, and how many pytest processes run them (xdist workers share the directory), do not matter.

Each file also carries the session it came from: its id, the mode (replay, live or record) and
the prompt fingerprint. `read` refuses a file whose session is not the sink's, so a record left
by an earlier session, another mode or another prompt can never reach a report.
"""

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

from dale.brain.application.model_port import Usage
from evals.harness.metrics import RunRecord
from evals.harness.model import prompt_fingerprint


class SinkError(ValueError):
    """A file in the sink does not belong to this session."""


@dataclass(frozen=True, slots=True)
class SinkSession:
    id: str
    mode: str
    fingerprint: str

    @classmethod
    def new(cls, mode: str) -> "SinkSession":
        return cls(uuid4().hex, mode, prompt_fingerprint())


class RunSink:
    def __init__(self, directory: Path, session: SinkSession) -> None:
        self._directory, self._session = directory, session

    def write(self, record: RunRecord) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        path = self._directory / f"{record.case}.run-{record.run}.json"
        temporary = path.with_name(f".{path.name}.tmp")
        text = json.dumps({"session": asdict(self._session), "record": asdict(record)})
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)

    def read(self) -> list[RunRecord]:
        """Every record, by case and run. Raises SinkError for a file of another session, mode
        or fingerprint, and ValueError for a file that is not a record."""
        records = list[RunRecord]()
        for path in sorted(self._directory.glob("*.json")):
            raw = json.loads(path.read_text(encoding="utf-8"))
            if raw.get("session") != asdict(self._session):
                raise SinkError(f"{path.name}: not written by this session, mode and prompt")
            fields = raw["record"]
            usage = tuple(Usage(**u) for u in fields.pop("usage"))
            problems = tuple(fields.pop("problems"))
            records.append(RunRecord(usage=usage, problems=problems, **fields))
        return records

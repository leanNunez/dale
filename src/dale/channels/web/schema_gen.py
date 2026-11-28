"""Writes contract v1 from the Python types (D20): `python -m dale.channels.web.schema_gen`.

One `<Type>.schema.json` per wire type, plus `components.json` and `notice.json` (the notice
version the page's banner text belongs to, DD42). The output is deterministic
(sorted keys, 2-space indent, trailing newline) and committed; a golden test and CI fail when a
regeneration differs, so a removed or renamed field cannot slip by (S5.2, S5.4).
"""

import json
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter
from pydantic.json_schema import JsonSchemaMode

from dale.channels.web.contract import (
    COMMANDS,
    COMPONENTS,
    ContractInfo,
    DemoInfo,
    ResponseEnvelope,
    WebEvent,
)
from dale.channels.web.demo import NOTICE

# A repository tool: this path resolves only in a source or editable checkout, not an install.
CONTRACT_DIR = Path(__file__).resolve().parents[4] / "contracts" / "v1"
SCHEMA_TYPES: dict[str, Any] = {
    "WebEvent": WebEvent,
    "ResponseEnvelope": ResponseEnvelope,
    "ContractInfo": ContractInfo,
    **COMMANDS,
}


def _closed(node: Any) -> Any:
    """Every object forbids extra keys, matching the exact-keys loader of the shown events. An
    object that already says what extra keys hold (a `dict[str, X]`) keeps it."""
    if isinstance(node, dict):
        closed = {key: _closed(value) for key, value in node.items()}
        if closed.get("type") == "object":
            closed.setdefault("additionalProperties", False)
        return closed
    return [_closed(item) for item in node] if isinstance(node, list) else node


def _dump(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def render_schema(name: str, wire_type: Any) -> str:
    """Commands are input, so a defaulted field is optional to send; what the host emits
    always carries its defaulted fields, so they are required."""
    mode: JsonSchemaMode = "validation" if name in COMMANDS else "serialization"
    schema = TypeAdapter(wire_type).json_schema(mode=mode)
    return _dump(_closed({"title": name, **schema}))


def render() -> dict[str, str]:
    files = {f"{name}.schema.json": render_schema(name, t) for name, t in SCHEMA_TYPES.items()}
    notice = DemoInfo(notice_version=NOTICE.version, retention_days=NOTICE.retention_days)
    return {
        **files,
        "components.json": _dump(COMPONENTS),
        "notice.json": _dump(notice.model_dump()),
    }


def main(out: Path = CONTRACT_DIR) -> None:
    files = render()
    out.mkdir(parents=True, exist_ok=True)
    for stale in out.glob("*.schema.json"):
        if stale.name not in files:
            stale.unlink()
    for name, text in files.items():
        (out / name).write_text(text)


if __name__ == "__main__":
    main()

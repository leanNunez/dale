"""Schema generation is deterministic, committed and English-only (W5, W16; S5.2, S5.4, S16.2)."""

import json
import re
from pathlib import Path
from typing import Any

from pydantic import Field, create_model

from dale.channels.web import schema_gen
from dale.channels.web.contract import COMPONENTS, ResponseEnvelope, SendMessage
from dale.channels.web.schema_gen import CONTRACT_DIR, SCHEMA_TYPES, render, render_schema

SPEC_ID = re.compile(r"\((?:[WRSDB]\d+(?:\.\d+)?(?:, )?)+\)")
SPANISH = re.compile(r"pedido|cliente|producto|precio|cantidad|fecha|entrega|mensaje|estado", re.I)


def test_the_committed_files_equal_a_fresh_generation() -> None:
    committed = {p.name: p.read_text() for p in CONTRACT_DIR.glob("*.json")}
    assert committed == render()  # a stale, missing or extra file fails here


def test_main_writes_the_same_bytes_and_drops_stale_schemas(tmp_path: Path) -> None:
    (tmp_path / "Gone.schema.json").write_text("{}")
    schema_gen.main(tmp_path)
    assert {p.name: p.read_text() for p in tmp_path.glob("*.json")} == render()


def test_the_output_is_sorted_two_space_indented_and_ends_with_a_newline() -> None:
    for text in render().values():
        assert text.endswith("}\n") and not text.endswith("\n\n")
        assert text == json.dumps(json.loads(text), indent=2, sort_keys=True) + "\n"


def objects(node: Any) -> list[dict[str, Any]]:
    if isinstance(node, dict):
        return [node] * (node.get("type") == "object") + [
            o for v in node.values() for o in objects(v)
        ]
    return [o for item in node for o in objects(item)] if isinstance(node, list) else []


def test_every_object_forbids_additional_properties() -> None:
    for text in render().values():
        assert all(o["additionalProperties"] is False for o in objects(json.loads(text)))


def test_an_existing_additional_properties_is_kept() -> None:
    counts = create_model("Counts", by_kind=(dict[str, int], ...))
    schema = json.loads(render_schema("Counts", counts))
    assert schema["properties"]["by_kind"]["additionalProperties"] == {"type": "integer"}
    assert schema["additionalProperties"] is False


def test_a_defaulted_command_field_is_optional_and_a_defaulted_output_field_is_required() -> None:
    class WithNote(SendMessage):  # even with the flag that requires defaults on output
        model_config = SendMessage.model_config | {
            "json_schema_serialization_defaults_required": True
        }
        note: str = ""

    assert json.loads(render_schema("SendMessage", WithNote))["required"] == ["text"]
    assert "v" in json.loads(render_schema("ResponseEnvelope", ResponseEnvelope))["required"]


def descriptions(node: Any) -> list[str]:
    if isinstance(node, dict):
        own = [node["description"]] if isinstance(node.get("description"), str) else []
        return own + [d for value in node.values() for d in descriptions(value)]
    return [d for item in node for d in descriptions(item)] if isinstance(node, list) else []


def test_no_published_description_names_an_internal_spec_id() -> None:
    found = [d for text in render().values() for d in descriptions(json.loads(text))]
    assert found and not [d for d in found if SPEC_ID.search(d)]
    assert SPEC_ID.search("Every API response (D14, W3.1).")


def test_a_renamed_or_removed_field_changes_the_generated_schema() -> None:
    committed = (CONTRACT_DIR / "SendMessage.schema.json").read_text()
    assert render_schema("SendMessage", SendMessage) == committed
    renamed = create_model("SendMessage", body=(str, Field(min_length=1, max_length=2000)))
    removed = create_model("SendMessage")
    assert render_schema("SendMessage", renamed) != committed
    assert render_schema("SendMessage", removed) != committed


def identifiers(node: Any) -> list[str]:
    """Property names, definition names, titles and enum values: what the page can name."""
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("properties", "$defs"):
                found += list(value)
            elif key == "title" or key == "enum":
                found += [str(v) for v in (value if key == "enum" else [value])]
            found += identifiers(value)
    elif isinstance(node, list):
        found = [name for item in node for name in identifiers(item)]
    return found


def test_the_schemas_name_nothing_in_spanish() -> None:
    names = [i for text in render().values() for i in identifiers(json.loads(text))]
    assert names and all(n.isascii() and not SPANISH.search(n) for n in names)
    assert all(k.isascii() and not SPANISH.search(k) for k in COMPONENTS)


def test_there_is_one_schema_file_per_wire_type_plus_the_components_map() -> None:
    assert set(render()) == {f"{name}.schema.json" for name in SCHEMA_TYPES} | {"components.json"}
    assert set(SCHEMA_TYPES) == {
        "WebEvent",
        "ResponseEnvelope",
        "SendMessage",
        "PressDale",
        "CancelProposal",
    }

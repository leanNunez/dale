"""Contract v1 only grows (W5 S5.5): every field, event type and code of the schemas at tag
`v0.2` still exists in v0.3 with the same meaning, and the version is 1. The v0.2 files are read
with `git show`, so a rename, a removal or a tightened bound cannot hide behind a regeneration.

W5 lets v0.3 add fields, event types and error codes, nothing else: a command gains no validation
keyword (the v0.2 page sends what it always sent), a response gains no type branch and no enum
value but a code (the v0.2 page switches over them). The v0.2 samples are also read by the
current models, which catches a narrowing done in code."""

import ast
import copy
import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import Field, TypeAdapter, ValidationError, create_model

from dale.channels.web.contract import COMMANDS, COMPONENTS, VERSION, ResponseEnvelope, WebEvent
from dale.channels.web.errors import WebErrorCode, status_for
from dale.channels.web.schema_gen import SCHEMA_TYPES, render
from dale.shared.errors import ErrorCode

TAG = "v0.2"
FILES = ["WebEvent", "ResponseEnvelope", "SendMessage", "PressDale", "CancelProposal"]
FREE = {"title", "description", "examples", "$defs", "$ref", "properties", "required"}
# Keywords that refuse values: a command may not gain one where v0.2 had none.
NARROWING = """pattern minLength maxLength minimum maximum exclusiveMinimum exclusiveMaximum
minItems maxItems uniqueItems minProperties maxProperties multipleOf enum const format not allOf
if contains propertyNames patternProperties dependentRequired""".split()  # noqa: SIM905
# The enums W5 lets grow (error codes); the event types grow in their discriminated union.
GROWING_ENUMS = {"WebErrorCode", "ErrorCode"}
Schema = dict[str, Any]


def at_tag(path: str) -> str:
    done = subprocess.run(["git", "show", f"{TAG}:{path}"], capture_output=True, text=True)
    assert done.returncode == 0, f"tag {TAG} is not fetched (git fetch --tags): {done.stderr}"
    return done.stdout


def old_schema(name: str) -> Schema:
    return json.loads(at_tag(f"contracts/v1/{name}.schema.json"))  # type: ignore[no-any-return]


def new_schema(name: str) -> Schema:
    return json.loads(render()[f"{name}.schema.json"])  # type: ignore[no-any-return]


def deref(node: Schema, root: Schema) -> Schema:
    ref = node.get("$ref")
    return root["$defs"][ref.rsplit("/", 1)[1]] if isinstance(ref, str) else node


def violations(old: Schema, new: Schema, *, command: bool = False) -> list[str]:
    """What v0.2 promised that `new` no longer does; empty when `new` only adds."""
    return _walk(old, new, (old, new), command, "#", 0)


def _walk(
    o: Schema, n: Schema, roots: tuple[Schema, Schema], command: bool, at: str, depth: int
) -> list[str]:
    old, new = deref(o, roots[0]), deref(n, roots[1])
    found: list[str] = []
    if depth > 40:
        return [f"{at}: too deep"]
    if at == "#":  # a named type of v0.2 the page imports must still be defined
        found += [
            f"{at}: type {k} removed" for k in old.get("$defs", {}) if k not in new.get("$defs", {})
        ]
    for key, value in old.items():
        if key in FREE:
            continue
        if key in ("oneOf", "anyOf"):
            found += _branches(
                key, value, new, (old.get("discriminator"), roots, command), at, depth
            )
        elif key == "enum":
            found += [f"{at}: {v!r} removed from enum" for v in value if v not in new.get(key, [])]
            if not command and old.get("title") not in GROWING_ENUMS:
                found += [
                    f"{at}: {v!r} added to enum, which the v0.2 page does not know"
                    for v in new.get(key, [])
                    if v not in value
                ]
        elif key == "discriminator":
            mapping = new.get(key, {}).get("mapping", {})
            found += [
                f"{at}: {k} unmapped" for k, v in value["mapping"].items() if mapping.get(k) != v
            ]
        elif key == "items":
            found += _walk(value, new.get(key, {}), roots, command, f"{at}[]", depth + 1)
        elif new.get(key) != value:
            found.append(f"{at}: {key} changed from {value!r} to {new.get(key)!r}")
    if command:  # the v0.2 page sends what it sent, so no new rule may refuse it
        found += [
            f"{at}: {k} added, so what the v0.2 page sends may be refused"
            for k in new
            if k in NARROWING and k not in old
        ]
    for field, sub in old.get("properties", {}).items():
        if field not in new.get("properties", {}):
            found.append(f"{at}.{field}: removed")
        else:
            found += _walk(
                sub, new["properties"][field], roots, command, f"{at}.{field}", depth + 1
            )
    before, after = set(old.get("required", [])), set(new.get("required", []))
    found += [f"{at}: {r} no longer required" for r in before - after]
    if command:  # a field the page did not send before cannot become mandatory
        found += [f"{at}: {r} newly required" for r in after - before]
    return found


def _branches(
    key: str,
    olds: list[Schema],
    new: Schema,
    context: tuple[Any, tuple[Schema, Schema], bool],
    at: str,
    depth: int,
) -> list[str]:
    """Every old branch still has a counterpart; a response gains none, except in the union of
    event types (W5's own addition), since the v0.2 page has no case for a new type."""
    discriminator, roots, command = context
    news = new.get(key, [])
    tries = [
        [_walk(old, branch, roots, command, f"{at}/{key}{i}", depth + 1) for branch in news]
        for i, old in enumerate(olds)
    ]
    found = [
        f"{at}: {key} branch {i} lost ({min(row, key=len)[0] if row else 'no branches left'})"
        for i, row in enumerate(tries)
        if all(row)
    ]
    if not command and discriminator is None:
        found += [
            f"{at}: {key} gained branch {j}, a type the v0.2 page does not read"
            for j in range(len(news))
            if all(row[j] for row in tries)
        ]
    return found


@pytest.mark.parametrize("name", FILES)
def test_every_v02_field_event_type_and_code_is_still_there_unchanged(name: str) -> None:
    assert violations(old_schema(name), new_schema(name), command=name in COMMANDS) == []


def test_v03_added_something_and_the_checker_sees_it_as_an_addition() -> None:
    old, new = old_schema("ResponseEnvelope"), new_schema("ResponseEnvelope")
    assert old != new and set(SCHEMA_TYPES) > set(FILES)
    assert set(old["$defs"]["WebErrorCode"]["enum"]) < set(new["$defs"]["WebErrorCode"]["enum"])


def _nodes(node: Any) -> list[Schema]:
    if isinstance(node, dict):
        return [node, *(n for v in node.values() for n in _nodes(v))]
    return [n for v in node for n in _nodes(v)] if isinstance(node, list) else []


Mutation = Callable[[Schema], None]


def at_first(found: Callable[[Schema], bool], act: Mutation) -> Mutation:
    """Applies `act` to the first node of the schema that `found` picks."""

    def mutate(node: Schema) -> None:
        for sub in _nodes(node):
            if found(sub):
                return act(sub)

    return mutate


def has(field: str) -> Callable[[Schema], bool]:
    return lambda sub: field in sub.get("properties", {})


def drop_first(key: str) -> Mutation:
    return at_first(has(key), lambda sub: sub["properties"].pop(key))


def drop_enum_value(value: str) -> Mutation:
    return at_first(lambda sub: value in sub.get("enum", []), lambda sub: sub["enum"].remove(value))


def change(key: str, value: Any) -> Mutation:
    return at_first(lambda sub: key in sub, lambda sub: sub.__setitem__(key, value))


def field_gains(field: str, key: str, value: Any) -> Mutation:
    return at_first(has(field), lambda sub: sub["properties"][field].__setitem__(key, value))


def field_gains_branch(field: str, branch: Schema) -> Mutation:
    return at_first(has(field), lambda sub: sub["properties"][field]["anyOf"].append(branch))


def enum_gains(title: str, value: str) -> Mutation:
    return at_first(
        lambda sub: sub.get("title") == title and "enum" in sub,
        lambda sub: sub["enum"].append(value),
    )


def drop_branch(node: Schema) -> None:
    node["oneOf"].pop()
    node["discriminator"]["mapping"].popitem()


def root_gains(key: str, value: Any) -> Mutation:
    return lambda node: node.__setitem__(key, value)


def seq_nullable(node: Schema) -> None:
    node["properties"]["seq"] = {"anyOf": [{"minimum": 0, "type": "integer"}, {"type": "null"}]}


def new_event_type(node: Schema) -> None:
    node["$defs"]["Fresh"] = {"type": "object", "title": "Fresh"}
    for sub in _nodes(node):
        if "discriminator" in sub:
            sub["oneOf"].append({"$ref": "#/$defs/Fresh"})
            sub["discriminator"]["mapping"]["Fresh"] = "#/$defs/Fresh"


def new_optional_field(node: Schema) -> None:
    node["properties"]["extra"] = {"type": "string", "title": "Extra"}


# (id, schema, mutation): each one takes something away or changes it, and must be caught.
BROKEN: list[tuple[str, str, Mutation]] = [
    ("response-loses-pending-id", "ResponseEnvelope", drop_first("pending_proposal_id")),
    ("web-code-lost", "ResponseEnvelope", drop_enum_value("conversation_busy")),
    ("brain-code-lost", "ResponseEnvelope", drop_enum_value("rules_unavailable")),
    ("event-type-const-changed", "ResponseEnvelope", change("const", 2)),
    ("version-becomes-2", "ResponseEnvelope", field_gains("v", "const", 2)),
    ("text-max-length-grows", "SendMessage", change("maxLength", 2001)),
    ("text-removed", "SendMessage", drop_first("text")),
    ("proposal-id-format-changed", "PressDale", change("format", "uri")),
    ("event-branch-lost", "WebEvent", drop_branch),
    ("event-data-removed", "WebEvent", drop_first("data")),
    ("required-emptied", "CancelProposal", change("required", [])),
    ("seq-nullable", "ResponseEnvelope", seq_nullable),
    # Narrowing of what the page sends: the v0.2 page would send what it always sent.
    ("text-gains-pattern", "SendMessage", field_gains("text", "pattern", "^[a-z]+$")),
    ("proposal-id-gains-max-length", "PressDale", field_gains("proposal_id", "maxLength", 3)),
    ("command-gains-not", "SendMessage", root_gains("not", {"required": ["text"]})),
    # Widening of what the page reads: the v0.2 page does not handle the new type or value.
    (
        "conversation-id-gains-integer",
        "ResponseEnvelope",
        field_gains_branch("conversation_id", {"type": "integer"}),
    ),
    ("verdict-gains-a-value", "ResponseEnvelope", enum_gains("Verdict", "maybe")),
    ("verdict-gains-a-value-in-an-event", "WebEvent", enum_gains("Verdict", "maybe")),
    ("verdict-reason-gains-a-value", "ResponseEnvelope", enum_gains("Reason", "maybe")),
]
# What W5 lets v0.3 add: a field, an event type, an error code. None is a violation.
GROWN: list[tuple[str, str, Mutation]] = [
    ("web-code", "ResponseEnvelope", enum_gains("WebErrorCode", "fresh_code")),
    ("brain-code", "ResponseEnvelope", enum_gains("ErrorCode", "fresh_code")),
    ("response-field", "ResponseEnvelope", new_optional_field),
    ("event-type", "ResponseEnvelope", new_event_type),
    ("event-type-of-the-union", "WebEvent", new_event_type),
    ("command-field", "SendMessage", new_optional_field),
]


def caught(name: str, mutate: Mutation) -> list[str]:
    changed = copy.deepcopy(new_schema(name))
    mutate(changed)
    return violations(old_schema(name), changed, command=name in COMMANDS)


@pytest.mark.parametrize(("name", "mutate"), [b[1:] for b in BROKEN], ids=[b[0] for b in BROKEN])
def test_a_removed_renamed_changed_narrowed_or_widened_part_is_caught(
    name: str, mutate: Mutation
) -> None:
    assert caught(name, mutate)


@pytest.mark.parametrize(("name", "mutate"), [g[1:] for g in GROWN], ids=[g[0] for g in GROWN])
def test_what_w5_lets_v03_add_is_not_a_violation(name: str, mutate: Mutation) -> None:
    assert caught(name, mutate) == []


def test_a_message_names_the_value_a_lost_branch_lost() -> None:
    lost = caught("ResponseEnvelope", drop_enum_value("conversation_busy"))
    assert any("anyOf branch" in m and "'conversation_busy' removed from enum" in m for m in lost)


def test_a_new_required_command_field_is_caught() -> None:
    wider = copy.deepcopy(new_schema("SendMessage"))
    new_optional_field(wider)
    wider["required"].append("extra")
    assert any(
        "newly required" in m for m in violations(old_schema("SendMessage"), wider, command=True)
    )


def v02_samples() -> dict[str, str]:
    done = subprocess.run(
        ["git", "ls-tree", "--name-only", TAG, "contracts/v1/samples/"],
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, f"tag {TAG} is not fetched (git fetch --tags): {done.stderr}"
    return {Path(path).stem: at_tag(path) for path in done.stdout.split()}


def reader_for(stem: str) -> Callable[[str], Any]:
    """Parses a v0.2 sample with the current model of its kind and gives back what it holds."""
    if stem == "response_envelope":
        return lambda text: json.loads(ResponseEnvelope.model_validate_json(text).model_dump_json())
    if stem.startswith("event_"):
        events = TypeAdapter(WebEvent)
        return lambda text: json.loads(events.dump_json(events.validate_json(text)))
    if stem.startswith("command_"):
        command = COMMANDS["".join(word.title() for word in stem.split("_")[1:])]
        return lambda text: json.loads(command.model_validate_json(text).model_dump_json())
    raise AssertionError(f"the v0.2 sample {stem} has no reader here")


def unread(samples: dict[str, str], readers: Callable[[str], Callable[[str], Any]]) -> list[str]:
    found: list[str] = []
    for stem, text in samples.items():
        try:
            back = readers(stem)(text)
        except ValidationError as error:
            found.append(f"{stem}: no longer parses ({error.error_count()} errors)")
        else:
            if back != json.loads(text):
                found.append(f"{stem}: parses to something else")
    return found


def test_every_v02_sample_still_parses_with_the_same_meaning() -> None:
    samples = v02_samples()
    assert len(samples) == 12  # 3 commands, 8 events, 1 envelope
    assert unread(samples, reader_for) == []


def override(stem: str, reader: Callable[[str], Any]) -> Callable[[str], Callable[[str], Any]]:
    return lambda other: reader if other == stem else reader_for(other)


def test_a_sample_the_models_refuse_or_read_differently_is_caught() -> None:
    shorter = create_model("Shorter", text=(str, Field(max_length=3)))
    narrowed = override(
        "command_send_message",
        lambda t: json.loads(shorter.model_validate_json(t).model_dump_json()),
    )
    reshaped = override(
        "response_envelope", lambda t: {**json.loads(t), "pending_proposal_id": None}
    )
    refused, changed = unread(v02_samples(), narrowed), unread(v02_samples(), reshaped)
    assert len(refused) == 1 and "command_send_message" in refused[0]
    assert len(changed) == 1 and "response_envelope" in changed[0]


def test_the_version_is_still_1_everywhere() -> None:
    assert VERSION == 1
    for name in ("WebEvent", "ResponseEnvelope"):
        versions = [n["const"] for n in _nodes(new_schema(name)) if n.get("title") == "V"]
        assert versions and set(versions) == {1}
    assert json.loads(at_tag("contracts/v1/components.json")).items() <= COMPONENTS.items()


def literals(path: str, name: str) -> dict[str, Any]:
    """The `Code.X: constant` entries of a dict assigned at module level in v0.2's source."""
    for stmt in ast.parse(at_tag(path)).body:
        if (
            isinstance(stmt, ast.AnnAssign)
            and isinstance(stmt.target, ast.Name)
            and stmt.target.id == name
            and isinstance(stmt.value, ast.Dict)
        ):
            pairs = zip(stmt.value.keys, stmt.value.values, strict=True)
            return {
                k.attr: v.value
                for k, v in pairs
                if isinstance(k, ast.Attribute) and isinstance(v, ast.Constant)
            }
    raise AssertionError(f"{name} not found in {path} at {TAG}")


def test_every_v02_code_keeps_its_http_status() -> None:
    web = literals("src/dale/channels/web/errors.py", "WEB_STATUS")
    brain = literals("src/dale/shared/errors.py", "HTTP_STATUS")
    assert len(web) == 12 and len(brain) == 17
    assert all(status_for(WebErrorCode[k]) == s for k, s in web.items())
    assert all(status_for(ErrorCode[k]) == s for k, s in brain.items())

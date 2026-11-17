"""The case file (design §10, R13): YAML read at the I/O edge into frozen pydantic models that
refuse any unknown field, so a typo in a case never silently weakens it.

`expect` describes the FINAL STATE, never the path (S13.2): the orders in the database, the
handoff row, the kinds of event the customer was shown and the failure code of a failed turn.
No field names a tool, a tool order or a model call, so two different tool paths that reach the
same state both pass.

`history` is a list of earlier customer messages. Each one is a real turn through the same
model before `message`, so a recording holds the steps of every turn (the step counter runs
across the whole run). `seed_overrides` goes to the seed as it is, except that a
`cutoff_time` given as "HH:MM" text becomes a time.
"""

from collections.abc import Mapping
from datetime import date, time
from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from dale.brain.domain.handoff import HandoffReason
from dale.shared.clock import FrozenClock
from dale.shared.errors import ErrorCode

ShownKind = Literal[
    "AssistantText",
    "ProposalSummary",
    "OrderConfirmed",
    "OrderRejected",
    "HandoffNotice",
    "SystemNotice",
]
type Overrides = dict[str, dict[str, dict[str, Any]]]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExpectedLine(_Model):
    sku: str = Field(min_length=1)
    qty: int = Field(ge=1, le=999)


class ExpectedOrder(_Model):
    """An order that must exist at the end: its lines (any order), its total and its date."""

    lines: tuple[ExpectedLine, ...] = Field(min_length=1)
    total_pesos: int = Field(gt=0)
    delivery_date: date


class ShownExpect(_Model):
    """Kinds of shown event that must appear at least once, and kinds that must never appear."""

    includes: tuple[ShownKind, ...] = ()
    excludes: tuple[ShownKind, ...] = ()


class Expect(_Model):
    """`orders` is the whole set of orders in the database (empty: none), `handoff` the reason
    of the one handoff row (null: no handoff row) and `pending_proposal` whether a prepared
    proposal is left unconfirmed at the end; all three are required so a case cannot forget
    them. `failure` is the one failure code a turn may end with (null: every turn answers)."""

    orders: tuple[ExpectedOrder, ...]
    handoff: HandoffReason | None
    pending_proposal: bool
    failure: ErrorCode | None = None
    shown: ShownExpect = ShownExpect()


class Case(_Model):
    id: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    suite: Literal["core", "gauchadas"]
    now: AwareDatetime  # feeds FrozenClock: the cutoff rules never see the system time (S13.5)
    customer: str = Field(min_length=1)  # a customer code of El Hornero
    seed_overrides: Mapping[str, Mapping[str, Mapping[str, Any]]] = {}
    history: tuple[str, ...] = ()
    message: str = Field(min_length=1)
    press_dale: bool
    expect: Expect

    @model_validator(mode="after")
    def _gauchada(self) -> Self:
        """R7: a gauchada passes only with a handoff and no order. It presses the Dale key, so
        an exception the agent made confirmable becomes an order and fails the run."""
        if self.suite == "gauchadas" and (self.expect.orders or self.expect.handoff is None):
            raise ValueError("a gauchada expects a handoff and no order")
        if self.suite == "gauchadas" and not self.press_dale:
            raise ValueError("a gauchada presses the Dale key (press_dale: true)")
        return self

    def clock(self) -> FrozenClock:
        return FrozenClock(self.now)

    def overrides(self) -> Overrides:
        """The seed's override shape, with each cutoff given as "HH:MM" turned into a time."""
        typed: Overrides = {}
        for table, rows in self.seed_overrides.items():
            typed[table] = {key: dict(changes) for key, changes in rows.items()}
            for changes in typed[table].values():
                if isinstance(cutoff := changes.get("cutoff_time"), str):
                    changes["cutoff_time"] = time.fromisoformat(cutoff)
        return typed


class _UniqueKeys(yaml.SafeLoader):
    """Plain YAML keeps the last of two equal keys in silence; a case file refuses them."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        mapping = super().construct_mapping(node, deep=deep)
        if len(mapping) != len(node.value):
            keys = [self.construct_object(key) for key, _ in node.value]
            twice = next(key for key in keys if keys.count(key) > 1)
            raise yaml.MarkedYAMLError(
                None, None, f"the key {twice!r} appears twice", node.start_mark
            )
        return mapping


def load_case(path: Path) -> Case:
    """Raises ValueError for anything but one valid mapping whose id is the file's name."""
    try:
        raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeys)  # safe: a SafeLoader
    except yaml.YAMLError as error:
        raise ValueError(f"{path.name}: not valid YAML ({error})") from error
    case = Case.model_validate(raw)  # a ValidationError is a ValueError
    if case.id != path.stem:
        raise ValueError(f"{path.name}: the id {case.id!r} must be the file name")
    return case


def load_cases(directory: Path) -> list[Case]:
    """Every case in `directory`. A missing or empty directory raises, and so does any entry
    that is not a `*.yaml` file (a `.yml` is never skipped): a run with no case passes nothing."""
    if not directory.is_dir():
        raise ValueError(f"{directory}: no such case directory")
    entries = sorted(directory.iterdir())
    if others := [p.name for p in entries if p.suffix != ".yaml" or not p.is_file()]:
        raise ValueError(f"{directory}: not a *.yaml case file: {', '.join(others)}")
    if not entries:
        raise ValueError(f"{directory}: no case file")
    return [load_case(path) for path in entries]

"""The case schema (task 12.1, R13): a valid case loads, an unknown field is refused, `now`
feeds the frozen clock (S13.5), and `expect` has no field for the tool path (S13.2)."""

from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from dale.brain.domain.handoff import HandoffReason
from evals.harness.case import Case, Expect, load_case, load_cases

ORDER = {
    "lines": [{"sku": "COLA-225", "qty": 20}],
    "total_pesos": 49000,
    "delivery_date": "2026-11-19",
}
VALID: dict[str, Any] = {
    "id": "order-cola-ok",
    "suite": "core",
    "now": "2026-11-18T09:00:00-03:00",
    "customer": "C-001",
    "message": "quiero 20 colas de dos y cuarto",
    "press_dale": True,
    "expect": {"orders": [ORDER], "handoff": None, "pending_proposal": False},
}


def case(**changes: Any) -> Case:
    return Case.model_validate(VALID | changes)


def test_a_valid_case_loads_with_defaults() -> None:
    loaded = case()
    assert (loaded.history, loaded.seed_overrides, loaded.expect.failure) == ((), {}, None)
    assert loaded.expect.orders[0].delivery_date == date(2026, 11, 19)


@pytest.mark.parametrize(
    "bad",
    [
        {"surprise": 1},
        {"expect": VALID["expect"] | {"tools": ["prepare_order"]}},
        {"expect": VALID["expect"] | {"orders": [ORDER | {"extra": 1}]}},
        {"expect": {"orders": [], "pending_proposal": False}},  # handoff, even as null
        {"expect": {"handoff": None, "pending_proposal": False}},  # orders, even as empty
        {"expect": {"orders": [], "handoff": None}},  # whether a proposal is left pending
        {"now": "2026-11-18T09:00:00"},  # no timezone
        {"press_dale": "maybe"},
        {"id": "Not A Slug"},
    ],
)
def test_an_unknown_field_or_a_bad_value_is_refused(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        case(**bad)


def test_expect_grades_state_and_has_no_field_for_the_tool_path() -> None:
    """S13.2 by construction: nothing in a case can name a tool or a call order."""
    assert set(Expect.model_fields) == {"orders", "handoff", "pending_proposal", "failure", "shown"}


def test_now_feeds_the_frozen_clock_not_the_system_time() -> None:
    """S13.5."""
    assert case().clock().now() == datetime(2026, 11, 18, 12, tzinfo=UTC)


HANDED = {"orders": [], "handoff": "exception_request", "pending_proposal": False}


@pytest.mark.parametrize("expect", [HANDED | {"orders": [ORDER]}, HANDED | {"handoff": None}])
def test_a_gauchada_expects_a_handoff_and_no_order(expect: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="handoff and no order"):
        case(suite="gauchadas", expect=expect)
    ok = case(suite="gauchadas", expect=HANDED)
    assert ok.expect.handoff is HandoffReason.EXCEPTION_REQUEST


def test_a_gauchada_presses_the_dale_key() -> None:
    """So an exception the agent made confirmable becomes an order, and the run fails."""
    with pytest.raises(ValidationError, match="press_dale: true"):
        case(suite="gauchadas", expect=HANDED, press_dale=False)


def test_a_cutoff_override_given_as_text_becomes_a_time() -> None:
    zone = {"zones": {"Centro": {"cutoff_time": "17:30", "min_order_amount_cents": 1}}}
    loaded = case(seed_overrides=zone)
    assert loaded.overrides()["zones"]["Centro"] == {
        "cutoff_time": time(17, 30),
        "min_order_amount_cents": 1,
    }
    assert loaded.seed_overrides == zone  # the case itself is untouched


def write(directory: Path, name: str, text: str) -> Path:
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


YAML = """\
id: order-cola-ok
suite: core
now: 2026-11-18T09:00:00-03:00
customer: C-001
message: quiero 20 colas
press_dale: false
expect: {orders: [], handoff: null, pending_proposal: false}
"""


def test_a_case_file_loads_and_its_id_is_its_name(tmp_path: Path) -> None:
    write(tmp_path, "order-cola-ok.yaml", YAML)
    assert [c.id for c in load_cases(tmp_path)] == ["order-cola-ok"]
    with pytest.raises(ValueError, match="must be the file name"):
        load_case(write(tmp_path, "other-name.yaml", YAML))


def test_a_file_that_is_not_a_valid_case_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not valid YAML"):
        load_case(write(tmp_path, "x.yaml", "a: [unclosed"))
    with pytest.raises(ValueError):
        load_case(write(tmp_path, "y.yaml", "- just\n- a list\n"))
    with pytest.raises(ValueError):
        load_case(write(tmp_path, "z.yaml", YAML + "tools: [prepare_order]\n"))


def test_a_repeated_key_is_refused_not_overwritten(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="the key 'press_dale' appears twice"):
        load_case(write(tmp_path, "order-cola-ok.yaml", YAML + "press_dale: true\n"))


def test_a_missing_or_empty_case_directory_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no such case directory"):
        load_cases(tmp_path / "cases")
    with pytest.raises(ValueError, match="no case file"):
        load_cases(tmp_path)


@pytest.mark.parametrize("name", ["order-cola-ok.yml", "notes.txt", "sub"])
def test_any_entry_that_is_not_a_yaml_case_file_is_refused(tmp_path: Path, name: str) -> None:
    write(tmp_path, "order-cola-ok.yaml", YAML)
    if name == "sub":
        (tmp_path / name).mkdir()
    else:
        write(tmp_path, name, YAML)
    with pytest.raises(ValueError, match=f"not a \\*.yaml case file: {name}"):
        load_cases(tmp_path)


def test_a_price_change_needs_a_press_and_a_case_is_not_its_own_negative() -> None:
    moved = {"sku": "COLA-225", "pesos": 2600}
    assert case(price_change=moved).price_change.pesos == 2600  # type: ignore[union-attr]
    with pytest.raises(ValidationError, match="press_dale"):
        case(price_change=moved, press_dale=False)
    with pytest.raises(ValidationError, match="pesos"):
        case(price_change=moved | {"pesos": 0})
    with pytest.raises(ValidationError, match="its own negative"):
        case(negative_of="order-cola-ok")
    with pytest.raises(ValidationError, match="String should match"):
        case(negative_of="Not A Slug")
    assert case(negative_of="press-dale-confirms").negative_of == "press-dale-confirms"


@pytest.mark.parametrize(
    "premise",
    [
        {"kind": "below_minimum", "lines": [{"sku": "COLA-225", "qty": 12}], "total_pesos": 29400},
        {"kind": "ambiguous", "query": "gaseosas de dos y cuarto", "qty": 15},
        {"kind": "past_cutoff", "missed": "2026-11-19"},
    ],
)
def test_a_premise_of_each_kind_loads_and_any_other_is_refused(premise: dict[str, Any]) -> None:
    assert case(premise=premise).premise.kind == premise["kind"]  # type: ignore[union-attr]
    for bad in ({"kind": "lucky"}, premise | {"extra": 1}, {"kind": premise["kind"]}):
        with pytest.raises(ValidationError):
            case(premise=bad)

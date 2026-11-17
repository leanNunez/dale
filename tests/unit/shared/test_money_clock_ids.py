from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest

from dale.shared.clock import FrozenClock, SystemClock
from dale.shared.ids import SequentialIdGenerator, Uuid4Generator, new_proposal_id
from dale.shared.money import MAX_CENTS, Money, money_sum, pesos


def test_money_adds_and_multiplies_in_integer_cents() -> None:
    assert Money(150) + Money(250) == Money(400)
    assert Money(1999) * 3 == Money(5997)
    assert Money(100) < Money(101)


@pytest.mark.parametrize("bad", [1.5, True, "10", None])
def test_money_rejects_non_integer_cents(bad: object) -> None:
    with pytest.raises(TypeError):
        Money(bad)  # type: ignore[arg-type]


def test_money_rejects_float_quantity_and_has_no_division() -> None:
    with pytest.raises(TypeError):
        Money(100) * 1.5  # type: ignore[operator]
    with pytest.raises(TypeError):
        Money(100) / 2  # type: ignore[operator]


@pytest.mark.parametrize("bad", [True, False, 1.0, "2", None])
def test_money_multiplies_only_by_plain_integers(bad: object) -> None:
    with pytest.raises(TypeError):
        Money(100) * bad  # type: ignore[operator]


def test_money_rejects_negative_quantity_even_for_zero_cents() -> None:
    with pytest.raises(ValueError):
        Money(100) * -1
    with pytest.raises(ValueError):
        Money(0) * -1


def test_money_is_bounded_to_non_negative_bigint_cents() -> None:
    assert Money(MAX_CENTS).cents == 2**63 - 1
    for bad in (-1, MAX_CENTS + 1):
        with pytest.raises(ValueError):
            Money(bad)
    with pytest.raises(ValueError):
        Money(MAX_CENTS) + Money(1)
    with pytest.raises(ValueError):
        Money(MAX_CENTS) * 2


def test_money_add_rejects_non_money() -> None:
    with pytest.raises(TypeError):
        Money(1) + 5  # type: ignore[operator]


def test_money_sum_of_nothing_is_money_zero() -> None:
    assert money_sum([]) == Money(0)
    assert money_sum(iter([Money(1), Money(2)])) == Money(3)
    with pytest.raises(TypeError):
        money_sum([5])  # type: ignore[list-item]


def test_pesos_uses_argentine_notation() -> None:
    cases = {5: "$ 0,05", 4_900_000: "$ 49.000,00", 123_456_789: "$ 1.234.567,89"}
    assert {cents: pesos(Money(cents)) for cents in cases} == cases


def test_frozen_clock_returns_the_fixed_instant() -> None:
    instant = datetime(2026, 3, 2, 12, 0, tzinfo=UTC)
    clock = FrozenClock(instant)
    assert clock.now() == instant
    assert clock.now() == clock.now()


def test_clocks_reject_naive_datetimes() -> None:
    with pytest.raises(ValueError):
        FrozenClock(datetime(2026, 3, 2, 12, 0))


def test_clocks_are_timezone_aware() -> None:
    assert SystemClock().now().utcoffset() == timedelta(0)
    offset = datetime(2026, 3, 2, tzinfo=timezone(timedelta(hours=-3)))
    assert FrozenClock(offset).now().tzinfo is not None


def test_frozen_clock_normalizes_to_utc_like_the_system_clock() -> None:
    local = datetime(2026, 3, 2, 9, 0, tzinfo=timezone(timedelta(hours=-3)))
    now = FrozenClock(local).now()
    assert now == local
    assert now.tzinfo is UTC
    assert now.hour == 12
    assert SystemClock().now().tzinfo is now.tzinfo


def test_proposal_ids_are_random_uuid4() -> None:
    first, second = new_proposal_id(), new_proposal_id()
    assert isinstance(first, UUID)
    assert first.version == 4
    assert first != second
    assert Uuid4Generator().new_id() != Uuid4Generator().new_id()


def test_sequential_generator_is_deterministic_and_injectable() -> None:
    first_run = [new_proposal_id(SequentialIdGenerator()) for _ in range(2)]
    gen = SequentialIdGenerator()
    ids = [new_proposal_id(gen) for _ in range(3)]
    assert len(set(ids)) == 3
    assert ids[0] == first_run[0] == first_run[1] == UUID(int=1, version=4)

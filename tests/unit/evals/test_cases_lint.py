"""The suite's lint (task 14.7, R13, B96), with no database: every file loads, the case count,
the gauchada count, a negative for every positive, and each expected order checked against the
seed data and the rules code, and so is the premise of each negative, so a typo in a total, a
date or a SKU, or a negative that the right agent could fail (or the wrong one pass), fails
here and not in a live run.

A positive is a case that expects an order and is not a `negative_of` another; every other case
must name the positive it answers. A case that expects an order may still be a negative: the
cutoff case that misses the slot answers the one that makes it.

A premise is declared in the case (`premise`): `below_minimum` lines really total below the
zone minimum; an `ambiguous` request really matches two or more active products in full through
the catalog's own search, and its quantity of every one of them clears the minimum; at a
`past_cutoff` `now`, the zone's first delivery day really is missed, and a case that still
expects an order sets no date in its message (or the next slot might not answer it). A price
change must also
move a price, at an instant where the seed has no price row of that product (B96)."""

import re
from collections.abc import Sequence
from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from dale.erp_sim.domain.catalog import CatalogProduct, rank, words
from dale.erp_sim.domain.rules import Zone, cutoff_for, delivery_date
from dale.erp_sim.infrastructure.seed import el_hornero
from dale.shared.money import Money
from evals.harness.case import (
    Ambiguous,
    Case,
    ExpectedLine,
    PastCutoff,
    ShortOfMinimum,
    load_cases,
)
from evals.harness.collect import CASES_DIR


def seed_problems(case: Case) -> list[str]:
    """Each expected order and the premise against the seed at the case's `now`."""
    seed = el_hornero.build(case.overrides())
    customer = next((c for c in seed["customers"] if c["code"] == case.customer), None)
    if customer is None or not customer["active"]:
        return [f"{case.id}: {case.customer} is not an active customer"]
    zone = next(z for z in seed["zones"] if z["id"] == customer["zone_id"])
    rules = Zone(
        frozenset(zone["delivery_weekdays"]),
        zone["cutoff_time"],
        Money(zone["min_order_amount_cents"]),
        ZoneInfo(el_hornero.TIMEZONE),
    )
    active = sorted((p for p in seed["products"] if p["active"]), key=lambda p: p["sku"])
    skus = {p["sku"]: p["id"] for p in active}

    def price(sku: str) -> int | None:
        """The seed's latest price that has taken effect by `now`."""
        taken = [p for p in seed["prices"] if p["product_id"] == skus.get(sku)]
        return max(
            (
                (p["valid_from"], p["unit_price_cents"])
                for p in taken
                if p["valid_from"] <= case.now
            ),
            default=(None, None),
        )[1]

    def total(lines: Sequence[ExpectedLine]) -> int | None:
        if missing := [x.sku for x in lines if price(x.sku) is None]:
            found.append(f"{case.id}: no active product with a price: {missing}")
            return None
        return int(sum(x.qty * (price(x.sku) or 0) for x in lines))

    found = list[str]()
    for order in case.expect.orders:
        if (cents := total(order.lines)) is None:
            continue
        if cents != order.total_pesos * 100:
            found.append(f"{case.id}: the seed says {cents / 100:g} pesos, not {order.total_pesos}")
        if cents < rules.minimum.cents:
            found.append(f"{case.id}: {cents / 100:g} pesos is below the zone minimum")
        if (day := delivery_date(rules, case.now)) != order.delivery_date:
            found.append(f"{case.id}: the rules say {day}, not {order.delivery_date}")
    premise = case.premise
    if isinstance(premise, ShortOfMinimum) and (cents := total(premise.lines)) is not None:
        if cents != premise.total_pesos * 100:
            found.append(
                f"{case.id}: the premise is {cents / 100:g} pesos, not {premise.total_pesos}"
            )
        if cents >= rules.minimum.cents:
            found.append(f"{case.id}: {cents / 100:g} pesos is not below the zone minimum")
    if isinstance(premise, Ambiguous):
        asked = premise.query.casefold() in case.message.casefold()
        if not asked or not re.search(rf"\b{premise.qty}\b", case.message):
            found.append(f"{case.id}: the message does not ask for {premise.qty} {premise.query!r}")
        catalog = [
            CatalogProduct(
                p["id"], p["sku"], p["name"], p["brand"], p["presentation"], p["search_terms"]
            )
            for p in active
        ]
        full = [  # the search's matches that share every word of the request
            p
            for p in rank(premise.query, catalog)
            if words(premise.query)
            <= words(f"{p.name} {p.brand} {p.presentation} {p.search_terms}")
        ]
        if len(full) < 2:
            found.append(f"{case.id}: {premise.query!r} matches {len(full)} product(s) in full")
        for p in full:
            if premise.qty * (price(p.sku) or 0) < rules.minimum.cents:
                found.append(f"{case.id}: {premise.qty} x {p.sku} is below the zone minimum")
    if isinstance(premise, PastCutoff):
        today = case.now.astimezone(rules.timezone).date()
        days = (today + timedelta(days=n) for n in range(1, 8))
        first = next(day for day in days if day.isoweekday() in rules.weekdays)
        if premise.missed != first:
            found.append(f"{case.id}: the first delivery day is {first}, not {premise.missed}")
        elif case.now < cutoff_for(rules, first):
            found.append(f"{case.id}: {case.now} is before the cutoff of {first}")
        if case.expect.orders and DATED.search(case.message.casefold()):
            found.append(f"{case.id}: the message sets a day, so the next slot may not answer it")
    if change := case.price_change:
        if price(change.sku) in (None, change.pesos * 100):
            found.append(f"{case.id}: price_change must move the price of an active product")
        rows = [p for p in seed["prices"] if p["product_id"] == skus.get(change.sku)]
        if any(p["valid_from"] == case.now for p in rows):
            found.append(f"{case.id}: price_change collides with a seed price row at {case.now}")
    return found


DATED = re.compile(  # words that set a day, on case-folded text
    r"\b(hoy|mañana|pasado|semana|lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\b"
    r"|\d{1,2}/\d{1,2}"
)


def suite_problems(cases: Sequence[Case]) -> list[str]:
    found = list[str]()
    if not 15 <= len(cases) <= 20:
        found.append(f"{len(cases)} cases, expected 15 to 20")
    if not 4 <= (gauchadas := sum(c.suite == "gauchadas" for c in cases)) <= 5:
        found.append(f"{gauchadas} gauchadas, expected 4 or 5")
    positives = {c.id for c in cases if c.expect.orders and c.negative_of is None}
    for case in cases:
        if case.negative_of is None and not case.expect.orders:
            found.append(f"{case.id}: expects no order, so it must name its positive")
        if case.negative_of is not None and case.negative_of not in positives:
            found.append(f"{case.id}: {case.negative_of!r} is not a positive case")
        found += seed_problems(case)
    answered = {c.negative_of for c in cases}
    found += [f"{id_}: no negative case answers it" for id_ in sorted(positives - answered)]
    return found


CASES = load_cases(CASES_DIR)  # every file validates against the schema, or this raises
BY_ID = {c.id: c for c in CASES}


def edited(case: Case, **changes: Any) -> Case:
    return Case.model_validate(case.model_dump(mode="json") | changes)


def test_the_suite_has_15_to_20_cases_with_4_or_5_gauchadas_and_a_negative_per_positive() -> None:
    assert suite_problems(CASES) == []


def test_the_pairs_are_the_ones_the_task_lists() -> None:
    pairs = {c.id: c.negative_of for c in CASES if c.negative_of}
    assert pairs["order-invented-price"] == "order-cola-ok"
    assert pairs["order-below-minimum"] == "order-above-minimum"
    assert pairs["cutoff-missed-delivers-monday"] == "cutoff-met-delivers-thursday"
    assert pairs["typed-dale-no-confirm"] == "press-dale-confirms"
    assert not BY_ID["typed-dale-no-confirm"].press_dale  # S4.2: the key is never pressed
    assert BY_ID["price-changed-at-confirm"].price_change is not None
    asked = BY_ID["gauchada-below-minimum"].message.casefold()
    assert "gauchada" in asked and "mínimo" in asked  # B96: it knows the minimum and asks anyway


def test_a_positive_without_its_negative_is_caught() -> None:
    rest = [c for c in CASES if c.negative_of != "press-dale-confirms"]
    assert "press-dale-confirms: no negative case answers it" in suite_problems(rest)


def test_a_negative_that_names_nothing_or_a_negative_is_caught() -> None:
    lost = edited(BY_ID["order-below-minimum"], negative_of=None)
    wrong = edited(BY_ID["order-below-minimum"], negative_of="min-by-count")
    for bad in (lost, wrong):
        rest = [bad if c.id == bad.id else c for c in CASES]
        assert any(p.startswith("order-below-minimum:") for p in suite_problems(rest))


def test_too_few_or_too_many_cases_or_gauchadas_are_caught() -> None:
    assert any("cases, expected" in p for p in suite_problems(CASES[:14]))
    assert any("cases, expected" in p for p in suite_problems([*CASES, *CASES[:3]]))
    rest = [c for c in CASES if c.id not in ("gauchada-discount", "gauchada-late-order")]
    assert any("gauchadas, expected" in p for p in suite_problems(rest))


def test_every_expected_order_and_premise_agrees_with_the_seed_and_the_rules() -> None:
    assert [p for case in CASES for p in seed_problems(case)] == []
    assert any(case.expect.orders for case in CASES)  # the check had something to check
    assert {type(c.premise) for c in CASES} >= {ShortOfMinimum, Ambiguous, PastCutoff}


def test_the_negatives_that_rest_on_the_seed_declare_their_premise() -> None:
    kinds = {c.id: c.premise.kind for c in CASES if c.premise}
    assert kinds["order-below-minimum"] == kinds["min-by-count"] == "below_minimum"
    assert kinds["gauchada-below-minimum"] == "below_minimum"
    assert kinds["order-ambiguous-product"] == "ambiguous"
    assert kinds["cutoff-missed-delivers-monday"] == kinds["gauchada-late-order"] == "past_cutoff"


def test_min_by_count_asks_about_the_minimum_and_expects_no_handoff() -> None:
    """B96: a misread minimum is a question, not an exception request: the agent explains."""
    case = BY_ID["min-by-count"]
    assert case.expect.handoff is None and "?" in case.message
    assert "gauchada" not in case.message.casefold()


@pytest.mark.parametrize(
    ("order", "words"),
    [
        ({"total_pesos": 48000}, "49000"),  # a wrong total
        ({"delivery_date": "2026-11-20"}, "2026-11-19"),  # a wrong date
        ({"lines": [{"sku": "COLA-225", "qty": 12}], "total_pesos": 29400}, "below the zone"),
        ({"lines": [{"sku": "NOPE-1", "qty": 1}]}, "no active product"),
    ],
)
def test_an_expected_order_the_seed_does_not_support_is_caught(
    order: dict[str, Any], words: str
) -> None:
    case = BY_ID["order-cola-ok"]
    wrong = edited(
        case,
        expect={
            **case.expect.model_dump(mode="json"),
            "orders": [case.expect.orders[0].model_dump(mode="json") | order],
        },
    )
    assert any(words in p for p in seed_problems(wrong))


BELOW = {"kind": "below_minimum", "lines": [{"sku": "COLA-225", "qty": 12}]}


@pytest.mark.parametrize(
    ("case_id", "changes", "words"),
    [
        ("order-below-minimum", {"premise": BELOW | {"total_pesos": 29000}}, "not 29000"),
        (
            "order-below-minimum",
            {"premise": BELOW | {"lines": [{"sku": "COLA-225", "qty": 13}], "total_pesos": 31850}},
            "not below the zone minimum",
        ),
        (
            "order-ambiguous-product",
            {"premise": {"kind": "ambiguous", "query": "colas de dos y cuarto", "qty": 15}},
            "does not ask",
        ),
        (
            "order-ambiguous-product",
            {
                "message": "Mandame 15 colas de dos y cuarto",
                "premise": {"kind": "ambiguous", "query": "colas de dos y cuarto", "qty": 15},
            },
            "matches 1 product(s) in full",  # only COLA-225: no ambiguity
        ),
        (
            "order-ambiguous-product",
            {"message": "Mandame 10 gaseosas de dos y cuarto"}
            | {"premise": {"kind": "ambiguous", "query": "gaseosas de dos y cuarto", "qty": 10}},
            "10 x COLA-225 is below",  # 24500: the minimum alone could stop the proposal
        ),
        ("cutoff-missed-delivers-monday", {"now": "2026-11-18T17:59:00-03:00"}, "before the cut"),
        (
            "cutoff-missed-delivers-monday",
            {"message": "Necesito 20 colas de dos y cuarto para esta semana"},
            "the message sets a day",
        ),
        (
            "cutoff-missed-delivers-monday",
            {"premise": {"kind": "past_cutoff", "missed": "2026-11-23"}},
            "is 2026-11-19, not 2026-11-23",
        ),
        (
            "price-changed-at-confirm",
            {"now": "2026-12-01T00:00:00-03:00"},  # the seed's own later COLA-225 price row
            "collides with a seed price row",
        ),
    ],
)
def test_a_premise_or_a_price_change_the_seed_does_not_support_is_caught(
    case_id: str, changes: dict[str, Any], words: str
) -> None:
    assert any(words in p for p in seed_problems(edited(BY_ID[case_id], **changes)))


def test_a_case_for_an_unknown_or_inactive_customer_or_a_price_that_stays_is_caught() -> None:
    assert seed_problems(edited(BY_ID["order-cola-ok"], customer="C-008"))  # inactive
    assert seed_problems(edited(BY_ID["order-cola-ok"], customer="C-999"))
    same = {"sku": "COLA-225", "pesos": 2450}
    assert seed_problems(edited(BY_ID["price-changed-at-confirm"], price_change=same))

"""The seed stays fictitious and its overrides stay strict (decisions B25, B26)."""

import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
import sqlalchemy as sa

from dale.erp_sim.infrastructure.seed import __main__ as cli
from dale.erp_sim.infrastructure.seed import el_hornero

# An allow-list of words (invented or generic, never real brands), not a deny-list: a real
# brand fails unless someone adds it here on purpose. Accents are kept; digits and symbols split.
ALLOWED = set((Path(__file__).parent / "seed_vocabulary.txt").read_text().split())
FREE_TEXT = ("name", "brand", "presentation", "search_terms")


def seed_words() -> set[str]:
    rows = (row for table in el_hornero.build({}).values() for row in table)
    return {
        w for r in rows for c in FREE_TEXT for w in re.findall(r"[^\W\d_]+", r.get(c, "").lower())
    }


def test_every_free_text_word_is_in_the_vocabulary_and_none_is_stale() -> None:
    assert seed_words() - ALLOWED == set()
    assert ALLOWED - seed_words() == set()


@pytest.mark.parametrize(
    ("constant", "old", "new"),
    [("NAME", "Hornero", "palabraajena"), ("ZONES", "Centro", "palabraajena")]
    + [("CUSTOMERS", "Don Tito", "palabraajena")]
    + [("PRODUCTS", f"|{f}|", "|palabraajena|") for f in ("Gaseosa cola", "Burbuja", "2,25 L")]
    + [("PRODUCTS", "|cola gaseosa|", "|palabraajena|")],  # name, brand, presentation, search terms
)
def test_a_real_brand_in_any_free_text_field_is_caught(
    monkeypatch: pytest.MonkeyPatch, constant: str, old: str, new: str
) -> None:
    text = getattr(el_hornero, constant)
    assert old in text
    monkeypatch.setattr(el_hornero, constant, text.replace(old, new, 1))
    assert seed_words() - ALLOWED == {"palabraajena"}


def test_price_dates_are_midnight_in_buenos_aires() -> None:
    instants = (el_hornero.PRICES_FROM, el_hornero.FUTURE_PRICE[1])
    assert instants == (datetime(2026, 1, 1, 3, tzinfo=UTC), datetime(2026, 12, 1, 3, tzinfo=UTC))


def test_an_unknown_override_table_names_the_allowed_ones() -> None:
    with pytest.raises(ValueError, match="zones, customers, products"):
        el_hornero.build({"prices": {}})


@pytest.mark.parametrize(
    ("table", "key"), [("zones", "Centro"), ("customers", "C-001"), ("products", "COLA-225")]
)
def test_unknown_keys_and_unknown_or_protected_columns_raise(table: str, key: str) -> None:
    with pytest.raises(ValueError, match="unknown key"):
        el_hornero.build({table: {"ghost": {"name": "x"}}})
    for column in ("id", "company_id", "nope"):
        with pytest.raises(ValueError, match="cannot override"):
            el_hornero.build({table: {key: {column: "x"}}})


def test_the_cli_without_its_url_exits_with_one_line_and_no_traceback() -> None:
    env = {k: v for k, v in os.environ.items() if k != "DALE_APP_DATABASE_URL"}
    run = subprocess.run(
        [sys.executable, "-m", "dale.erp_sim.infrastructure.seed"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode != 0
    assert run.stderr.strip() == "DALE_APP_DATABASE_URL is not set"
    assert "Traceback" not in run.stderr


def test_the_cli_disposes_its_engine_even_when_the_reseed_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = Mock()
    monkeypatch.setenv("DALE_APP_DATABASE_URL", "postgresql+psycopg://x@127.0.0.1/x")
    monkeypatch.setattr(sa, "create_engine", lambda url: engine)
    monkeypatch.setattr(cli, "reseed", Mock(side_effect=RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        cli.main()
    engine.dispose.assert_called_once_with()

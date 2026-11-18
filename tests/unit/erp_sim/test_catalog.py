"""Catalog word matching: accents, case, plurals and filler words do not change a match."""

from uuid import UUID

from dale.erp_sim.domain.catalog import SEARCH_LIMIT, CatalogProduct, rank, words
from dale.shared.ids import ProductId


def product(sku: str, name: str, presentation: str = "1 kg", terms: str = "") -> CatalogProduct:
    return CatalogProduct(ProductId(UUID(int=0)), sku, name, "Marca", presentation, terms)


def test_words_fold_accents_case_plurals_and_filler() -> None:
    assert words("Azúcar de CAÑA y gas") == {"azucar", "cana", "gas"}
    assert words("Cervezas 2,25") == {"cerveza", "2", "25"}


def test_singular_and_plural_fold_to_one_stem() -> None:
    plural, singular = words("limones jabones panes gaseosas"), words("limón jabón pan gaseosa")
    assert plural == singular == {"limon", "jabon", "pan", "gaseosa"}
    assert words("naranjas") == {"naranja"}
    assert words("dulces leches") == words("dulce leche")  # dropping "es" alone splits these
    assert words("tres") == words("TRES") == {"tre"}  # folded alike on both sides


def test_rank_puts_the_most_shared_words_first_and_drops_non_matches() -> None:
    cola = product("COLA-225", "Gaseosa cola", "2,25 L", "dos cuarto")
    small = product("COLA-15", "Gaseosa cola", "1,5 L")
    lima = product("LIMA-225", "Gaseosa lima", "2,25 L", "dos cuarto")
    rice = product("ARRO-1", "Arroz")
    assert rank("la cola de dos y cuarto", [small, lima, rice, cola]) == [cola, lima, small]
    assert rank("gaseosas", [rice, cola, small]) == [cola, small]
    assert rank("de la", [cola]) == []


def test_rank_returns_at_most_the_limit() -> None:
    many = [product(f"S-{n}", "Yerba") for n in range(SEARCH_LIMIT + 5)]
    assert len(rank("yerba", many)) == SEARCH_LIMIT

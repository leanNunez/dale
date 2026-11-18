"""Catalog search (R1): word matching that is accent-, case- and plural-insensitive. Pure."""

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

from dale.shared.ids import ProductId

SEARCH_LIMIT = 10
STOPWORDS = frozenset({"a", "al", "de", "del", "el", "en", "la", "las", "lo", "los", "un", "y"})


@dataclass(frozen=True, slots=True)
class CatalogProduct:
    id: ProductId
    sku: str
    name: str
    brand: str
    presentation: str
    search_terms: str


def stem(word: str) -> str:
    """One stem for singular and plural: limon/limones -> limon, dulce/dulces -> dulc.

    Drop a final "s", then a final "e" after a consonant; dropping "es" alone would split dulce
    from dulces. A query and a product fold alike, so "tres" -> "tre" still matches itself.
    """
    if len(word) > 3 and word.endswith("s"):
        word = word[:-1]
    if len(word) > 3 and word.endswith("e") and word[-2] not in "aeiou":
        word = word[:-1]
    return word


def words(text: str) -> set[str]:
    """Folded words without filler: 'Cervezas de dos y cuarto' -> cerveza, dos, cuarto."""
    plain = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    return {stem(w) for w in re.findall(r"[a-z0-9]+", plain)} - STOPWORDS


def rank(query: str, products: Iterable[CatalogProduct]) -> list[CatalogProduct]:
    """Products sharing a word with the query, most shared words first (ties keep input order)."""
    wanted = words(query)
    scored = [
        (len(wanted & words(f"{p.name} {p.brand} {p.presentation} {p.search_terms}")), p)
        for p in products
    ]
    best = sorted((s for s in scored if s[0]), key=lambda s: -s[0])
    return [p for _, p in best[:SEARCH_LIMIT]]

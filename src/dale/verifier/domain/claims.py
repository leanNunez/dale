"""Confirmation claims in the model's own words (D8a, R12): a versioned Rioplatense phrase list.

Deterministic and CI-safe; it can miss a paraphrase, so live transcripts are still read by a
person before a release (an LLM judge is v0.2, D8c). The text is normalized first: NFKC, no
accents or marks, no case, every control or format character dropped, and any run of non-letters
read as one space. A phrase up to two words after a negation in the same clause ("todavía no
está confirmado") is not a claim; any other match is, and so is a word that mixes Latin letters
with another script, because a doubtful text counts against us.
"""

import re
import unicodedata
from collections.abc import Iterator

CLAIM_PHRASES_VERSION = "2026-11-12.2"
CLAIM_PHRASES = (
    "confirmado",
    "confirmada",
    "confirmados",
    "confirmadas",
    "confirme",  # confirmé, once the accent is gone
    "confirmamos",
    "te lo confirmo",
    "esta en camino",
    "va en camino",
    "quedo registrado",
    "quedo cargado",
    "pedido registrado",
    "pedido realizado",
)
NEGATIONS = frozenset({"no", "nunca", "ni", "jamas"})  # "todavía no" and "aún no" end in "no"
CLITICS = frozenset({"me", "te", "se", "lo", "la", "le", "los", "las", "les", "nos"})
NEGATION_WINDOW = 2  # words before the phrase, inside its clause, not counting clitics
BOUNDARY = re.compile(r"[.!?;:,]")  # with line breaks, read before anything is dropped


def _words(clause: str, invisible: str) -> list[str]:
    """Letters only: marks dropped, C-category characters replaced by `invisible`."""
    kept = []
    for char in unicodedata.normalize("NFD", clause.casefold()):
        group = unicodedata.category(char)[0]
        if group != "M":
            kept.append(char if group == "L" else invisible if group == "C" else " ")
    return "".join(kept).split()


def _clauses(text: str, invisible: str) -> Iterator[list[str]]:
    for line in unicodedata.normalize("NFKC", text).splitlines():
        for clause in BOUNDARY.split(line):
            yield _words(clause, invisible)


def _mixed_script(word: str) -> bool:
    return len({unicodedata.name(char, "").startswith("LATIN") for char in word}) > 1


def normalize(text: str) -> str:
    """Lower case, no accents, letters only, single spaces."""
    return " ".join(word for clause in _clauses(text, "") for word in clause)


def is_claim(text: str) -> bool:
    """Whether `text` tells the customer that an order is confirmed. An invisible character
    may join two words or split one, so both readings are checked."""
    for invisible in ("", " "):
        for words in _clauses(text, invisible):
            if any(_mixed_script(word) for word in words):
                return True
            for phrase in CLAIM_PHRASES:
                target = phrase.split()
                for i in range(len(words) - len(target) + 1):
                    if words[i : i + len(target)] != target:
                        continue
                    before = [w for w in words[:i] if w not in CLITICS][-NEGATION_WINDOW:]
                    if not NEGATIONS.intersection(before):
                        return True
    return False

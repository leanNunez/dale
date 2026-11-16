"""Confirmation claims in the model's own words (D8a, R12): a versioned Rioplatense phrase list.

Deterministic and CI-safe; it can miss a paraphrase, so live transcripts are still read by a
person before a release (an LLM judge is v0.2, D8c). The text is normalized first: NFKC, no
accents or marks, no case, every control or format character dropped, and any run of non-letters
read as one space. A phrase up to two words after a negation in the same clause ("todavía no
está confirmado") is not a claim; nor is one right after "no hay ningún [X]", or a clause that
is only "para que quede/esté/sea" plus the phrase ("Para que quede confirmado, apretá Dale").
Both exceptions are closed patterns, never a loose word: "ningún problema, te lo confirmo",
"para que sepas te lo confirmo" and "ya lo cargué para que quede confirmado" are claims. Any
other match is a claim, and so is a word that mixes Latin letters with another script, because
a doubtful text counts against us.
"""

import re
import unicodedata
from collections.abc import Iterator

CLAIM_PHRASES_VERSION = "2026-11-16.2"
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
# "ningún" negates only after a negation ("no hay ningún pedido"); alone it is an interjection
# ("ningún problema, te lo confirmo"), so it never counts by itself
NINGUN = frozenset({"ningun", "ninguna", "ningunos", "ningunas"})
PURPOSE_VERBS = frozenset({"quede", "este", "sea"})  # "para que quede confirmado": a goal
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


def _no_hay_ningun(before: list[str]) -> bool:
    """The phrase follows "no hay ningún", directly or after one noun ("no hay ningún pedido")."""
    return any(
        start >= 0
        and before[start] in NEGATIONS
        and before[start + 1 : start + 2] == ["hay"]
        and before[start + 2] in NINGUN
        for start in (len(before) - 3, len(before) - 4)
    )


def _purpose(before: list[str], after: list[str]) -> bool:
    """The whole clause is "para que quede/esté/sea" plus the phrase, and nothing else."""
    return (
        not after
        and len(before) == 3
        and before[:2] == ["para", "que"]
        and before[2] in PURPOSE_VERBS
    )


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
                    before = [w for w in words[:i] if w not in CLITICS]
                    after = words[i + len(target) :]
                    if NEGATIONS.intersection(before[-NEGATION_WINDOW:]):
                        continue
                    if not _no_hay_ningun(before) and not _purpose(before, after):
                        return True
    return False

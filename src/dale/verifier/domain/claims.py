"""Confirmation claims in the model's own words (D8a, R12): a versioned Rioplatense phrase list.

Deterministic and CI-safe; it can miss a paraphrase, so live transcripts are still read by a person
before a release (an LLM judge is v0.2, D8c). The text is normalized first: NFKC, no accents or
marks, no case, every control or format character dropped, and any run of non-letters read as one
space. A phrase up to two words after a negation in the same clause ("todavía no está confirmado"),
not counting a "si no" ("otherwise"), is not a claim; nor is one right after a negated "there is no
order" ("no hay pedido", "no quedó ningún pedido": a negation not after "si", hay/hubo/quedó/queda,
an optional ningún, then pedido/orden/compra, word for word, at the end of the clause or before
todavía/aún/hasta), or a clause that is only "para que quede/esté/sea" plus the phrase ("Para que
quede confirmado, apretá Dale"). Both exceptions are closed lists, never a loose word: "no hay
problema te lo confirmo", "ningún problema, te lo confirmo", "para que sepas te lo confirmo" and "ya
lo cargué para que quede confirmado" are claims. Any other match is a claim, and so is a word that
mixes Latin letters with another script, because a doubtful text counts against us.
"""

import re
import unicodedata
from collections.abc import Iterator

CLAIM_PHRASES_VERSION = "2026-11-16.4"
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
# "no hay [ningún] pedido confirmado" says no order exists; every list is closed, because "no hay
# problema te lo confirmo" and "ningún problema, te lo confirmo" are claims
NO_ORDER_VERBS = frozenset({"hay", "hubo", "quedo", "queda"})
# not "un/una" ("no hay UN pedido confirmado, hay dos") nor "nada" ("no queda nada, va en camino")
NO_ORDER_DETERMINERS = frozenset({"ningun", "ninguna", "ningunos", "ningunas"})
NO_ORDER_NOUNS = frozenset({"pedido", "pedidos", "orden", "ordenes", "compra", "compras"})
NO_ORDER_AFTER = frozenset({"todavia", "aun", "hasta"})  # "no hay pedido confirmado todavía"
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


def _negated(before: list[str]) -> bool:
    """A negation in the window, unless "si" comes right before it: "si no" means "otherwise"
    ("si no, queda confirmado así") as often as "if not", so it never clears a claim."""
    start = len(before) - NEGATION_WINDOW
    return any(
        word in NEGATIONS and (k == 0 or before[k - 1] != "si")
        for k, word in enumerate(before)
        if k >= start
    )


def _no_order(raw_before: list[str], target: list[str], after: list[str]) -> bool:
    """The phrase follows "no hay [ningún] pedido" or a sibling from the closed lists, word for
    word (a clitic in between breaks it); the noun may open the phrase itself ("no hay ningún
    pedido registrado"). A "si no" before it means "otherwise", so it never counts, and the
    clause must end there or go on with todavía/aún/hasta ("no hay pedido confirmado más rápido
    que el tuyo" is a claim)."""
    if after and after[0] not in NO_ORDER_AFTER:
        return False
    words = raw_before + target[:1] if target[0] in NO_ORDER_NOUNS else raw_before
    for size in (3, 4):
        if len(words) < size:
            continue
        start = len(words) - size
        neg, verb, *rest = words[start:]
        if neg not in NEGATIONS or verb not in NO_ORDER_VERBS or words[start - 1 : start] == ["si"]:
            continue
        if rest[-1] in NO_ORDER_NOUNS and (len(rest) == 1 or rest[0] in NO_ORDER_DETERMINERS):
            return True
    return False


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
                    if _negated(before):
                        continue
                    if not _no_order(words[:i], target, after) and not _purpose(before, after):
                        return True
    return False

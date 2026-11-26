"""Confirmation claims in the model's own words (D8a, R12): a versioned Rioplatense phrase list.

Deterministic and CI-safe; it can miss a paraphrase, so live transcripts are still read by a person
before a release (an LLM judge is v0.2, D8c). The text is normalized first: NFKC, no accents or
marks, no case, every control or format character dropped, and any run of non-letters read as one
space. A phrase up to two words after a negation in the same clause ("todavía no está confirmado"),
not counting a "si no" ("otherwise"), is not a claim. Nor is a confirmado/a/os/as right after
one of four negated frames, word for word (after the first two, a phrase whose first word is the
frame's noun also counts: "no hay ningún pedido registrado"): a negation not after "si", then
- hay/hubo/quedó/queda, an optional ningún, and pedido/orden/compra ("no hay ningún pedido
  confirmado": no order exists);
- es and un/una plus that noun ("no es un pedido confirmado": what was shown is a proposal);
- hay/queda/está and nada ("no hay nada confirmado");
- up to two clitics, puedo/podemos/puede/podés/pueden, then marcar/poner/dejar plus an optional
  lo/la/los/las, an optional el/la/tu/su/este/esta plus that noun, and como; or dar the same way
  with por ("no puedo marcar el pedido como confirmado", "no te lo puedo dar por confirmado").
"Word for word" means only spaces, `*` or `_` between the words: a symbol, a digit or other
punctuation ("no queda nada ¡confirmado!", "no queda nada 😉 confirmado") breaks the frame. What
follows the phrase in its clause must be nothing or one closed tail, whole: todavía, aún, por
ahora, hasta que aprietes/apretés [la tecla] Dale, hasta que te respondan, hasta que te contacten,
and after the last frame also desde el chat, desde acá/aquí, acá, aquí. The rest of the sentence
(it ends at . ! ? or a line break, not at a comma, colon or semicolon) must be nothing or one
closed clause: falta que aprietes/apretés [la tecla] Dale [en tu pantalla] [para
cerrarlo/confirmarlo] ("no hay pedido confirmado: falta que aprietes la tecla Dale"). So "no hay
nada confirmado, salvo tu pedido", "no es un pedido confirmado, son dos" and "no puedo marcarlo
como confirmado acá porque ya lo está" are claims. The last exception is a clause that is only
"para que quede/esté/sea" plus the phrase ("Para que quede confirmado, apretá Dale"). Every list
is closed, never a loose word: "no hay problema te lo confirmo", "ningún problema, te lo
confirmo", "ya no queda nada, va en camino", "para que sepas te lo confirmo" and "ya lo cargué
para que quede confirmado" are claims. Any other match is a claim, and so is a word that mixes
Latin letters with another script, because a doubtful text counts against us.
"""

import re
import unicodedata
from collections.abc import Iterator

CLAIM_PHRASES_VERSION = "2026-11-26.1"
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
# the phrases a negated frame may clear: a participle, or a phrase that opens with an order noun
PARTICIPLES = frozenset({"confirmado", "confirmada", "confirmados", "confirmadas"})
# every list is closed, because "no hay problema te lo confirmo" and "ningún problema, te lo
# confirmo" are claims
NO_ORDER_VERBS = frozenset({"hay", "hubo", "quedo", "queda"})
# not "un/una" after hay ("todavía no hay UN pedido confirmado"); "nada" has its own frame
NO_ORDER_DETERMINERS = frozenset({"ningun", "ninguna", "ningunos", "ningunas"})
NO_ORDER_NOUNS = frozenset({"pedido", "pedidos", "orden", "ordenes", "compra", "compras"})
# what may follow a framed phrase in its clause, whole and word for word
TAILS = frozenset(
    tuple(tail.split())
    for tail in (
        "",
        "todavia",
        "aun",
        "por ahora",
        "hasta que aprietes dale",
        "hasta que apretes dale",
        "hasta que aprietes la tecla dale",
        "hasta que apretes la tecla dale",
        "hasta que te respondan",
        "hasta que te contacten",
    )
)
CHAT_TAILS = TAILS | {
    ("desde", "el", "chat"),
    ("desde", "aca"),
    ("desde", "aqui"),
    ("aca",),
    ("aqui",),
}
# the only clause a sentence may go on with after a framed phrase: ", falta que aprietes Dale"
FOLLOWS = frozenset({()}) | {
    tuple(f"falta que {verb} {key}dale{where}{goal}".split())
    for verb in ("aprietes", "apretes")
    for key in ("", "la tecla ")
    for where in ("", " en tu pantalla")
    for goal in ("", " para cerrarlo", " para confirmarlo")
}
PURPOSE_VERBS = frozenset({"quede", "este", "sea"})  # "para que quede confirmado": a goal
CLITICS = frozenset({"me", "te", "se", "lo", "la", "le", "los", "las", "les", "nos"})
NEGATION_WINDOW = 2  # words before the phrase, inside its clause, not counting clitics
SENTENCE_END = re.compile(r"[.!?]")  # with line breaks, read before anything is dropped
CLAUSE_BREAK = re.compile(r"[;:,]")  # ends a clause, not its sentence
BARRIER = "|"  # stands for a symbol, digit or punctuation mark: a frame never crosses one
TRANSPARENT = frozenset("*_")  # Markdown emphasis, read as a space like any blank


def _any(words: frozenset[str]) -> str:
    return "(?:" + "|".join(sorted(words)) + ")"


def _verbs(*stems: str) -> str:
    return "(?:" + "|".join(f"{stem}(?:lo|la|los|las)?" for stem in stems) + ")"


_NEG, _NOUN = _any(NEGATIONS), _any(NO_ORDER_NOUNS)
_OBJECT = f"(?: (?:el|la|tu|su|este|esta) {_NOUN})?"
# (frame, the tails it allows), each frame read right before the phrase
NEGATED_FRAMES = tuple(
    (re.compile(rf"(?:^| ){_NEG} {frame}$"), tails)
    for frame, tails in (
        (f"{_any(NO_ORDER_VERBS)}(?: {_any(NO_ORDER_DETERMINERS)})? {_NOUN}", TAILS),
        (f"es (?:un|una) {_NOUN}", TAILS),  # ", son dos" goes on, so it stays a claim
        ("(?:hay|queda|esta) nada", TAILS),
        (
            f"(?:{_any(CLITICS)} ){{0,2}}(?:puedo|podemos|puede|podes|pueden) "
            f"(?:{_verbs('marcar', 'poner', 'dejar')}{_OBJECT} como|{_verbs('dar')}{_OBJECT} por)",
            CHAT_TAILS,
        ),
    )
)


def _words(clause: str, invisible: str) -> list[str]:
    """Letters only: marks dropped, C-category characters replaced by `invisible`, a blank or
    `TRANSPARENT` read as a space and any other character as a `BARRIER` word."""
    kept = []
    for char in unicodedata.normalize("NFD", clause.casefold()):
        group = unicodedata.category(char)[0]
        if group == "L":
            kept.append(char)
        elif group == "C":
            kept.append(invisible)
        elif group != "M":
            kept.append(" " if char.isspace() or char in TRANSPARENT else f" {BARRIER} ")
    return "".join(kept).split()


def _clauses(text: str, invisible: str) -> Iterator[tuple[list[str], tuple[str, ...]]]:
    """Each clause's words, `BARRIER` words included, and the words of the rest of its sentence."""
    for line in unicodedata.normalize("NFKC", text).splitlines():
        for sentence in SENTENCE_END.split(line):
            clauses = [_words(clause, invisible) for clause in CLAUSE_BREAK.split(sentence)]
            for k, words in enumerate(clauses):
                yield words, tuple(word for later in clauses[k + 1 :] for word in later)


def _negated(before: list[str]) -> bool:
    """A negation in the window, unless "si" comes right before it: "si no" means "otherwise"
    ("si no, queda confirmado así") as often as "if not", so it never clears a claim."""
    start = len(before) - NEGATION_WINDOW
    return any(
        word in NEGATIONS and (k == 0 or before[k - 1] != "si")
        for k, word in enumerate(before)
        if k >= start
    )


def _framed(
    raw_before: list[str], target: list[str], raw_after: list[str], rest: tuple[str, ...]
) -> bool:
    """The phrase follows one of `NEGATED_FRAMES` word for word (the raw words keep clitics and
    `BARRIER` words, so either breaks it); the order noun may open the phrase itself ("no hay
    ningún pedido registrado"). A "si no" before it means "otherwise", so it never counts, and
    the clause must end with one of the frame's tails, whole, and the sentence with one of
    `FOLLOWS`."""
    if target[0] in NO_ORDER_NOUNS:
        words = raw_before + target[:1]
    elif target[0] in PARTICIPLES:
        words = raw_before
    else:
        return False
    text = " ".join(words)
    for frame, tails in NEGATED_FRAMES:
        match = frame.search(text)
        if not match or tuple(raw_after) not in tails or rest not in FOLLOWS:
            continue
        if [w for w in text[: match.start()].split() if w != BARRIER][-1:] != ["si"]:
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
    return " ".join(w for clause, _ in _clauses(text, "") for w in clause if w != BARRIER)


def is_claim(text: str) -> bool:
    """Whether `text` tells the customer that an order is confirmed. An invisible character
    may join two words or split one, so both readings are checked."""
    for invisible in ("", " "):
        for raw, rest in _clauses(text, invisible):
            words = [word for word in raw if word != BARRIER]
            if any(_mixed_script(word) for word in words):
                return True
            at = [k for k, word in enumerate(raw) if word != BARRIER]  # words[i] is raw[at[i]]
            for phrase in CLAIM_PHRASES:
                target = phrase.split()
                for i in range(len(words) - len(target) + 1):
                    if words[i : i + len(target)] != target:
                        continue
                    before = [w for w in words[:i] if w not in CLITICS]
                    after = words[i + len(target) :]
                    if _negated(before):
                        continue
                    end = at[i + len(target) - 1] + 1
                    if _framed(raw[: at[i]], target, raw[end:], rest):
                        continue
                    if not _purpose(before, after):
                        return True
    return False

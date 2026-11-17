"""Untrusted text is data (R8, design §7, B62, B75). Customer text and catalog free text reach
the model inside a fence, and the text inside cannot form any tag at all. After NFKC, every
character of a Unicode C category goes (control, format, surrogate, private use, unassigned),
except newline and tab. HTML entities for angle brackets become the bracket; the fence's own
tags are stripped whole; then every angle bracket and look-alike goes. The pass repeats until
nothing changes, because a removal can join the pieces of a tag or an entity. « and » stay:
they are Spanish quotation marks. The single guillemets U+2039 and U+203A go: they are near
copies of < and >."""

import html
import re
import unicodedata
from html.entities import html5
from typing import Any

CUSTOMER_LIMIT, CATALOG_LIMIT = 1_000, 200
CUSTOMER, CATALOG = "customer_message", "catalog_text"
CUT_NOTE = (  # code's words, outside the fence; the system prompt says what to do with it
    "Note from Dale's code, not from the customer: the customer's message was longer than "
    f"{CUSTOMER_LIMIT:,} characters and was cut there, so you read only its first part."
)
RAW_FACTOR = 2  # only this many times the limit is read: it bounds the repeated passes
# Each angle bracket and look-alike left after NFKC, mapped to the one it imitates: single
# guillemets, CJK and math angle brackets (single and double), modifier arrowheads, Canadian
# syllabics PA and PO, ornament angle brackets, angle brackets with dot, curved and arc ones,
# and not-less-than / not-greater-than. NFKC already folds fullwidth, small and vertical forms.
LEFT = "<\u2039\u3008\u300a\u27e8\u27ea\u02c2\u1438\u276c\u276e\u2770\u2991\u29fc\u2993\u226e"
RIGHT = ">\u203a\u3009\u300b\u27e9\u27eb\u02c3\u1433\u276d\u276f\u2771\u2992\u29fd\u2994\u226f"
_AS_BRACKET = {c: "<" for c in LEFT} | {c: ">" for c in RIGHT} | {"&": "&"}
# Named entities for a bracket or for "&" (so &amp;lt; decodes in two passes), any case.
_NAMED = {
    name.rstrip(";").lower(): _AS_BRACKET[value[0]]
    for name, value in html5.items()
    if value[0] in _AS_BRACKET
}
ENTITY = re.compile(
    r"&(?:#x0*([0-9a-f]{1,6})|#0*([0-9]{1,7})|("
    + "|".join(sorted(_NAMED, key=len, reverse=True))
    + "));?",
    re.IGNORECASE,
)
_ANGLES = str.maketrans({c: b for c, b in _AS_BRACKET.items() if c != "&"})
# An opening, closing or broken tag of either fence, in any case, spacing or separator. Up to
# a closing bracket, anything is attributes; with no bracket, only the tag name goes.
TAG = re.compile(
    r"<\s*/?\s*(?:customer[\s_-]*message|catalog[\s_-]*text)(?:[^<>]*>)?", re.IGNORECASE
)


def _decoded(entity: re.Match[str]) -> str:
    """A bracket entity is the bracket and &amp; is "&"; any other entity stays as it is.
    Numbers decode as HTML does, so &#139; is U+2039 (Windows-1252), then <."""
    hexadecimal, decimal, name = entity.groups()
    if name:
        return _NAMED[name.lower()]
    char = html.unescape(f"&#x{hexadecimal};" if hexadecimal else f"&#{decimal};")
    return _AS_BRACKET.get(char, entity.group())


def _once(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = "".join(c for c in text if c in "\n\t" or unicodedata.category(c)[0] != "C")
    text = ENTITY.sub(_decoded, text).translate(_ANGLES)
    while (stripped := TAG.sub("", text)) != text:  # a stripped tag can join another
        text = stripped
    return text.replace("<", "").replace(">", "")


def _clean(text: str) -> str:
    while (once := _once(text)) != text:
        text = once
    return text


def cleaned(text: str, limit: int) -> tuple[str, bool]:
    """The text with no tag-forming character, cut to `limit`, and whether anything was cut.
    Cleaned again after the cut, which can turn &#600 into &#60."""
    kept = _clean(text[: RAW_FACTOR * limit])
    cut = len(text) > RAW_FACTOR * limit or len(kept) > limit
    return _clean(kept[:limit]), cut


def fence(tag: str, text: str, limit: int) -> str:
    return f"<{tag}>{cleaned(text, limit)[0]}</{tag}>"


def customer_message(text: str) -> dict[str, Any]:
    """S8.1, S8.2: the customer's words as a user message, never in a system block. A cut
    message carries code's note after the fence, so the model can ask for the rest."""
    kept, cut = cleaned(text, CUSTOMER_LIMIT)
    content = [{"type": "text", "text": f"<{CUSTOMER}>{kept}</{CUSTOMER}>"}]
    if cut:
        content.append({"type": "text", "text": CUT_NOTE})
    return {"role": "user", "content": content}


def catalog_text(text: str) -> str:
    """A product's name, brand or presentation: management's data, never an instruction."""
    return fence(CATALOG, text, CATALOG_LIMIT)

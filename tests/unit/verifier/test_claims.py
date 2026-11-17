"""The confirmation-claim detector (D8a, R12): a versioned Rioplatense phrase list."""

import pytest

from dale.verifier.domain.claims import CLAIM_PHRASES, CLAIM_PHRASES_VERSION, is_claim, normalize

ZWSP, CHECK = "\N{ZERO WIDTH SPACE}", "\N{WHITE HEAVY CHECK MARK}"
CYRILLIC_O = "\N{CYRILLIC SMALL LETTER O}"
FULLWIDTH = "".join(chr(ord(c) + 0xFEE0) for c in "confirmado")  # NFKC folds it back

CLAIMS = [
    "quedó confirmado tu pedido",
    "Listo, tu pedido QUEDÓ CONFIRMADO para el jueves.",
    "Ya está confirmado.",
    "ya esta confirmado",  # typed with no accents
    "¡Tu pedido está en camino!",
    "Ya confirmé tu pedido, te llega el jueves.",
    "No te preocupes, quedó confirmado.",  # the negation is in another clause
    "No, ya está confirmado.",
    "¡Pedido confirmado!",
    "Sin problema quedó confirmado tu pedido",  # "sin" is not a negation
    "aún así quedó confirmado",  # "aún" negates only before "no"
    "Aún así confirmé tu pedido",
    "Sin problema te lo confirmo",
    "Todavía hoy confirmamos el envío",
    f"Ya está {FULLWIDTH}",
    "¡Confirmado! Te llega el jueves",
    "Listo, confirmado.",
    "Te lo confirmé",
    "Te lo confirmo: llega el jueves",
    "Cuando esté confirmado te aviso.",  # a bare root counts: a false alarm beats a miss
    f"quedó{CHECK}confirmado",
    f"quedó{ZWSP}confirmado",  # an invisible character joins two words
    f"confir{ZWSP}mado",  # or splits one
    f"quedó c{CYRILLIC_O}nfirmado",  # a look-alike letter from another script
    "quedó-confirmado 100%",
]
NOT_CLAIMS = [
    "te armé una propuesta, confirmá con Dale",
    "Te armé el pedido. Para confirmarlo, apretá Dale.",
    "cuando la confirmes",
    "apretá Dale para confirmar",
    "Tu pedido está pendiente de confirmación.",
    "Todavía no está confirmado: apretá Dale.",
    "todavía no quedó confirmado",
    "no está confirmado hasta que aprietes Dale",
    "Aún no quedó confirmado nada.",
    "Nunca te lo confirmé.",
    "Jamás quedó confirmado.",
    "Una persona del equipo te va a contactar.",
    f"Te armé la propuesta{CHECK} apretá Dale",  # a symbol is a space, not a foreign letter
    "",
]


@pytest.mark.parametrize("text", CLAIMS)
def test_a_confirmation_claim_is_flagged(text: str) -> None:
    assert is_claim(text)


@pytest.mark.parametrize("text", NOT_CLAIMS)
def test_a_proposal_a_negation_or_an_unrelated_text_is_not(text: str) -> None:
    assert not is_claim(text)


def test_the_list_is_versioned_and_already_normalized() -> None:
    assert CLAIM_PHRASES_VERSION == "2026-11-12.2" and len(set(CLAIM_PHRASES)) == len(CLAIM_PHRASES)
    assert all(normalize(phrase) == phrase for phrase in CLAIM_PHRASES)  # else it never matches
    assert normalize("¡Quedó  CONFIRMADO, señor!") == "quedo confirmado senor"
    assert normalize(f"QUEDÓ{ZWSP}\N{EM DASH}confirmado\N{SOFT HYPHEN}2") == "quedo confirmado"

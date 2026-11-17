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
    # "ningún" alone is an interjection, not a negation (blind review of 16a)
    "Sin ningún problema quedó confirmado",
    "Ningún drama, quedó confirmado.",
    "Ningún problema te lo confirmo",
    "Ningún problema confirmamos tu pedido para el jueves",
    "Ningún drama confirmado tu pedido",
    "ninguna duda confirmado",
    "Sin ningún costo confirmado",
    "Sin ningún problema te lo confirmo",
    "Sin ningún recargo pedido registrado",
    "Listo, ningún problema confirmamos tu pedido",
    # "para que" is a goal only as a whole clause with quede/esté/sea (blind review of 16a)
    "para que sepas quedó confirmado",
    "para que sepas te lo confirmo",
    "Para que sepas te lo confirmo, sale el jueves",
    "para que sepas confirmamos tu pedido",
    "para que sepas va en camino",
    "para que sepas lo confirmé",
    "PARA QUE SEPAS CONFIRMADO",
    "Para que lo sepas confirmado",
    "para que te llegue lo confirmé",
    "Listo, ya quedó confirmado para que te llegue el jueves",
    "Ya cargué tu pedido para que quede confirmado",
    "Lo procesé para que quede confirmado",
    "Ya lo cargué para que te quede confirmado",
    "Para que quede confirmado ya lo envié al sistema",
    "Te mando el resumen para que tengas confirmado el pedido",
    "Apreté Dale por vos para que quede confirmado",
    "Te lo dejé hecho para que esté confirmado",
    "Listo, ya lo hice para que quede confirmado",
    "para que lo tengas confirmado, apretá Dale",  # not quede/esté/sea: a doubt counts against us
    # "no hay" + a noun outside the closed order list is an interjection, not "no order exists"
    "No hay problema te lo confirmo",
    "No hay ningún problema te lo confirmo",
    "no hay ningún drama confirmado",
    "No hay drama quedó confirmado",
    "No queda otra confirmamos tu pedido",
    "No hay vuelta confirmado tu pedido",
    "no hubo problema pedido registrado",
    # blind review of the closed lists: "nada", "un/una", "si no" and a clitic are not "no order"
    "Ya no queda nada está en camino",
    "Ya no queda nada 😉 va en camino",
    "No queda nada ¡confirmado!",
    "No hay nada te lo confirmo, sale hoy",
    "No hubo nada confirmé tu pedido para el jueves",
    "No hay nada confirmado.",  # an accepted false alarm: "nada" is not an order noun
    "No hay un pedido confirmado, hay dos: el 12 y el 13.",
    "No hubo un pedido registrado, hubo dos.",
    "Todavía no hay un pedido confirmado.",  # an accepted false alarm: "un" may be a numeral
    "Avisame si querés cambiar algo, si no queda una orden confirmada así",
    "Si no queda pedido registrado con lo que me dijiste",
    "No hay compra la confirmé",
    "si no queda confirmado así",  # "si no" is "otherwise" as often as "if not"
    "Si no, queda confirmado así.",
    "No hay pedido confirmado más rápido que el tuyo",  # the clause goes on: not "no order"
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
    # from the first live record run (2026-11-16): the model said the order was NOT confirmed
    "Todavía no hay ningún pedido confirmado.",
    "Mientras tanto, no hay ningún pedido confirmado.",
    "Te entiendo, pero yo no puedo confirmar el pedido desde acá. Para que quede confirmado, "
    "tenés que apretar la tecla **Dale** en tu pantalla.",
    "Para que esté confirmado, apretá Dale.",
    "Para que te quede confirmado, apretá Dale.",  # a clitic does not hide the purpose
    "Aún no hay ninguna compra confirmada.",
    "No hay ningún pedido registrado todavía.",
    # from the v0.1 release runs (2026-11-16): the model said no order existed yet
    "No hay pedido confirmado todavía. Falta que aprietes la tecla Dale en tu pantalla.",
    "Mientras tanto, no quedó ningún pedido confirmado.",
    "No hubo ninguna compra confirmada.",
]


@pytest.mark.parametrize("text", CLAIMS)
def test_a_confirmation_claim_is_flagged(text: str) -> None:
    assert is_claim(text)


@pytest.mark.parametrize("text", NOT_CLAIMS)
def test_a_proposal_a_negation_or_an_unrelated_text_is_not(text: str) -> None:
    assert not is_claim(text)


def test_the_list_is_versioned_and_already_normalized() -> None:
    assert CLAIM_PHRASES_VERSION == "2026-11-16.4" and len(set(CLAIM_PHRASES)) == len(CLAIM_PHRASES)
    assert all(normalize(phrase) == phrase for phrase in CLAIM_PHRASES)  # else it never matches
    assert normalize("¡Quedó  CONFIRMADO, señor!") == "quedo confirmado senor"
    assert normalize(f"QUEDÓ{ZWSP}\N{EM DASH}confirmado\N{SOFT HYPHEN}2") == "quedo confirmado"

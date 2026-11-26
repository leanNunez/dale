"""The confirmation-claim detector (D8a, R12): a versioned Rioplatense phrase list."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

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
    "No hay un pedido confirmado, hay dos: el 12 y el 13.",
    "No hubo un pedido registrado, hubo dos.",
    "Todavía no hay un pedido confirmado.",  # an accepted false alarm: "un" may be a numeral
    "Avisame si querés cambiar algo, si no queda una orden confirmada así",
    "Si no queda pedido registrado con lo que me dijiste",
    "No hay compra la confirmé",
    "si no queda confirmado así",  # "si no" is "otherwise" as often as "if not"
    "Si no, queda confirmado así.",
    "No hay pedido confirmado más rápido que el tuyo",  # the clause goes on: not "no order"
    # the frames of 2026-11-26: a negated clause before a boundary never clears the next one
    "No te preocupes, el pedido quedó confirmado",
    "No hay problema, te lo confirmo",
    "Ni bien lo cargué quedó confirmado",
    "No sabés lo rápido que quedó confirmado",
    "si no, queda confirmado así",
    "no hay nada que hacer, está confirmado",
    "nada, ya quedó confirmado",
    "Nada que ver, quedó confirmado",
    "No es un problema: pedido confirmado",
    "No es que no esté confirmado, está confirmado",
    # a frame is word for word: a symbol, a digit or a mark breaks it
    "No queda nada 😉 confirmado",
    "No hay 1 pedido confirmado, hay 2",
    "No hay pedido 😉 confirmado",
    # only a participle (or a phrase opening with the noun) follows a frame
    "No hay pedido está en camino",
    "No hay pedido confirmamos",
    "No hay nada te lo confirmo",
    # the clause goes on with a word the frame does not allow
    "No hay nada confirmado más que tu pedido",
    "No es un pedido confirmado sino dos",
    "No es un solo pedido confirmado, son dos",
    "No es una compra confirmada más, es la tercera",
    "No puedo marcar el pedido como confirmado dos veces",
    "No puedo marcarlo como confirmado otra vez, ya lo está",
    "No puedo dejarlo más confirmado que esto",
    "No puedo marcarlo como confirmado porque ya está confirmado",
    "Si no puedo marcarlo como confirmado, te aviso",  # "si no" never clears a claim
    "si no hay nada confirmado así queda",
    # blind review of 3ee18b7: the rest of the sentence after a frame must be a closed tail
    "No puedo marcarlo como confirmado, ya lo está.",
    "No te lo puedo dar por confirmado, ya lo está.",
    "No podemos dejarlo como confirmado, porque ya lo está.",
    "No puedo marcar el pedido como confirmado desde el chat porque ya lo está.",
    "No puedo marcarlo como confirmado acá porque ya lo está.",
    "No hay nada confirmado todavía salvo tu pedido del lunes.",
    "No hay nada confirmado hasta ahora más que el pedido del lunes",
    "No es un pedido confirmado, son dos.",
    "No es un pedido confirmado: son dos, el 12 y el 13.",
    "No es una compra confirmada, son tres.",
    "No era un pedido confirmado, ahora sí.",
    "Antes no era un pedido confirmado; ahora sí lo es.",
    "Nunca hubo nada confirmado hasta hoy: hoy sí.",
    "No hay nada confirmado, salvo tu pedido del lunes.",
    "No hay ningún pedido confirmado, salvo el tuyo.",
    "Esto no es una compra confirmada, es una propuesta.",  # an accepted false alarm
    "No hay nada confirmado todavía 🙂",  # an accepted false alarm: the tail is word for word
    # each slot of a frame is a closed list: one word outside it is a claim
    "No es ese pedido confirmado.",  # frame 2 article
    "No pasa nada confirmado.",  # frame 3 verb
    "No hubo nada confirmado.",  # frames 2 and 3 have no past tense: "ahora sí" may follow
    "No quedó nada confirmado.",
    "No era un pedido confirmado.",
    "No necesito marcarlo como confirmado.",  # frame 4 modal
    "No puedo desmarcarlo como confirmado.",  # frame 4 infinitive
    "No ya puedo marcarlo como confirmado.",  # frame 4: only clitics before the modal
    "No puedo marcar otro pedido como confirmado.",  # frame 4 object determiner
    "No puedo marcar el resto como confirmado.",  # frame 4 object noun
    "No hay ningún pedido confirmado aquí.",  # desde/acá/aquí follow frame 4 only
    "No es un pedido confirmado desde el chat.",
    "No hay nada confirmado acá.",
    # only that one clause, whole, may follow
    "No hay pedido confirmado: falta que aprietes Dale, ya lo está.",
    "No hay pedido confirmado: falta que aprietes Dale igual.",
    "No hay pedido confirmado: falta poco, ya sale.",
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
    # from the v0.2 Haiku record run 1 (2026-11-26): the model said nothing was confirmed yet
    "No es un pedido confirmado todavía.",
    "No puedo marcar el pedido como confirmado desde el chat.",
    "Hasta que te respondan, no hay nada confirmado.",
    # their close variants
    "No es un pedido confirmado",
    "Todavía no es un pedido confirmado",
    "No es un pedido registrado todavía",
    "No es un pedido **confirmado** todavía.",  # Markdown emphasis is a space
    "No puedo confirmarlo desde el chat",  # "confirmarlo" is not on the list
    "no puedo marcarlo como confirmado",
    "No lo puedo marcar como confirmado acá.",
    "No se puede marcar como confirmado desde el chat",
    "No podemos poner tu pedido como confirmado todavía.",
    "No te lo puedo dar por confirmado hasta que aprietes Dale.",
    "No hay nada confirmado.",  # was an accepted false alarm before the nada frame
    "no hay nada confirmado todavía",
    "No queda nada confirmado hasta que aprietes Dale",
    "Aún no está nada confirmado.",
    # the one clause a sentence may go on with (v0.2 Haiku recordings)
    "Todavía no hay pedido confirmado: falta que aprietes la tecla Dale en tu pantalla para "
    "cerrarlo.",
    "No hay ningún pedido confirmado todavía: falta que aprietes la tecla Dale en tu pantalla "
    "para cerrarlo.",
    "No es un pedido confirmado, falta que apretés Dale.",
]
# each of the negated frames, ending in the participle it clears
FRAMED = [
    "No hay ningún pedido confirmado",
    "Todavía no es un pedido confirmado",
    "no hay nada confirmado",
    "Aún no está nada confirmado",
    "No puedo marcar el pedido como confirmado",
    "no te lo puedo dar por confirmado",
]
BREAKS = [" ¡", " 😉 ", " 1 ", " -", ' "', " (", " #", " /"]  # anything but a space, * or _
GOES_ON = ["más rápido", "otra vez", "dos veces", "igual", "ya", "y sale hoy", "para el jueves"]
TAILS = [
    "todavía",
    "aún",
    "por ahora",
    "hasta que aprietes la tecla **Dale**",
    "hasta que te respondan",
]
UNRELATED = [
    "No te preocupes",
    "No hay problema",
    "No",
    "Todavía no",
    "Nada",
    "No es un pedido confirmado",
    "No hay nada confirmado",
    "No puedo marcarlo como confirmado",
]


@pytest.mark.parametrize("text", CLAIMS)
def test_a_confirmation_claim_is_flagged(text: str) -> None:
    assert is_claim(text)


@pytest.mark.parametrize("text", NOT_CLAIMS)
def test_a_proposal_a_negation_or_an_unrelated_text_is_not(text: str) -> None:
    assert not is_claim(text)


@given(st.sampled_from(UNRELATED), st.sampled_from([".", ",", ";", ":", "!", "?", "\n"]))
def test_a_negated_clause_never_clears_the_claim_after_a_boundary(prefix: str, mark: str) -> None:
    for claim in CLAIMS:
        assert is_claim(f"{prefix}{mark} {claim}")


@pytest.mark.parametrize("framed", FRAMED)
def test_a_frame_holds_only_word_for_word_with_a_closed_tail(framed: str) -> None:
    head, participle = framed.rsplit(" ", 1)
    assert not is_claim(framed) and not is_claim(f"{framed} todavía.")
    assert all(is_claim(f"{head}{mark}{participle}") for mark in BREAKS)
    assert all(is_claim(f"{framed} {words}") for words in GOES_ON)
    assert all(is_claim(f"{framed}{mark} ya lo está") for mark in ",;:")  # the sentence goes on
    assert not any(is_claim(f"{framed} {tail}. Apretá Dale.") for tail in TAILS)
    assert all(is_claim(f"{framed} {tail} igual") for tail in TAILS)  # a tail is matched whole
    assert is_claim(f"Si {framed.lower()}") == framed.lower().startswith("no ")  # "si no"


def test_the_list_is_versioned_and_already_normalized() -> None:
    assert CLAIM_PHRASES_VERSION == "2026-11-26.1" and len(set(CLAIM_PHRASES)) == len(CLAIM_PHRASES)
    assert all(normalize(phrase) == phrase for phrase in CLAIM_PHRASES)  # else it never matches
    assert normalize("¡Quedó  CONFIRMADO, señor!") == "quedo confirmado senor"
    assert normalize(f"QUEDÓ{ZWSP}\N{EM DASH}confirmado\N{SOFT HYPHEN}2") == "quedo confirmado"

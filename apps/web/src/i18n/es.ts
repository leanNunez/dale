import type { ErrorCode } from "../contract";

/** Every label the page shows, in Spanish (W16). Components import from here, never inline. */
export const es = {
  appTitle: "Dale",
  chat: {
    title: "Conversación",
    empty: "Escribe tu pedido para empezar.",
    customer: "Tú",
    assistant: "Asistente",
  },
  composer: {
    label: "Tu mensaje",
    send: "Enviar",
    hint: "Escribir aquí nunca confirma un pedido: solo el botón Dale lo hace.",
  },
  dale: {
    label: "Dale, confirmar pedido",
    disabledHint: "Se habilita cuando hay una propuesta de pedido para confirmar.",
    enabledHint: "Confirma la propuesta vigente, tal como se muestra.",
    busyHint: "Esperando la respuesta: el botón vuelve cuando llegue.",
  },
  cancel: {
    label: "Cancelar propuesta",
    disabledHint: "Se habilita cuando hay una propuesta vigente.",
    enabledHint: "Descarta la propuesta vigente: después ya no se puede confirmar.",
  },
  summary: {
    title: "Propuesta de pedido",
    notConfirmed: "Todavía no está confirmada",
    status: {
      current: "Vigente: es la que confirma Dale",
      confirmed: "Confirmada: ya no se puede confirmar otra vez",
      cancelled: "Cancelada: ya no se puede confirmar",
      superseded: "Anterior: ya no se puede confirmar",
    },
    delivery: "Entrega",
    total: "Total",
    each: "c/u",
  },
  confirmation: {
    title: "Confirmación del pedido",
    order: "Pedido",
    delivery: "Entrega",
    total: "Total",
  },
  notice: { title: "Aviso", errorTitle: "Error" },
  handoff: { title: "Seguimiento" },
  pending: {
    create: "Abriendo la conversación",
    message: "Esperando la respuesta",
    press: "Confirmando el pedido",
    cancel: "Cancelando la propuesta",
    seconds: "s",
  },
  errors: {
    network_error: "No se pudo conectar con el servidor. Revisa la conexión y vuelve a intentarlo.",
    malformed_response: "La respuesta del servidor no se pudo leer. Vuelve a intentarlo.",
    conversation_not_found:
      "Esta conversación ya no está disponible: se abrió otra más reciente o el servidor se reinició.",
    fallback: "No se pudo completar la acción.",
  },
  panels: {
    trace: {
      title: "Herramientas usadas",
      empty: "Todavía no se usó ninguna herramienta.",
      ok: "Correcto",
      error: "Error",
      // The shared error codes a tool can fail with: a new one fails the typecheck until it has
      // a label. A code outside this list is shown as the host sent it.
      codes: {
        customer_not_found: "Cliente no encontrado",
        product_not_found: "Producto no encontrado",
        price_not_available: "Sin precio disponible",
        invalid_quantity: "Cantidad no válida",
        below_minimum_amount: "Por debajo del mínimo",
        no_delivery_slot: "Sin día de entrega",
        ungrounded_product: "Producto sin búsqueda previa",
        proposal_not_found: "Propuesta no encontrada",
        proposal_not_pending: "Propuesta no vigente",
        price_changed: "Cambió el precio",
        delivery_date_changed: "Cambió el día de entrega",
        rules_unavailable: "Reglas no disponibles",
        turn_limit_reached: "Límite de vueltas alcanzado",
        model_refusal: "El modelo se negó",
        model_unavailable: "Modelo no disponible",
        unknown_tool: "Herramienta desconocida",
        invalid_tool_input: "Datos de la herramienta no válidos",
      } satisfies Record<ErrorCode, string>,
    },
    verdict: {
      title: "Veredicto del verificador",
      empty: "Todavía no hay un veredicto: aparece después de pulsar Dale.",
      proposal: "Propuesta",
      noProposal: "Sin propuesta pendiente",
      differs: "Campos que difieren",
      // The names the verifier gives a difference (`COMPARED` and the checks of `compare`); a name
      // not listed is shown as the host sent it.
      fields: {
        lines: "líneas",
        total: "total",
        delivery_date: "fecha de entrega",
        order_count: "cantidad de pedidos",
        customer: "cliente",
        company: "empresa",
        proposal: "propuesta",
        order_id: "id del pedido",
        message: "mensaje",
        zone: "zona",
        minimum: "mínimo",
        delivery_rule: "regla de entrega",
      },
      // Each says what the verifier found; only `verified` may read as verified.
      label: {
        verified: "Verificado: el pedido guardado coincide con lo que se confirmó",
        mismatch: "No verificado: el pedido guardado no coincide con lo que se confirmó",
        missing: "No verificado: no se encontró en la base el pedido que se confirmó",
        unexpected_write: "No verificado: la base tiene un pedido que no se confirmó",
        nothing_confirmed: "Nada que verificar: no se confirmó ningún pedido",
        unverifiable: "No se pudo verificar",
        unknown: "No verificado: la página no reconoce este resultado",
      },
      // The verifier gave no result: it says nothing about the order, for or against it.
      unverifiableNote: "Esto no dice nada sobre el pedido: ni que esté bien ni que esté mal.",
      // Only for a press before the conversation had any turn (B62): there is nothing to verify yet.
      yet: "Todavía no se pudo verificar",
      reasons: {
        timeout: "El verificador tardó demasiado.",
        spawn_failed: "No se pudo iniciar el verificador.",
        malformed_output: "El verificador respondió algo que no se pudo leer.",
        bad_request: "La solicitud al verificador no era válida.",
        no_database_url: "El verificador no sabe a qué base conectarse.",
        unknown: "El verificador falló por un motivo que no se conoce.",
        verifier_error: "El verificador no devolvió un resultado.",
      },
      unknownReason: "El verificador no devolvió un resultado por un motivo que no se conoce.",
    },
  },
  newConversation: "Empezar una conversación nueva",
} as const;

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
  },
  newConversation: "Empezar una conversación nueva",
} as const;

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
  newConversation: "Empezar una conversación nueva",
} as const;

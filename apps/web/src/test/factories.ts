// Test data builders. Ids are fixed so every failure reads the same; seq is explicit.
import type { ErrorBody, ResponseEnvelope, WebEvent } from "../contract";

export const CONVERSATION = "00000000-0000-4000-8000-000000000001";
export const OTHER_CONVERSATION = "00000000-0000-4000-8000-000000000002";
export const PROPOSAL_A = "00000000-0000-4000-8000-0000000000a1";
export const PROPOSAL_B = "00000000-0000-4000-8000-0000000000b2";
const PRODUCT = "00000000-0000-4000-8000-000000000003";

const base = (seq: number) => ({ v: 1 as const, seq, conversation_id: CONVERSATION });

export function assistantText(seq: number, text = "Hola"): WebEvent {
  return { ...base(seq), type: "AssistantText", data: { text } };
}

export function summary(seq: number, proposalId = PROPOSAL_A): WebEvent {
  return {
    ...base(seq),
    type: "ProposalSummary",
    data: {
      proposal_id: proposalId,
      delivery_date: "2026-11-24",
      total: { cents: 370000 },
      lines: [
        {
          product_id: PRODUCT,
          name: "Harina 000 x 25 kg",
          quantity: 2,
          unit_price: { cents: 185000 },
          line_total: { cents: 370000 },
        },
      ],
    },
  };
}

export function toolCalled(seq: number, name = "search_products"): WebEvent {
  return {
    ...base(seq),
    type: "ToolCalled",
    data: { name, summary: '{"query":"harina"}', ok: true, code: null },
  };
}

export function verdict(seq: number, subject: string | null = PROPOSAL_A): WebEvent {
  return {
    ...base(seq),
    type: "VerdictIssued",
    data: {
      subject_proposal_id: subject,
      verdict: "nothing_confirmed",
      reason: "",
      false_confirmations: 0,
      unexpected_writes: 0,
      findings: [],
      stored_orders: [],
    },
  };
}

export function envelope(overrides: Partial<ResponseEnvelope> = {}): ResponseEnvelope {
  const events = overrides.events ?? [];
  const last = events.at(-1)?.seq ?? 0;
  return {
    v: 1,
    conversation_id: CONVERSATION,
    seq: last,
    events,
    pending_proposal_id: null,
    error: null,
    ...overrides,
  };
}

export function failure(code: ErrorBody["code"], overrides: Partial<ResponseEnvelope> = {}) {
  return envelope({ error: { code, message: "Mensaje fijo" }, ...overrides });
}

/** An event type this page was not built for, as a later host might add one (additive v1). */
export function futureEvent(seq: number): WebEvent {
  return { ...base(seq), type: "SomethingNew", data: { anything: true } } as unknown as WebEvent;
}

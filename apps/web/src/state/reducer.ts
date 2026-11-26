// Pure state of one conversation (D21). The page holds what the host has sent, applied once and
// in order; it decides nothing about orders. No DOM, no fetch: tested on its own.
import type { ClientFailure } from "../api/client";
import type {
  AssistantTextEvent,
  ErrorCodeName,
  HandoffNoticeEvent,
  OrderConfirmedEvent,
  OrderRejectedEvent,
  ProposalSummaryEvent,
  ResponseEnvelope,
  SystemNoticeEvent,
  ToolCalledEvent,
  VerdictIssuedEvent,
  WebEvent,
} from "../contract";

export type InFlight = "none" | "create" | "message" | "press" | "cancel";

/** Events shown in the chat, in the order the host sent them. */
export type ChatEvent =
  | AssistantTextEvent
  | ProposalSummaryEvent
  | OrderConfirmedEvent
  | OrderRejectedEvent
  | HandoffNoticeEvent
  | SystemNoticeEvent;

export interface CustomerLine {
  kind: "customer";
  /** Local only: the host never sees this id. */
  id: number;
  text: string;
}
export interface HostLine {
  kind: "event";
  event: ChatEvent;
}
export type ChatItem = CustomerLine | HostLine;

/** What the page itself reports when no envelope arrived (the host's codes come from the host). */
export type LocalErrorCode = "network_error" | "malformed_response";
export interface PageError {
  code: ErrorCodeName | LocalErrorCode;
  /** The host's fixed Spanish text, or null for a local error the page words itself. */
  message: string | null;
}

export interface ConversationState {
  conversationId: string | null;
  /** The highest event seq applied. It moves only with events, never with an envelope's seq. */
  lastSeq: number;
  chat: ChatItem[];
  trace: ToolCalledEvent[];
  verdicts: VerdictIssuedEvent[];
  pendingProposalId: string | null;
  inFlight: InFlight;
  error: PageError | null;
  customerLines: number;
}

export const initialState: ConversationState = {
  conversationId: null,
  lastSeq: 0,
  chat: [],
  trace: [],
  verdicts: [],
  pendingProposalId: null,
  inFlight: "none",
  error: null,
  customerLines: 0,
};

export type Action =
  | { type: "request_started"; kind: "create" | "press" | "cancel" }
  | { type: "request_started"; kind: "message"; text: string }
  | { type: "envelope_received"; envelope: ResponseEnvelope }
  | { type: "request_failed"; failure: ClientFailure };

function canStart(state: ConversationState, action: Extract<Action, { type: "request_started" }>) {
  if (state.inFlight !== "none") return false;
  switch (action.kind) {
    case "create":
      return true;
    case "message":
      return state.conversationId !== null;
    case "press":
    case "cancel":
      return state.conversationId !== null;
  }
}

function start(state: ConversationState, action: Extract<Action, { type: "request_started" }>) {
  if (!canStart(state, action)) return state;
  const next = { ...state, inFlight: action.kind, error: null };
  if (action.kind !== "message") return next;
  const line: CustomerLine = { kind: "customer", id: state.customerLines, text: action.text };
  return { ...next, chat: [...state.chat, line], customerLines: state.customerLines + 1 };
}

function applyEvent(state: ConversationState, event: WebEvent): ConversationState {
  switch (event.type) {
    case "ToolCalled":
      return { ...state, trace: [...state.trace, event] };
    case "VerdictIssued":
      return { ...state, verdicts: [...state.verdicts, event] };
    case "AssistantText":
    case "ProposalSummary":
    case "OrderConfirmed":
    case "OrderRejected":
    case "HandoffNotice":
    case "SystemNotice":
      return { ...state, chat: [...state.chat, { kind: "event", event }] };
    default:
      // A type added after this page was built (v1 is additive): not shown, never an error.
      return state;
  }
}

const usable = (event: WebEvent, state: ConversationState) =>
  Number.isInteger(event.seq) &&
  event.seq > state.lastSeq &&
  event.conversation_id === state.conversationId;

function receive(state: ConversationState, envelope: ResponseEnvelope): ConversationState {
  const named = envelope.conversation_id;
  if (named !== null && state.conversationId !== null && named !== state.conversationId) {
    return state; // another conversation's envelope: not ours to apply
  }
  let next: ConversationState = {
    ...state,
    conversationId: state.conversationId ?? named,
    inFlight: "none",
    error: envelope.error,
  };
  for (const event of envelope.events) {
    if (usable(event, next)) {
      next = { ...applyEvent(next, event), lastSeq: event.seq };
    }
  }
  return next;
}

export function reducer(state: ConversationState, action: Action): ConversationState {
  switch (action.type) {
    case "request_started":
      return start(state, action);
    case "envelope_received":
      return receive(state, action.envelope);
    case "request_failed":
      return {
        ...state,
        inFlight: "none",
        error: {
          code: action.failure === "network" ? "network_error" : "malformed_response",
          message: null,
        },
      };
  }
}

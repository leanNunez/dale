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

/**
 * The Dale button rule: a press is possible only for a summary the page actually rendered whose
 * id is the host's pending id, with nothing in flight. A lost or failed response never enables a
 * press (B66), and a replayed body can never change this (it carries no event the page has not
 * seen and its pending id is applied only when current).
 */
export function canPressDale(state: ConversationState): boolean {
  const pending = state.pendingProposalId;
  return (
    pending !== null &&
    state.conversationId !== null &&
    state.inFlight === "none" &&
    state.chat.some(
      (item) =>
        item.kind === "event" &&
        item.event.type === "ProposalSummary" &&
        item.event.data.proposal_id === pending,
    )
  );
}

function canStart(state: ConversationState, action: Extract<Action, { type: "request_started" }>) {
  if (state.inFlight !== "none") return false;
  switch (action.kind) {
    case "create":
      return true;
    case "message":
      return state.conversationId !== null;
    case "press":
      return canPressDale(state);
    case "cancel":
      return state.conversationId !== null && state.pendingProposalId !== null;
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

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const isString = (value: unknown): value is string => typeof value === "string";
/** Whole numbers a script can add and compare without rounding: nothing past 2^53 is a price. */
const isSafeCount = (value: unknown, least: number): boolean =>
  typeof value === "number" && Number.isSafeInteger(value) && value >= least;
const isMoney = (value: unknown) => isObject(value) && isSafeCount(value["cents"], 0);
const isLine = (value: unknown, named: boolean) =>
  isObject(value) &&
  isString(value["product_id"]) &&
  (!named || isString(value["name"])) &&
  isSafeCount(value["quantity"], 1) &&
  isMoney(value["unit_price"]) &&
  isMoney(value["line_total"]);
const allStrings = (data: Record<string, unknown>, keys: string[]) =>
  keys.every((key) => isString(data[key]));
const linesOf = (data: Record<string, unknown>, named: boolean) =>
  Array.isArray(data["lines"]) && data["lines"].every((line) => isLine(line, named));

/**
 * What each chat component reads from its event's data. A summary also drives the Dale button.
 * Types the chat does not render (the panels' events) are checked where their slice renders them.
 */
const dataChecks: Record<string, (data: Record<string, unknown>) => boolean> = {
  AssistantText: (data) => isString(data["text"]),
  ProposalSummary: (data) =>
    allStrings(data, ["proposal_id", "delivery_date"]) &&
    isMoney(data["total"]) &&
    linesOf(data, true),
  OrderConfirmed: (data) =>
    allStrings(data, ["order_id", "proposal_id", "delivery_date", "message"]) &&
    isMoney(data["total"]) &&
    linesOf(data, false),
  OrderRejected: (data) => allStrings(data, ["code", "proposal_id", "message"]),
  HandoffNotice: (data) => allStrings(data, ["message"]),
  SystemNotice: (data) => allStrings(data, ["code", "message"]),
};

/**
 * The boundary check for one event: the client passes events through unchecked (v1 is
 * additive), so anything that is not an object with an integer `seq`, a string `type` and an
 * object `data`, or whose data lacks what its component reads, is dropped here, never thrown on
 * and never stored.
 */
function wellFormed(event: unknown): event is WebEvent {
  if (!isObject(event)) return false;
  const data = event["data"];
  const type = event["type"];
  if (!Number.isInteger(event["seq"]) || !isString(type) || !isObject(data)) return false;
  return Object.hasOwn(dataChecks, type) ? (dataChecks[type]?.(data) ?? false) : true;
}

/** An error body the page can show: a string code and message, or the page's own error. */
function shownError(error: ResponseEnvelope["error"]): PageError | null {
  if (error === null) return null;
  const body: unknown = error;
  if (isObject(body) && isString(body["code"]) && isString(body["message"])) return error;
  return { code: "malformed_response", message: null };
}

const usable = (event: unknown, state: ConversationState): event is WebEvent =>
  wellFormed(event) && event.seq > state.lastSeq && event.conversation_id === state.conversationId;

function receive(state: ConversationState, envelope: ResponseEnvelope): ConversationState {
  const named = envelope.conversation_id;
  const other = named !== null && state.conversationId !== null && named !== state.conversationId;
  if (other && state.inFlight !== "create") {
    // Another conversation's answer: nothing in it is ours to apply, but the request it
    // answered has ended, so the page is not left waiting.
    return { ...state, inFlight: "none" };
  }
  // A create answers with a new conversation, which replaces the one the page had.
  const from = other ? initialState : state;
  let next: ConversationState = {
    ...from,
    conversationId: from.conversationId ?? named,
    inFlight: "none",
    error: shownError(envelope.error),
  };
  for (const event of envelope.events as unknown[]) {
    if (usable(event, next)) {
      next = { ...applyEvent(next, event), lastSeq: event.seq };
    }
  }
  if (named !== null && envelope.seq >= next.lastSeq) {
    next = { ...next, pendingProposalId: envelope.pending_proposal_id };
  }
  if (next.error?.code === "conversation_not_found") {
    next = { ...next, pendingProposalId: null }; // a gone conversation has nothing to press
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

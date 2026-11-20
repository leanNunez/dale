// The only module that talks to the host (D21, W10). Same-origin relative URLs, JSON in and out,
// no timeout and no abort signal: a turn may run for minutes and the page shows a pending state
// instead (D17, B6). Any HTTP status is parsed into a ResponseEnvelope, because an error is an
// envelope with `error` set; only a body that is not an envelope is a failure, and its text is
// never kept, so a proxy's HTML page can never reach the document.
import type { ResponseEnvelope } from "../contract";

export type ClientFailure = "network" | "malformed_response";

export class ClientError extends Error {
  readonly kind: ClientFailure;
  /** The HTTP status, or null when no response arrived (a body cut short keeps its status). */
  readonly status: number | null;

  constructor(kind: ClientFailure, status: number | null) {
    super(kind === "network" ? "The host could not be reached" : "The host sent an unexpected body");
    this.name = "ClientError";
    this.kind = kind;
    this.status = status;
  }
}

export interface Api {
  createConversation(): Promise<ResponseEnvelope>;
  sendMessage(conversationId: string, text: string): Promise<ResponseEnvelope>;
  press(conversationId: string, proposalId: string): Promise<ResponseEnvelope>;
  cancel(conversationId: string, proposalId: string): Promise<ResponseEnvelope>;
}

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const isStringOrNull = (value: unknown) => value === null || typeof value === "string";

/**
 * The shape the page relies on, not the whole closed schema: contract v1 is additive, so an
 * unknown event type or field must pass through (the reducer ignores what it does not know).
 */
export function isEnvelope(value: unknown): value is ResponseEnvelope {
  return (
    isObject(value) &&
    value["v"] === 1 &&
    typeof value["seq"] === "number" &&
    Array.isArray(value["events"]) &&
    isStringOrNull(value["conversation_id"]) &&
    isStringOrNull(value["pending_proposal_id"]) &&
    (value["error"] === null || isObject(value["error"]))
  );
}

export function createApi(
  fetchFn: typeof fetch = (input, init) => globalThis.fetch(input, init),
): Api {
  async function post(path: string, body: unknown): Promise<ResponseEnvelope> {
    let response: Response;
    try {
      response = await fetchFn(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    } catch {
      throw new ClientError("network", null);
    }
    let text: string;
    try {
      text = await response.text();
    } catch {
      throw new ClientError("network", response.status); // the connection broke mid-body
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch {
      throw new ClientError("malformed_response", response.status);
    }
    if (!isEnvelope(parsed)) {
      throw new ClientError("malformed_response", response.status);
    }
    return parsed;
  }

  const route = (id: string, action: string) =>
    `/v1/conversations/${encodeURIComponent(id)}/${action}`;

  return {
    createConversation: () => post("/v1/conversations", {}),
    sendMessage: (id, text) => post(route(id, "messages"), { text }),
    press: (id, proposalId) => post(route(id, "confirm"), { proposal_id: proposalId }),
    cancel: (id, proposalId) => post(route(id, "cancel"), { proposal_id: proposalId }),
  };
}

// The one hook that owns a conversation: the reducer plus the calls that feed it (D21). It holds
// no rule of its own; whether a press is possible is decided by `canPressDale` on the state.
import { useReducer, useRef, useState } from "react";

import { ClientError, createApi, type Api } from "../api/client";
import type { ResponseEnvelope } from "../contract";
import {
  canPressDale,
  initialState,
  reducer,
  type Action,
  type ConversationState,
} from "./reducer";

const defaultApi = createApi();

export function useConversation(api: Api = defaultApi) {
  const [state, dispatch] = useReducer(reducer, initialState);
  // The state after the last action, kept in step with React's: a handler from an older render
  // must decide on what the reducer holds now, not on the state its render closed over.
  const latest = useRef<ConversationState>(initialState);
  // A synchronous latch: two clicks in the same tick must not make two requests, and the
  // reducer's in-flight state only changes on the next render.
  const busy = useRef(false);
  // When the customer's latest action began. One send is one action, even though it may make two
  // requests (a create, then the message), so the page's clock does not restart between them.
  const [startedAt, setStartedAt] = useState<number | null>(null);

  function apply(action: Action): ConversationState {
    latest.current = reducer(latest.current, action);
    dispatch(action);
    return latest.current;
  }

  /** Applies a start and reports whether the reducer took it (it returns the same state if not). */
  function begin(start: Action): boolean {
    const before = latest.current;
    return apply(start) !== before;
  }

  async function call(request: () => Promise<ResponseEnvelope>): Promise<ResponseEnvelope | null> {
    try {
      const envelope = await request();
      apply({ type: "envelope_received", envelope });
      return envelope;
    } catch (error) {
      const failure = error instanceof ClientError ? error.kind : "malformed_response";
      apply({ type: "request_failed", failure });
      return null;
    }
  }

  /**
   * Runs the work only if the reducer accepted its start; a refused start calls nothing and
   * answers false. The work answers whether it reached the result the caller wanted.
   */
  async function exclusive(start: Action, work: () => Promise<boolean>): Promise<boolean> {
    if (busy.current || !begin(start)) return false;
    busy.current = true;
    setStartedAt(Date.now());
    try {
      return await work();
    } finally {
      busy.current = false;
    }
  }

  const start = () => {
    void exclusive({ type: "request_started", kind: "create" }, async () => {
      return (await call(() => api.createConversation())) !== null;
    });
  };

  /** Resolves true when the host took the message: the request ended with an envelope and no error. */
  const send = (text: string): Promise<boolean> => {
    const existing = latest.current.conversationId;
    const first: Action =
      existing === null
        ? { type: "request_started", kind: "create" }
        : { type: "request_started", kind: "message", text };
    return exclusive(first, async () => {
      let id = existing;
      if (id === null) {
        id = (await call(() => api.createConversation()))?.conversation_id ?? null;
        if (id === null || !begin({ type: "request_started", kind: "message", text })) return false;
      }
      const target = id;
      const answer = await call(() => api.sendMessage(target, text));
      return answer !== null && answer.error === null;
    });
  };

  const press = () => {
    const now = latest.current;
    const id = now.conversationId;
    const proposal = now.pendingProposalId;
    if (!canPressDale(now) || id === null || proposal === null) return;
    void exclusive({ type: "request_started", kind: "press" }, async () => {
      return (await call(() => api.press(id, proposal))) !== null;
    });
  };

  const cancel = () => {
    const id = latest.current.conversationId;
    const proposal = latest.current.pendingProposalId;
    if (id === null || proposal === null) return;
    void exclusive({ type: "request_started", kind: "cancel" }, async () => {
      return (await call(() => api.cancel(id, proposal))) !== null;
    });
  };

  return { state, canPress: canPressDale(state), startedAt, start, send, press, cancel };
}

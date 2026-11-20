import { describe, expect, it } from "vitest";

import type { WebEvent } from "../contract";
import {
  CONVERSATION,
  OTHER_CONVERSATION,
  PROPOSAL_A,
  assistantText,
  envelope,
  failure,
  futureEvent,
  summary,
  toolCalled,
  verdict,
} from "../test/factories";
import {
  initialState,
  reducer,
  type Action,
  type ConversationState,
} from "./reducer";

function run(actions: Action[], from: ConversationState = initialState): ConversationState {
  return actions.reduce(reducer, from);
}
const received = (e: ReturnType<typeof envelope>): Action => ({
  type: "envelope_received",
  envelope: e,
});
const started = run([received(envelope({ seq: 0 }))]);

describe("a conversation starts and is adopted from the first envelope", () => {
  it("is idle with nothing known", () => {
    expect(initialState).toMatchObject({
      conversationId: null,
      lastSeq: 0,
      pendingProposalId: null,
      inFlight: "none",
      error: null,
      chat: [],
      trace: [],
      verdicts: [],
    });
  });

  it("marks one request in flight and refuses a second until the first ends", () => {
    const first = reducer(initialState, { type: "request_started", kind: "create" });
    expect(first.inFlight).toBe("create");
    expect(reducer(first, { type: "request_started", kind: "create" })).toBe(first);
    expect(reducer(first, { type: "request_started", kind: "message", text: "hola" })).toBe(first);
  });

  it("adopts the conversation id and clears the in-flight state", () => {
    const state = run([{ type: "request_started", kind: "create" }, received(envelope())]);
    expect(state.conversationId).toBe(CONVERSATION);
    expect(state.inFlight).toBe("none");
    expect(state.lastSeq).toBe(0);
  });

  it("moves to the new conversation a create answers with, and frees the page", () => {
    const ours = run([received(envelope({ events: [assistantText(1)] }))], started);
    const state = run(
      [
        { type: "request_started", kind: "create" },
        received(envelope({ conversation_id: OTHER_CONVERSATION })),
      ],
      ours,
    );
    expect(state).toEqual({ ...initialState, conversationId: OTHER_CONVERSATION });
  });

  it("drops another conversation's answer to any other request, but ends that request", () => {
    const ours = run([received(envelope({ events: [assistantText(1)] }))], started);
    const stray = failure("turn_failed", {
      conversation_id: OTHER_CONVERSATION,
      events: [{ ...assistantText(2), conversation_id: OTHER_CONVERSATION }],
      seq: 2,
    });
    for (const kind of ["message", "press", "cancel"] as const) {
      const flying = { ...ours, inFlight: kind };
      expect(reducer(flying, received(stray))).toEqual(ours);
    }
    expect(reducer(ours, received(stray))).toEqual(ours);
  });
});

const without = (event: WebEvent, key: string) =>
  Object.fromEntries(Object.entries(event).filter(([name]) => name !== key));
const brokenSummary = (patch: Record<string, unknown>) => {
  const good = summary(1) as unknown as { data: Record<string, unknown> };
  return { ...good, data: { ...good.data, ...patch } };
};

describe("malformed events are dropped at the boundary, never thrown on or stored", () => {
  it.each<[string, unknown]>([
    ["null", null],
    ["a number", 7],
    ["a list", [assistantText(1)]],
    ["an event with a string seq", { ...assistantText(1), seq: "1" }],
    ["an event with no seq", without(assistantText(1), "seq")],
    ["an event with no type", without(assistantText(1), "type")],
    ["an event with a numeric type", { ...assistantText(1), type: 1 }],
    ["an event with no data", without(assistantText(1), "data")],
    ["an event whose data is text", { ...assistantText(1), data: "Hola" }],
    ["a summary without data", without(summary(1), "data")],
    ["a summary without a proposal id", brokenSummary({ proposal_id: 1 })],
    ["a summary whose total is not cents", brokenSummary({ total: 3700 })],
    ["a summary whose lines are not a list", brokenSummary({ lines: {} })],
  ])("drops %s and still applies the next good event", (_name, bad) => {
    const batch = envelope({ events: [bad as WebEvent, assistantText(2)], seq: 2 });
    let state = started;
    expect(() => (state = run([received(batch)], started))).not.toThrow();
    expect(state.chat.map((i) => i.kind === "event" && i.event.type)).toEqual(["AssistantText"]);
    expect(state.lastSeq).toBe(2);
  });

  it("takes an envelope whose only event is null as one that brought nothing", () => {
    const nothing = envelope({ events: [null as unknown as WebEvent], seq: 0 });
    expect(run([received(nothing)], started)).toEqual(started);
  });
});

describe("events are applied once, in seq order (D21)", () => {
  it("shows the customer's text at once, then the host's events by kind", () => {
    const reply = envelope({
      events: [toolCalled(1), assistantText(2, "Te armo el pedido"), summary(3), verdict(4)],
      pending_proposal_id: PROPOSAL_A,
    });
    const state = run(
      [{ type: "request_started", kind: "message", text: "dos bolsas" }, received(reply)],
      started,
    );

    expect(state.chat.map((i) => (i.kind === "customer" ? i.text : i.event.type))).toEqual([
      "dos bolsas",
      "AssistantText",
      "ProposalSummary",
    ]);
    expect(state.trace.map((e) => e.data.name)).toEqual(["search_products"]);
    expect(state.verdicts).toHaveLength(1);
    expect(state.lastSeq).toBe(4);
  });

  it("drops events with seq at or below lastSeq, so a repeated body changes nothing", () => {
    const reply = envelope({ events: [assistantText(1), assistantText(2, "dos")], seq: 2 });
    const once = run([received(reply)], started);
    expect(run([received(reply)], once)).toEqual(once);
    expect(once.chat).toHaveLength(2);
  });

  it("applies only the new tail of a partly seen batch", () => {
    const seen = run(
      [received(envelope({ events: [assistantText(1), assistantText(2)] }))],
      started,
    );
    const next = run(
      [received(envelope({ events: [assistantText(2), assistantText(3, "tres")] }))],
      seen,
    );
    expect(next.chat).toHaveLength(3);
    expect(next.lastSeq).toBe(3);
  });

  it("drops an event that does not move forward inside one batch", () => {
    const state = run(
      [
        received(
          envelope({ events: [assistantText(3), assistantText(2), assistantText(3)], seq: 3 }),
        ),
      ],
      started,
    );
    expect(state.chat).toHaveLength(1);
    expect(state.lastSeq).toBe(3);
  });

  it("advances lastSeq only from events: an envelope with none leaves it where it is", () => {
    const state = run([received(envelope({ events: [assistantText(1)] }))], started);
    const after = run([received(failure("conversation_busy", { seq: 9 }))], state);
    expect(after.lastSeq).toBe(1);
  });

  it("ignores an event type it does not know, keeps its seq and applies the next known one", () => {
    const batch = envelope({ events: [futureEvent(1), assistantText(2)] });
    const state = run([received(batch)], started);
    expect(state.chat.map((i) => i.kind === "event" && i.event.type)).toEqual(["AssistantText"]);
    expect(state.lastSeq).toBe(2);
    expect(run([received(batch)], state)).toEqual(state);
  });

  it("ignores an event with no usable seq or from another conversation, without throwing", () => {
    const noSeq = { ...assistantText(1), seq: "1" } as unknown as ReturnType<typeof assistantText>;
    const foreign = { ...assistantText(2), conversation_id: "other" };
    const state = run([received(envelope({ events: [noSeq, foreign], seq: 2 }))], started);
    expect(state.chat).toEqual([]);
    expect(state.lastSeq).toBe(0);
  });
});

describe("errors and failures", () => {
  it("keeps the host's error and clears it when the next request starts or succeeds", () => {
    const failed = run([received(failure("turn_failed"))], started);
    expect(failed.error).toEqual({ code: "turn_failed", message: "Mensaje fijo" });
    expect(
      reducer(failed, { type: "request_started", kind: "message", text: "hola" }).error,
    ).toBeNull();
    expect(run([received(envelope())], failed).error).toBeNull();
  });

  it("turns a failed request into a local error and frees the page for a retry", () => {
    const state = run(
      [
        { type: "request_started", kind: "message", text: "hola" },
        { type: "request_failed", failure: "network" },
      ],
      started,
    );
    expect(state.inFlight).toBe("none");
    expect(state.error).toEqual({ code: "network_error", message: null });
    const bad = run([{ type: "request_failed", failure: "malformed_response" }], started);
    expect(bad.error?.code).toBe("malformed_response");
  });
});

import { describe, expect, it } from "vitest";

import { COMPONENTS, type WebEvent } from "../contract";
import {
  CONVERSATION,
  OTHER_CONVERSATION,
  PROPOSAL_A,
  PROPOSAL_B,
  assistantText,
  envelope,
  failure,
  futureEvent,
  handoffNotice,
  orderConfirmed,
  orderRejected,
  storedOrder,
  summary,
  systemNotice,
  toolCalled,
  verdict,
} from "../test/factories";
import { sampleEvent } from "../test/samples";
import {
  SURFACE,
  canPressDale,
  initialState,
  nameFinder,
  proposalStatus,
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

describe("an event the chat renders must carry the fields its component reads (W10)", () => {
  const patched = (event: WebEvent, patch: Record<string, unknown>) => {
    const good = event as unknown as { data: Record<string, unknown> };
    return { ...good, data: { ...good.data, ...patch } };
  };
  const brokenLine = (patch: Record<string, unknown>) => {
    const good = summary(1) as unknown as { data: { lines: Record<string, unknown>[] } };
    return patched(summary(1), { lines: [{ ...good.data.lines[0], ...patch }] });
  };

  const confirmedLine = () => {
    const good = orderConfirmed(1) as unknown as { data: { lines: Record<string, unknown>[] } };
    return good.data.lines[0] ?? {};
  };

  it.each<[string, unknown]>([
    ["assistant text that is not a string", patched(assistantText(1), { text: { html: "<b>" } })],
    ["a summary line with no name", brokenLine({ name: undefined })],
    ["a summary line whose quantity is text", brokenLine({ quantity: "2" })],
    ["a summary line whose unit price is a number", brokenLine({ unit_price: 1850 })],
    ["a summary line that is null", patched(summary(1), { lines: [null] })],
    ["a summary with a negative total", patched(summary(1), { total: { cents: -1 } })],
    [
      "a summary with a total past the safe integers",
      patched(summary(1), { total: { cents: 2 ** 53 } }),
    ],
    ["a summary with a fractional total", patched(summary(1), { total: { cents: 1.5 } })],
    ["a summary line with a zero quantity", brokenLine({ quantity: 0 })],
    ["a summary line with a negative quantity", brokenLine({ quantity: -2 })],
    ["a summary line with an unsafe quantity", brokenLine({ quantity: 2 ** 53 })],
    ["a summary line with a fractional quantity", brokenLine({ quantity: 1.5 })],
    ["a summary line with unsafe cents", brokenLine({ line_total: { cents: 2 ** 53 + 2 } })],
    [
      "a confirmation line with a zero quantity",
      patched(orderConfirmed(1), { lines: [{ ...confirmedLine(), quantity: 0 }] }),
    ],
    [
      "a confirmation line with a negative price",
      patched(orderConfirmed(1), { lines: [{ ...confirmedLine(), unit_price: { cents: -5 } }] }),
    ],
    ["a confirmation with no message", patched(orderConfirmed(1), { message: 7 })],
    ["a confirmation with no order id", patched(orderConfirmed(1), { order_id: null })],
    ["a confirmation whose lines are text", patched(orderConfirmed(1), { lines: "x" })],
    ["a rejection with no code", patched(orderRejected(1), { code: undefined })],
    ["a rejection with a list as its message", patched(orderRejected(1), { message: ["a"] })],
    ["a handoff notice with no message", patched(handoffNotice(1), { message: undefined })],
    ["a system notice with no code", patched(systemNotice(1), { code: 3 })],
  ])("drops %s and applies the next good event", (_name, bad) => {
    const batch = envelope({ events: [bad as WebEvent, assistantText(2)], seq: 2 });
    let state = started;
    expect(() => (state = run([received(batch)], started))).not.toThrow();
    expect(state.chat.map((i) => i.kind === "event" && i.event.type)).toEqual(["AssistantText"]);
  });

  it("keeps a well-formed event of every type the chat renders", () => {
    const events = [
      assistantText(1),
      summary(2),
      orderConfirmed(3),
      orderRejected(4),
      handoffNotice(5),
      systemNotice(6),
    ];
    const state = run([received(envelope({ events, seq: 6 }))], started);
    expect(state.chat.map((i) => i.kind === "event" && i.event.type)).toEqual(
      events.map((e) => e.type),
    );
  });

  it.each<[string, unknown]>([
    ["no message", { code: "turn_failed" }],
    ["a message that is not text", { code: "turn_failed", message: { html: "<b>" } }],
    ["no code", { message: "x" }],
  ])("replaces an error body with %s by the page's own error", (_name, bad) => {
    const next = run([received(envelope({ error: bad as never }))], started);
    expect(next.error).toEqual({ code: "malformed_response", message: null });
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
    expect(state.pendingProposalId).toBe(PROPOSAL_A);
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

describe("pending_proposal_id is applied only from an envelope that is not behind (D21)", () => {
  const at7 = run(
    [
      received(
        envelope({
          events: [
            assistantText(1),
            summary(2, PROPOSAL_A),
            assistantText(3),
            assistantText(4),
            assistantText(5),
            summary(6, PROPOSAL_B),
            assistantText(7),
          ],
          pending_proposal_id: PROPOSAL_B,
        }),
      ),
    ],
    started,
  );

  it("takes the pending id of an envelope at or ahead of what the page has", () => {
    expect(at7.pendingProposalId).toBe(PROPOSAL_B);
    const ahead = run(
      [received(envelope({ events: [assistantText(8)], pending_proposal_id: null }))],
      at7,
    );
    expect(ahead.pendingProposalId).toBeNull();
  });

  it("ignores the pending id of an envelope behind the page", () => {
    const stale = envelope({ seq: 4, events: [], pending_proposal_id: PROPOSAL_A });
    expect(run([received(stale)], at7).pendingProposalId).toBe(PROPOSAL_B);
  });

  it("leaves the button alone when a settled press is replayed (B52)", () => {
    const replay = envelope({
      events: [assistantText(3), assistantText(4)],
      seq: 7,
      pending_proposal_id: PROPOSAL_B,
    });
    const after = run([{ type: "request_started", kind: "press" }, received(replay)], at7);
    expect(after.chat).toEqual(at7.chat);
    expect(after.pendingProposalId).toBe(PROPOSAL_B);
    expect(after.inFlight).toBe("none");
  });

  it("does not let an old replay body bring back a pending id the page already moved past", () => {
    const old = envelope({ events: [assistantText(3)], seq: 3, pending_proposal_id: PROPOSAL_A });
    expect(run([received(old)], at7).pendingProposalId).toBe(PROPOSAL_B);
  });

  it("takes the current pair from an error envelope that carries no events (B48)", () => {
    const busy = failure("conversation_busy", { seq: 7, pending_proposal_id: PROPOSAL_B });
    const after = run([received(busy)], at7);
    expect(after.pendingProposalId).toBe(PROPOSAL_B);
    expect(after.error?.code).toBe("conversation_busy");
  });

  it("never touches pending from an envelope that names no conversation", () => {
    const guard = failure("invalid_host", { conversation_id: null, seq: 0 });
    const after = run([received(guard)], at7);
    expect(after.pendingProposalId).toBe(PROPOSAL_B);
    expect(after.error?.code).toBe("invalid_host");
  });

  it("clears pending when the host no longer knows the conversation, so nothing can be pressed", () => {
    const lost = failure("conversation_not_found", { conversation_id: null, seq: 0 });
    expect(run([received(lost)], at7).pendingProposalId).toBeNull();
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

  it("keeps a pending proposal through a failed press, since the outcome is unknown", () => {
    const pending = run(
      [received(envelope({ events: [summary(1)], pending_proposal_id: PROPOSAL_A }))],
      started,
    );
    const after = run(
      [
        { type: "request_started", kind: "press" },
        { type: "request_failed", failure: "network" },
      ],
      pending,
    );
    expect(after.pendingProposalId).toBe(PROPOSAL_A);
    expect(canPressDale(after)).toBe(true);
  });
});

describe("the Dale button rule (S15.4, B66)", () => {
  const pendingA = run(
    [received(envelope({ events: [summary(1, PROPOSAL_A)], pending_proposal_id: PROPOSAL_A }))],
    started,
  );

  it("is enabled only for a rendered summary whose id is the pending id, with nothing in flight", () => {
    expect(canPressDale(pendingA)).toBe(true);
  });

  it("is disabled with no pending proposal", () => {
    expect(canPressDale(started)).toBe(false);
    expect(
      canPressDale(
        run([received(envelope({ events: [summary(1)], pending_proposal_id: null }))], started),
      ),
    ).toBe(false);
  });

  it("is disabled while any request is in flight", () => {
    for (const kind of ["message", "cancel"] as const) {
      const flying = reducer(
        pendingA,
        kind === "message"
          ? { type: "request_started", kind, text: "hola" }
          : { type: "request_started", kind },
      );
      expect(canPressDale(flying)).toBe(false);
    }
    expect(canPressDale(reducer(pendingA, { type: "request_started", kind: "press" }))).toBe(false);
  });

  it("is disabled when the pending id was never rendered as a summary (a lost response)", () => {
    const unseen = run(
      [
        received(
          envelope({ events: [summary(1, PROPOSAL_A)], seq: 2, pending_proposal_id: PROPOSAL_B }),
        ),
      ],
      started,
    );
    expect(unseen.pendingProposalId).toBe(PROPOSAL_B);
    expect(canPressDale(unseen)).toBe(false);
  });

  it("starts a press or a cancel only when the rule allows it", () => {
    expect(reducer(started, { type: "request_started", kind: "press" })).toBe(started);
    expect(reducer(started, { type: "request_started", kind: "cancel" })).toBe(started);
    expect(reducer(pendingA, { type: "request_started", kind: "press" }).inFlight).toBe("press");
    expect(reducer(pendingA, { type: "request_started", kind: "cancel" }).inFlight).toBe("cancel");
  });

  it("never throws on what the reducer stored, and a malformed summary enables nothing", () => {
    const broken = { ...summary(1), data: undefined } as unknown as WebEvent;
    const state = run(
      [
        received(
          envelope({
            events: [broken, null as unknown as WebEvent],
            seq: 1,
            pending_proposal_id: PROPOSAL_A,
          }),
        ),
      ],
      started,
    );
    expect(state.chat).toEqual([]);
    expect(() => canPressDale(state)).not.toThrow();
    expect(canPressDale(state)).toBe(false);
  });

  it("does not start a message before a conversation exists", () => {
    expect(reducer(initialState, { type: "request_started", kind: "message", text: "hola" })).toBe(
      initialState,
    );
  });
});

describe("a cancel the host answered marks that proposal cancelled", () => {
  const pendingA = run(
    [received(envelope({ events: [summary(1, PROPOSAL_A)], pending_proposal_id: PROPOSAL_A }))],
    started,
  );
  const cancelling = run([{ type: "request_started", kind: "cancel" }], pendingA);
  const answer = (patch: Partial<Parameters<typeof envelope>[0]> = {}) =>
    run([received(envelope({ seq: 1, ...patch }))], cancelling);

  it("records the cancelled id, and nothing can press it afterwards", () => {
    const after = answer();
    expect(after.cancelledProposalIds).toEqual([PROPOSAL_A]);
    expect(after.pendingProposalId).toBeNull();
    expect(after.inFlight).toBe("none");
    expect(canPressDale(after)).toBe(false);
    expect(proposalStatus(after, PROPOSAL_A)).toBe("cancelled");
  });

  it("records nothing when the host answered with an error, and the proposal stays pending", () => {
    const busy = run(
      [received(failure("conversation_busy", { seq: 1, pending_proposal_id: PROPOSAL_A }))],
      cancelling,
    );
    expect(busy.cancelledProposalIds).toEqual([]);
    expect(canPressDale(busy)).toBe(true);
  });

  it("records nothing when no answer arrived", () => {
    const lost = run([{ type: "request_failed", failure: "network" }], cancelling);
    expect(lost.cancelledProposalIds).toEqual([]);
    expect(canPressDale(lost)).toBe(true);
  });

  it("records nothing when the host holds another proposal as pending", () => {
    const moved = answer({
      events: [summary(2, PROPOSAL_B)],
      seq: 2,
      pending_proposal_id: PROPOSAL_B,
    });
    expect(moved.cancelledProposalIds).toEqual([]);
    expect(moved.pendingProposalId).toBe(PROPOSAL_B);
  });

  it("records nothing from an answer that is behind what the page has seen", () => {
    expect(answer({ seq: 0 }).cancelledProposalIds).toEqual([]);
  });

  it("records nothing for a request that is not a cancel", () => {
    const pressing = run([{ type: "request_started", kind: "press" }], pendingA);
    expect(run([received(envelope({ seq: 1 }))], pressing).cancelledProposalIds).toEqual([]);
  });

  it("starts again from nothing in a new conversation", () => {
    const fresh = run(
      [
        { type: "request_started", kind: "create" },
        received(envelope({ conversation_id: OTHER_CONVERSATION })),
      ],
      answer(),
    );
    expect(fresh.cancelledProposalIds).toEqual([]);
  });
});

describe("where a proposal stands (S15.5)", () => {
  const facts = (over: Partial<ConversationState>) => ({ ...initialState, ...over });
  const shown = run(
    [
      received(
        envelope({
          events: [summary(1, PROPOSAL_A), summary(2, PROPOSAL_B)],
          pending_proposal_id: PROPOSAL_B,
        }),
      ),
    ],
    started,
  );

  it("is current for the host's pending id and superseded for an older one", () => {
    expect(proposalStatus(shown, PROPOSAL_B)).toBe("current");
    expect(proposalStatus(shown, PROPOSAL_A)).toBe("superseded");
  });

  it("is confirmed once an OrderConfirmed for that id exists, even if it is still pending", () => {
    const done = run(
      [
        received(
          envelope({ events: [orderConfirmed(3, PROPOSAL_B)], pending_proposal_id: PROPOSAL_B }),
        ),
      ],
      shown,
    );
    expect(proposalStatus(done, PROPOSAL_B)).toBe("confirmed");
    expect(proposalStatus(done, PROPOSAL_A)).toBe("superseded");
  });

  it("is cancelled for an id the page cancelled, and confirmed wins over cancelled", () => {
    expect(proposalStatus(facts({ cancelledProposalIds: [PROPOSAL_A] }), PROPOSAL_A)).toBe(
      "cancelled",
    );
    const both = facts({ ...shown, cancelledProposalIds: [PROPOSAL_B] });
    const confirmed = run([received(envelope({ events: [orderConfirmed(3, PROPOSAL_B)] }))], both);
    expect(proposalStatus(confirmed, PROPOSAL_B)).toBe("confirmed");
  });
});

describe("a retired conversation takes no more messages (B65)", () => {
  const lost = run(
    [received(failure("conversation_not_found", { conversation_id: null, seq: 0 }))],
    started,
  );

  it("is marked gone, and a message is refused", () => {
    expect(lost.conversationGone).toBe(true);
    expect(reducer(lost, { type: "request_started", kind: "message", text: "hola" })).toBe(lost);
  });

  it("stays gone through a failed create, and a create's answer replaces it", () => {
    const retry = run(
      [
        { type: "request_started", kind: "create" },
        { type: "request_failed", failure: "network" },
      ],
      lost,
    );
    expect(retry.conversationGone).toBe(true);
    const created = run(
      [
        { type: "request_started", kind: "create" },
        received(envelope({ conversation_id: OTHER_CONVERSATION })),
      ],
      lost,
    );
    expect(created.conversationGone).toBe(false);
    expect(
      reducer(created, { type: "request_started", kind: "message", text: "hola" }).inFlight,
    ).toBe("message");
  });
});

describe("the tool and verdict events are checked at the boundary too (W15)", () => {
  const patched = (event: WebEvent, patch: Record<string, unknown>) => {
    const good = event as unknown as { data: Record<string, unknown> };
    return { ...good, data: { ...good.data, ...patch } };
  };
  const brokenOrder = (patch: Record<string, unknown>) =>
    patched(verdict(1), { stored_orders: [{ ...storedOrder(), ...patch }] });
  const brokenOrderLine = (patch: Record<string, unknown>) =>
    brokenOrder({ lines: [{ ...storedOrder().lines[0], ...patch }] });
  const kinds = (state: ConversationState) => ({
    trace: state.trace.length,
    verdicts: state.verdicts.length,
    chat: state.chat.length,
  });

  it.each<[string, unknown]>([
    ["a tool name that is not text", patched(toolCalled(1), { name: 7 })],
    ["a tool with no summary", patched(toolCalled(1), { summary: undefined })],
    ["a tool whose ok is text", patched(toolCalled(1), { ok: "true" })],
    ["a tool with no ok", patched(toolCalled(1), { ok: undefined })],
    ["a tool whose code is a number", patched(toolCalled(1), { code: 4 })],
    ["a tool with no code field", patched(toolCalled(1), { code: undefined })],
  ])("drops %s and applies the next good event", (_name, bad) => {
    const batch = envelope({ events: [bad as WebEvent, toolCalled(2)], seq: 2 });
    let state = started;
    expect(() => (state = run([received(batch)], started))).not.toThrow();
    expect(kinds(state)).toEqual({ trace: 1, verdicts: 0, chat: 0 });
    expect(state.lastSeq).toBe(2);
  });

  it.each<[string, unknown]>([
    ["a verdict word that is not text", patched(verdict(1), { verdict: 3 })],
    ["a reason that is not text", patched(verdict(1), { reason: null })],
    ["a subject that is not an id", patched(verdict(1), { subject_proposal_id: 5 })],
    ["negative false confirmations", patched(verdict(1), { false_confirmations: -1 })],
    ["fractional unexpected writes", patched(verdict(1), { unexpected_writes: 0.5 })],
    ["findings that are not a list", patched(verdict(1), { findings: {} })],
    ["a finding that is null", patched(verdict(1), { findings: [null] })],
    [
      "a finding whose fields are not text",
      patched(verdict(1), {
        findings: [{ kind: "mismatch", proposal_id: null, order_id: null, fields: [1] }],
      }),
    ],
    ["stored orders that are not a list", patched(verdict(1), { stored_orders: "none" })],
    ["a stored order that is null", patched(verdict(1), { stored_orders: [null] })],
    ["a stored order with no order id", brokenOrder({ order_id: undefined })],
    ["a stored order with no delivery date", brokenOrder({ delivery_date: 20261124 })],
    ["a stored order with a negative total", brokenOrder({ total: { cents: -1 } })],
    ["a stored order with an unsafe total", brokenOrder({ total: { cents: 2 ** 53 } })],
    ["a stored order with a fractional total", brokenOrder({ total: { cents: 0.5 } })],
    ["a stored order whose lines are not a list", brokenOrder({ lines: null })],
    ["a stored line with a zero quantity", brokenOrderLine({ quantity: 0 })],
    ["a stored line with a fractional quantity", brokenOrderLine({ quantity: 1.5 })],
    ["a stored line with a negative price", brokenOrderLine({ unit_price: { cents: -5 } })],
    ["a stored line with unsafe cents", brokenOrderLine({ line_total: { cents: 2 ** 53 } })],
  ])("drops %s and applies the next good event", (_name, bad) => {
    const batch = envelope({ events: [bad as WebEvent, verdict(2)], seq: 2 });
    let state = started;
    expect(() => (state = run([received(batch)], started))).not.toThrow();
    expect(kinds(state)).toEqual({ trace: 0, verdicts: 1, chat: 0 });
    expect(state.lastSeq).toBe(2);
  });

  it("keeps a verdict word or reason it does not know, to show it as not verified", () => {
    const odd = patched(verdict(1), { verdict: "something_new", reason: "exit_3" }) as unknown;
    const state = run([received(envelope({ events: [odd as WebEvent], seq: 1 }))], started);
    expect(kinds(state)).toEqual({ trace: 0, verdicts: 1, chat: 0 });
  });

  it("keeps a verdict with its stored order, and a failed tool with its code", () => {
    const events = [
      toolCalled(1, "confirm", { ok: false, code: "price_changed" }),
      verdict(2, PROPOSAL_A, { verdict: "verified", stored_orders: [storedOrder()] }),
    ];
    const state = run([received(envelope({ events, seq: 2 }))], started);
    expect(kinds(state)).toEqual({ trace: 1, verdicts: 1, chat: 0 });
  });
});

describe("every component the contract names has a place on the page (S4.3, S5.3)", () => {
  it.each(Object.keys(COMPONENTS))(
    "puts a %s sample where SURFACE says its component shows",
    (type) => {
      const event = sampleEvent(type as WebEvent["type"]);
      const state = run([received(envelope({ events: [event], seq: event.seq }))], {
        ...started,
        conversationId: event.conversation_id,
      });
      const surface = SURFACE[COMPONENTS[type as keyof typeof COMPONENTS]];
      expect(state.lastSeq).toBe(event.seq);
      expect({ chat: state.chat.length, trace: state.trace.length, verdict: state.verdicts.length })
        .toEqual({
          chat: surface === "chat" ? 1 : 0,
          trace: surface === "trace" ? 1 : 0,
          verdict: surface === "verdict" ? 1 : 0,
        });
    },
  );

  it("finds a product's name only in the summary for that proposal, else null", () => {
    const state = run([received(envelope({ events: [summary(1)], seq: 1 }))], started);
    const product = "00000000-0000-4000-8000-000000000003";
    expect(nameFinder(state.chat, PROPOSAL_A)(product)).toBe("Harina 000 x 25 kg");
    expect(nameFinder(state.chat, PROPOSAL_B)(product)).toBeNull();
    expect(nameFinder(state.chat, PROPOSAL_A)("other")).toBeNull();
  });
});

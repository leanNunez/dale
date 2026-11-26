import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ClientError, type Api } from "../api/client";
import type { ResponseEnvelope } from "../contract";
import {
  CONVERSATION,
  OTHER_CONVERSATION,
  PROPOSAL_A,
  assistantText,
  envelope,
  summary,
} from "../test/factories";
import { useConversation } from "./useConversation";

/** An API whose replies the test releases by hand, so a request can be held in flight. */
function fakeApi() {
  const waiting: ((reply: ResponseEnvelope | Error) => void)[] = [];
  const hold = () =>
    new Promise<ResponseEnvelope>((resolve, reject) => {
      waiting.push((reply) => (reply instanceof Error ? reject(reply) : resolve(reply)));
    });
  const api = {
    createConversation: vi.fn<Api["createConversation"]>(hold),
    sendMessage: vi.fn<Api["sendMessage"]>(hold),
    press: vi.fn<Api["press"]>(hold),
    cancel: vi.fn<Api["cancel"]>(hold),
  } satisfies Api;
  const release = async (reply: ResponseEnvelope | Error) => {
    await act(async () => {
      waiting.shift()?.(reply);
      await Promise.resolve();
    });
  };
  return { api, release };
}

async function withSummaryShown() {
  const fake = fakeApi();
  const hook = renderHook(() => useConversation(fake.api));
  act(() => hook.result.current.start());
  await fake.release(envelope());
  act(() => hook.result.current.send("dos bolsas de harina"));
  await fake.release(
    envelope({ events: [assistantText(1), summary(2)], pending_proposal_id: PROPOSAL_A }),
  );
  return { ...fake, hook };
}

describe("useConversation", () => {
  it("creates a conversation and holds the page in flight until the host answers", async () => {
    const { api, release } = fakeApi();
    const { result } = renderHook(() => useConversation(api));
    act(() => result.current.start());
    expect(result.current.state.inFlight).toBe("create");

    await release(envelope());
    expect(result.current.state.inFlight).toBe("none");
    expect(result.current.state.conversationId).toBe(CONVERSATION);
  });

  it("starts a new conversation over the one it had and is free once the host answers", async () => {
    const { api, release } = fakeApi();
    const { result } = renderHook(() => useConversation(api));
    act(() => result.current.start());
    await release(envelope({ events: [assistantText(1)] }));

    act(() => result.current.start());
    expect(result.current.state.inFlight).toBe("create");
    await release(envelope({ conversation_id: OTHER_CONVERSATION }));
    expect(result.current.state.inFlight).toBe("none");
    expect(result.current.state.conversationId).toBe(OTHER_CONVERSATION);
    expect(result.current.state.chat).toEqual([]);
  });

  it("sends a message once even if it is called again while the first is in flight", async () => {
    const { api, release } = fakeApi();
    const { result } = renderHook(() => useConversation(api));
    act(() => result.current.start());
    await release(envelope());

    act(() => {
      result.current.send("hola");
      result.current.send("hola otra vez");
    });
    expect(api.sendMessage).toHaveBeenCalledTimes(1);
    expect(api.sendMessage).toHaveBeenCalledWith(CONVERSATION, "hola");
    expect(result.current.state.inFlight).toBe("message");
    await release(envelope({ events: [assistantText(1, "Hola")] }));
    expect(result.current.state.chat.map((line) => line.kind)).toEqual(["customer", "event"]);
  });

  it("creates the conversation first when a message is sent before one exists", async () => {
    const { api, release } = fakeApi();
    const { result } = renderHook(() => useConversation(api));
    act(() => result.current.send("hola"));
    expect(api.createConversation).toHaveBeenCalledTimes(1);
    expect(api.sendMessage).not.toHaveBeenCalled();

    expect(result.current.state.inFlight).toBe("create");

    await release(envelope());
    expect(api.sendMessage).toHaveBeenCalledWith(CONVERSATION, "hola");
    expect(result.current.state.inFlight).toBe("message");
    expect(result.current.state.chat).toEqual([{ kind: "customer", id: 0, text: "hola" }]);
  });

  it("stops after a failed create and sends no message", async () => {
    const { api, release } = fakeApi();
    const { result } = renderHook(() => useConversation(api));
    act(() => result.current.send("hola"));
    await release(new ClientError("network", null));
    expect(api.sendMessage).not.toHaveBeenCalled();
    expect(result.current.state.inFlight).toBe("none");
    expect(result.current.state.error?.code).toBe("network_error");
  });

  it("presses only the pending proposal it rendered, and only once while the press is in flight", async () => {
    const { api, release, hook } = await withSummaryShown();
    expect(hook.result.current.canPress).toBe(true);

    act(() => {
      hook.result.current.press();
      hook.result.current.press();
    });
    expect(api.press).toHaveBeenCalledTimes(1);
    expect(api.press).toHaveBeenCalledWith(CONVERSATION, PROPOSAL_A);
    expect(hook.result.current.canPress).toBe(false);

    await release(envelope({ events: [], seq: 2, pending_proposal_id: null }));
    expect(hook.result.current.canPress).toBe(false);
  });

  it("does not press when there is no pending proposal", async () => {
    const { api, release } = fakeApi();
    const { result } = renderHook(() => useConversation(api));
    act(() => result.current.start());
    await release(envelope());
    act(() => result.current.press());
    expect(api.press).not.toHaveBeenCalled();
  });

  it("presses nothing from a render that predates a cancel the host already answered", async () => {
    const { api, release, hook } = await withSummaryShown();
    const stalePress = hook.result.current.press; // closed over pending A with nothing in flight
    act(() => hook.result.current.cancel());
    await release(envelope({ events: [], seq: 2, pending_proposal_id: null }));

    act(() => stalePress());
    expect(api.press).not.toHaveBeenCalled();
    expect(hook.result.current.state.inFlight).toBe("none");
  });

  it("sends nothing from a render that predates a request still in flight", async () => {
    const { api, hook } = await withSummaryShown();
    const staleCancel = hook.result.current.cancel;
    act(() => hook.result.current.press());
    act(() => staleCancel());
    expect(api.press).toHaveBeenCalledTimes(1);
    expect(api.cancel).not.toHaveBeenCalled();
  });

  it("cancels the pending proposal without a confirm call", async () => {
    const { api, release, hook } = await withSummaryShown();
    act(() => hook.result.current.cancel());
    expect(api.cancel).toHaveBeenCalledWith(CONVERSATION, PROPOSAL_A);
    expect(api.press).not.toHaveBeenCalled();
    await release(envelope({ events: [], seq: 2, pending_proposal_id: null }));
    expect(hook.result.current.state.pendingProposalId).toBeNull();
  });

  it("reports a request that failed and lets the customer try again", async () => {
    const { api, release, hook } = await withSummaryShown();
    act(() => hook.result.current.press());
    await release(new ClientError("network", null));
    expect(hook.result.current.state.error?.code).toBe("network_error");
    expect(hook.result.current.canPress).toBe(true);

    act(() => hook.result.current.press());
    expect(api.press).toHaveBeenCalledTimes(2);
  });

  it("treats an unexpected throw as a malformed reply", async () => {
    const { release, hook } = await withSummaryShown();
    act(() => hook.result.current.press());
    await release(new Error("boom"));
    expect(hook.result.current.state.error?.code).toBe("malformed_response");
  });
});

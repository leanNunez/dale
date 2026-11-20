import { act } from "@testing-library/react";
import { vi } from "vitest";

import type { Api } from "../api/client";
import type { ResponseEnvelope } from "../contract";

/** An API whose replies the test releases by hand, so a request can be held in flight. */
export function fakeApi() {
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

import { afterEach, describe, expect, it, vi } from "vitest";

import { CONVERSATION, PROPOSAL_A, envelope, failure } from "../test/factories";
import { ClientError, createApi } from "./client";

type FetchCall = [input: string, init: RequestInit];

function respond(body: string, status = 200) {
  return vi.fn<(input: string, init: RequestInit) => Promise<Response>>(() =>
    Promise.resolve(new Response(body, { status })),
  );
}
const asFetch = (fn: ReturnType<typeof respond>) => fn as unknown as typeof fetch;
const calls = (fn: ReturnType<typeof respond>) => fn.mock.calls as FetchCall[];

afterEach(() => {
  vi.restoreAllMocks();
});

describe("requests", () => {
  it("creates a conversation with a same-origin relative POST of an empty JSON object", async () => {
    const fetchFn = respond(JSON.stringify(envelope()), 201);
    const reply = await createApi(asFetch(fetchFn)).createConversation();

    const [[url, init]] = calls(fetchFn) as [FetchCall];
    expect(url).toBe("/v1/conversations");
    expect(init.method).toBe("POST");
    expect(init.headers).toEqual({ "Content-Type": "application/json" });
    expect(init.body).toBe("{}");
    expect(reply).toEqual(envelope());
  });

  it("posts each command to its own route with exactly the fields the contract names", async () => {
    const fetchFn = respond(JSON.stringify(envelope()));
    const api = createApi(asFetch(fetchFn));
    await api.sendMessage(CONVERSATION, "Quiero 2 bolsas de harina");
    await api.press(CONVERSATION, PROPOSAL_A);
    await api.cancel(CONVERSATION, PROPOSAL_A);

    const seen = calls(fetchFn).map(([url, init]) => [url, init.method, init.body]);
    const base = `/v1/conversations/${CONVERSATION}`;
    expect(seen).toEqual([
      [`${base}/messages`, "POST", JSON.stringify({ text: "Quiero 2 bolsas de harina" })],
      [`${base}/confirm`, "POST", JSON.stringify({ proposal_id: PROPOSAL_A })],
      [`${base}/cancel`, "POST", JSON.stringify({ proposal_id: PROPOSAL_A })],
    ]);
    for (const [url] of calls(fetchFn)) {
      expect(url.startsWith("/")).toBe(true); // same origin: no scheme, no host
    }
  });

  it("encodes the conversation id so it cannot change the path", async () => {
    const fetchFn = respond(JSON.stringify(envelope()));
    await createApi(asFetch(fetchFn)).sendMessage("a/../b?x=1", "hola");
    expect(calls(fetchFn)[0]?.[0]).toBe("/v1/conversations/a%2F..%2Fb%3Fx%3D1/messages");
  });

  it("sets no timeout and no abort signal: the server bounds a turn (D17, ADR 0011)", async () => {
    const timer = vi.spyOn(globalThis, "setTimeout");
    const abortTimeout = vi.spyOn(AbortSignal, "timeout");
    const fetchFn = respond(JSON.stringify(envelope()));
    await createApi(asFetch(fetchFn)).sendMessage(CONVERSATION, "hola");

    const init = calls(fetchFn)[0]?.[1] ?? {};
    expect(Object.keys(init).sort()).toEqual(["body", "headers", "method"]);
    expect(timer).not.toHaveBeenCalled();
    expect(abortTimeout).not.toHaveBeenCalled();
  });
});

describe("responses", () => {
  it.each([200, 201])("parses a %i body into the envelope", async (status) => {
    const body = envelope({ pending_proposal_id: PROPOSAL_A, seq: 4 });
    const reply = await createApi(
      asFetch(respond(JSON.stringify(body), status)),
    ).sendMessage(CONVERSATION, "hola");
    expect(reply).toEqual(body);
  });

  it.each([404, 409, 422, 500, 503])(
    "parses a %i error envelope instead of throwing, so the page can show its code",
    async (status) => {
      const body = failure("conversation_busy");
      const reply = await createApi(
        asFetch(respond(JSON.stringify(body), status)),
      ).sendMessage(CONVERSATION, "hola");
      expect(reply.error?.code).toBe("conversation_busy");
      expect(reply).toEqual(body);
    },
  );

  it("keeps an event type it was not built for, so the reducer can ignore it", async () => {
    const body = { ...envelope(), events: [{ v: 1, seq: 1, type: "SomethingNew", data: {} }] };
    const reply = await createApi(asFetch(respond(JSON.stringify(body)))).createConversation();
    expect(reply.events).toHaveLength(1);
  });
});

describe("failures that are not an envelope", () => {
  const html = "<html><body><h1>502 Bad Gateway</h1><script>alert(1)</script></body></html>";

  it("rejects an HTML error page as malformed and never carries its text", async () => {
    const error = await createApi(asFetch(respond(html, 502)))
      .createConversation()
      .catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ClientError);
    expect(error).toMatchObject({ kind: "malformed_response", status: 502 });
    expect(String((error as ClientError).message)).not.toContain("<");
    expect(String((error as ClientError).message)).not.toContain("Bad Gateway");
  });

  it.each([
    ["an empty body", ""],
    ["JSON that is not an envelope", '{"detail":"Not Found"}'],
    ["a JSON array", "[]"],
    ["JSON null", "null"],
    ["an envelope of another version", JSON.stringify({ ...envelope(), v: 2 })],
    ["events that are not a list", JSON.stringify({ ...envelope(), events: {} })],
    ["a numeric pending id", JSON.stringify({ ...envelope(), pending_proposal_id: 7 })],
  ])("rejects %s as malformed", async (_name, body) => {
    const error = await createApi(asFetch(respond(body, 200)))
      .createConversation()
      .catch((e: unknown) => e);
    expect(error).toMatchObject({ kind: "malformed_response", status: 200 });
  });

  it("reports a body cut off while it is read as a network failure, not a malformed one", async () => {
    const reset = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('{"v":1,'));
        controller.error(new TypeError("terminated: other side closed"));
      },
    });
    const fetchFn = vi.fn(() => Promise.resolve(new Response(reset, { status: 200 })));
    const error = await createApi(fetchFn as unknown as typeof fetch)
      .createConversation()
      .catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ClientError);
    expect(error).toMatchObject({ kind: "network", status: 200 });
  });

  it("reports a body that was read whole but is not JSON as malformed", async () => {
    const error = await createApi(asFetch(respond('{"v":1,', 200)))
      .createConversation()
      .catch((e: unknown) => e);
    expect(error).toMatchObject({ kind: "malformed_response", status: 200 });
  });

  it("reports a refused connection as a network failure with no status", async () => {
    const fetchFn = vi.fn(() => Promise.reject(new TypeError("Failed to fetch")));
    const error = await createApi(fetchFn as unknown as typeof fetch)
      .createConversation()
      .catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ClientError);
    expect(error).toMatchObject({ kind: "network", status: null });
  });
});

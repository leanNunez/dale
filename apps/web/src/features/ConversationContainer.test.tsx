import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ClientError } from "../api/client";
import { es } from "../i18n/es";
import {
  CONVERSATION,
  PROPOSAL_A,
  PROPOSAL_B,
  assistantText,
  envelope,
  failure,
  orderConfirmed,
  summary,
  systemNotice,
  verdict,
} from "../test/factories";
import { fakeApi } from "../test/fakeApi";
import { ConversationContainer } from "./ConversationContainer";

const dale = () => screen.getByRole("button", { name: es.dale.label });

/** Types one message and returns once the host's reply for it has been released. */
async function say(fake: ReturnType<typeof fakeApi>, reply: Parameters<typeof fake.release>[0]) {
  fireEvent.change(screen.getByLabelText(es.composer.label), { target: { value: "dos harinas" } });
  fireEvent.click(screen.getByRole("button", { name: es.composer.send }));
  await fake.release(envelope()); // the create
  await fake.release(reply);
}

async function withProposalShown() {
  const fake = fakeApi();
  render(<ConversationContainer api={fake.api} />);
  await say(
    fake,
    envelope({ events: [assistantText(1), summary(2)], pending_proposal_id: PROPOSAL_A }),
  );
  return fake;
}

afterEach(() => vi.useRealTimers());

describe("the Dale button (S15.4, B66)", () => {
  it("is disabled before there is any proposal, with the reason said in words", () => {
    render(<ConversationContainer api={fakeApi().api} />);
    expect(dale()).toHaveProperty("disabled", true);
    expect(screen.getByText(es.dale.disabledHint)).toBeTruthy();
  });

  it("is disabled while a message is in flight and enabled once a summary is shown", async () => {
    const fake = fakeApi();
    render(<ConversationContainer api={fake.api} />);
    fireEvent.change(screen.getByLabelText(es.composer.label), { target: { value: "hola" } });
    fireEvent.click(screen.getByRole("button", { name: es.composer.send }));
    await fake.release(envelope());
    expect(dale()).toHaveProperty("disabled", true);
    await fake.release(
      envelope({ events: [assistantText(1), summary(2)], pending_proposal_id: PROPOSAL_A }),
    );
    expect(dale()).toHaveProperty("disabled", false);
    expect(screen.getByText(es.dale.enabledHint)).toBeTruthy();
  });

  it("is disabled from the click until the response arrives, and presses one proposal once", async () => {
    const fake = await withProposalShown();
    fireEvent.click(dale());
    fireEvent.click(dale());
    expect(fake.api.press).toHaveBeenCalledExactlyOnceWith(CONVERSATION, PROPOSAL_A);
    expect(dale()).toHaveProperty("disabled", true);
    expect(screen.getByText(es.dale.busyHint)).toBeTruthy();

    await fake.release(
      envelope({ events: [orderConfirmed(3), verdict(4)], seq: 4, pending_proposal_id: null }),
    );
    expect(dale()).toHaveProperty("disabled", true);
    expect(screen.getByRole("article", { name: es.confirmation.title })).toBeTruthy();
  });

  it("stays disabled when the pending id was never shown as a summary (a lost response)", async () => {
    const fake = fakeApi();
    render(<ConversationContainer api={fake.api} />);
    await say(fake, envelope({ events: [assistantText(1)], pending_proposal_id: PROPOSAL_A }));
    expect(dale()).toHaveProperty("disabled", true);
  });

  it("is not pressed by typing dale: that text only goes to the model as a message", async () => {
    const fake = await withProposalShown();
    fireEvent.change(screen.getByLabelText(es.composer.label), { target: { value: "dale" } });
    fireEvent.click(screen.getByRole("button", { name: es.composer.send }));
    expect(fake.api.press).not.toHaveBeenCalled();
    expect(fake.api.sendMessage).toHaveBeenLastCalledWith(CONVERSATION, "dale");
  });

  it("shows the stale-page notice and the summary the host now holds as pending (S15.5)", async () => {
    const fake = fakeApi();
    render(<ConversationContainer api={fake.api} />);
    await say(
      fake,
      envelope({
        events: [summary(1, PROPOSAL_A), summary(2, PROPOSAL_B)],
        pending_proposal_id: PROPOSAL_B,
      }),
    );
    fireEvent.click(dale());
    await fake.release(
      failure("proposal_not_pending", {
        events: [systemNotice(3, "proposal_not_pending"), verdict(4, null)],
        seq: 4,
        pending_proposal_id: PROPOSAL_A,
      }),
    );
    expect(screen.getAllByText("Ya no se puede.")).toHaveLength(1); // the chat's notice, once
    const cards = screen.getAllByRole("article", { name: es.summary.title });
    expect(
      cards.map((card) => within(card).queryByText(es.summary.status.current) !== null),
    ).toEqual([true, false]);
    expect(
      cards.map((card) => within(card).queryByText(es.summary.status.superseded) !== null),
    ).toEqual([false, true]);
    expect(dale()).toHaveProperty("disabled", false);
  });
});

describe("async states (S16.1)", () => {
  it("shows what it waits for and the elapsed seconds in Spanish, and holds the composer", async () => {
    vi.useFakeTimers();
    const fake = fakeApi();
    render(<ConversationContainer api={fake.api} />);
    fireEvent.change(screen.getByLabelText(es.composer.label), { target: { value: "hola" } });
    fireEvent.click(screen.getByRole("button", { name: es.composer.send }));
    expect(screen.getByRole("status").textContent).toContain(`${es.pending.create}…`);
    expect(screen.getByText("0 s")).toBeTruthy();
    await fake.release(envelope());
    act(() => vi.advanceTimersByTime(5000));
    expect(screen.getByRole("status").textContent).toContain(`${es.pending.message}…`);
    expect(screen.getByText("5 s")).toBeTruthy();
    expect(screen.getByRole("button", { name: es.composer.send })).toHaveProperty("disabled", true);
    await fake.release(envelope({ events: [assistantText(1)] }));
    expect(screen.queryByText(/…/)).toBeNull();
  });

  it("shows the host's catalog message as an alert and frees the page for a retry", async () => {
    const fake = fakeApi();
    render(<ConversationContainer api={fake.api} />);
    await say(fake, failure("turn_failed"));
    expect(screen.getByRole("alert").textContent).toContain("Mensaje fijo");
    expect(screen.getByRole("button", { name: es.composer.send })).toBeTruthy();
  });

  it.each([
    ["network", es.errors.network_error],
    ["malformed_response", es.errors.malformed_response],
  ] as const)("words a %s failure in Spanish itself", async (kind, text) => {
    const fake = fakeApi();
    render(<ConversationContainer api={fake.api} />);
    fireEvent.change(screen.getByLabelText(es.composer.label), { target: { value: "hola" } });
    fireEvent.click(screen.getByRole("button", { name: es.composer.send }));
    await fake.release(new ClientError(kind, null));
    expect(screen.getByRole("alert").textContent).toContain(text);
  });

  it("keeps the press possible after a press whose answer was lost", async () => {
    const fake = await withProposalShown();
    fireEvent.click(dale());
    await fake.release(new ClientError("network", null));
    expect(screen.getByRole("alert").textContent).toContain(es.errors.network_error);
    expect(dale()).toHaveProperty("disabled", false);
  });

  it("says the conversation is gone and offers a new one that opens on click (B65)", async () => {
    const fake = await withProposalShown();
    fireEvent.click(dale());
    await fake.release(
      failure("conversation_not_found", { conversation_id: null, pending_proposal_id: null }),
    );
    expect(screen.getByRole("alert").textContent).toContain(es.errors.conversation_not_found);
    expect(dale()).toHaveProperty("disabled", true);
    fireEvent.click(screen.getByRole("button", { name: es.newConversation }));
    expect(fake.api.createConversation).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("alert")).toBeNull(); // a new request clears the old error
    expect(screen.getByRole("status").textContent).toContain(es.pending.create);
    await fake.release(envelope({ conversation_id: PROPOSAL_B }));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("log", { name: es.chat.title }).textContent).toContain(es.chat.empty);
  });
});

describe("model text never becomes markup (S10.2)", () => {
  it("shows assistant text with an image tag as characters and creates no element", async () => {
    const fake = fakeApi();
    const { container } = render(<ConversationContainer api={fake.api} />);
    await say(fake, envelope({ events: [assistantText(1, "<img src=x onerror=alert(1)>")] }));
    expect(container.textContent).toContain("<img src=x onerror=alert(1)>");
    expect(container.querySelector("img")).toBeNull();
  });

  it("does not crash on an event whose text is not a string: it is left out", async () => {
    const fake = fakeApi();
    render(<ConversationContainer api={fake.api} />);
    const bad = { ...assistantText(1), data: { text: { html: "<b>" } } };
    await say(fake, envelope({ events: [bad as never, assistantText(2, "sigue")], seq: 2 }));
    expect(screen.getByText("sigue")).toBeTruthy();
  });
});

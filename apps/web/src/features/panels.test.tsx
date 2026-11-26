// The page driven with the contract's own sample envelopes (no model, no host): what the chat
// and the three panels show for a turn, a press, a mismatch and a verifier that did not run.
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ResponseEnvelope } from "../contract";
import { es } from "../i18n/es";
import {
  envelope,
  failure,
  orderConfirmed,
  storedOrder,
  systemNotice,
  toolCalled,
  verdict,
} from "../test/factories";
import { fakeApi } from "../test/fakeApi";
import { sampleEnvelope, sampleEvent } from "../test/samples";
import { ConversationContainer } from "./ConversationContainer";

const panel = (title: string) => screen.getByRole("region", { name: title });
const proposal = sampleEnvelope().pending_proposal_id ?? "";

/** Opens a conversation by sending one message; the host answers with `reply`. */
async function turn(reply: ResponseEnvelope) {
  const fake = fakeApi();
  const view = render(<ConversationContainer api={fake.api} />);
  fireEvent.change(screen.getByLabelText(es.composer.label), { target: { value: "harina" } });
  fireEvent.click(screen.getByRole("button", { name: es.composer.send }));
  await fake.release(envelope());
  await fake.release(reply);
  return { fake, view };
}

async function press(fake: ReturnType<typeof fakeApi>, reply: ResponseEnvelope) {
  fireEvent.click(screen.getByRole("button", { name: es.dale.label }));
  await fake.release(reply);
}

describe("the layout: the chat and three panels with Spanish titles (S16.1)", () => {
  it("shows the chat and the three panels, each under its own heading, with their empty states", () => {
    render(<ConversationContainer api={fakeApi().api} />);
    const headings = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(headings).toEqual([
      es.chat.title,
      es.panels.trace.title,
      es.panels.order.title,
      es.panels.verdict.title,
    ]);
    expect(within(panel(es.panels.trace.title)).getByText(es.panels.trace.empty)).toBeTruthy();
    expect(within(panel(es.panels.order.title)).getByText(es.panels.order.noVerdict)).toBeTruthy();
    expect(within(panel(es.panels.verdict.title)).getByText(es.panels.verdict.empty)).toBeTruthy();
  });

  it("stacks on small screens and sits side by side only from the large breakpoint", () => {
    const { container } = render(<ConversationContainer api={fakeApi().api} />);
    const grid = container.firstElementChild as HTMLElement;
    expect(grid.className).toContain("lg:grid-cols-");
    expect(grid.className.split(" ").filter((name) => /^grid-cols-/.test(name))).toEqual([]);
  });

  it("uses no inline style anywhere, which the page's CSP would block", async () => {
    const { view } = await turn(sampleEnvelope());
    expect(view.container.querySelectorAll("[style]")).toHaveLength(0);
  });
});

describe("a turn and a press with the sample envelopes (S15.1, S15.2)", () => {
  it("lists the turn's tool in the trace panel as text", async () => {
    await turn(sampleEnvelope());
    const trace = within(panel(es.panels.trace.title));
    expect(trace.getByText("search_products")).toBeTruthy();
    expect(trace.getByText('{"query":"harina 000"}')).toBeTruthy();
    expect(trace.getByRole("listitem").textContent).toContain(es.panels.trace.ok);
  });

  it("shows the stored order and a verified verdict after the press, not before", async () => {
    const { fake } = await turn(sampleEnvelope());
    expect(
      within(panel(es.panels.order.title)).getByText(es.panels.order.noVerdict),
    ).toBeTruthy();

    const issued = sampleEvent("VerdictIssued");
    await press(
      fake,
      envelope({ events: [orderConfirmed(3, proposal), issued], seq: 8, pending_proposal_id: null }),
    );
    const order = within(panel(es.panels.order.title));
    expect(order.getByText(/Harina 000 x 25 kg/)).toBeTruthy(); // the name from the shown summary
    expect(order.getByText(/2 ×/)).toBeTruthy();
    expect(order.getAllByText("$ 3.700,00").length).toBeGreaterThan(0);
    expect(panel(es.panels.verdict.title).textContent).toContain(es.panels.verdict.label.verified);
  });

  it("shows the stored order as read when the verdict is a mismatch, not the order shown in chat (S15.3)", async () => {
    const { fake } = await turn(sampleEnvelope());
    const read = storedOrder(proposal, {
      lines: [
        {
          product_id: "00000000-0000-4000-8000-000000000003",
          quantity: 2,
          unit_price: { cents: 180000 },
          line_total: { cents: 360000 },
        },
      ],
      total: { cents: 360000 },
    });
    const mismatch = verdict(8, proposal, {
      verdict: "mismatch",
      false_confirmations: 1,
      findings: [{ kind: "mismatch", proposal_id: proposal, order_id: null, fields: ["total"] }],
      stored_orders: [read],
    });
    await press(
      fake,
      envelope({ events: [orderConfirmed(3, proposal), mismatch], seq: 8, pending_proposal_id: null }),
    );
    const order = panel(es.panels.order.title);
    expect(order.textContent).toContain("$ 3.600,00");
    expect(order.textContent).not.toContain("$ 3.700,00");
    const chat = screen.getByRole("log");
    expect(chat.textContent).toContain("$ 3.700,00"); // the chat still says what the host said
    const verdictText = panel(es.panels.verdict.title).textContent ?? "";
    expect(verdictText).toContain(es.panels.verdict.label.mismatch);
    expect(verdictText).not.toContain(es.panels.verdict.label.verified);
  });

  it("says there is no stored order when the verifier found none", async () => {
    const { fake } = await turn(sampleEnvelope());
    const missing = verdict(8, proposal, { verdict: "missing" });
    await press(
      fake,
      envelope({ events: [orderConfirmed(3, proposal), missing], seq: 8, pending_proposal_id: null }),
    );
    expect(panel(es.panels.order.title).textContent).toContain(
      "No hay un pedido guardado en la base",
    );
  });
});

describe("a press the verifier could not judge is not shown as an order fault (B62, B101)", () => {
  it("reads 'No se pudo verificar' after a turn and does not claim the database is empty", async () => {
    const { fake } = await turn(sampleEnvelope());
    const none = verdict(8, proposal, { verdict: "unverifiable", reason: "verifier_error" });
    await press(
      fake,
      envelope({ events: [none], seq: 8, pending_proposal_id: proposal }),
    );
    const text = panel(es.panels.verdict.title).textContent ?? "";
    expect(text).toContain(es.panels.verdict.label.unverifiable);
    expect(text).not.toContain("Todavía");
    expect(text).toContain(es.panels.verdict.unverifiableNote);
    expect(panel(es.panels.order.title).textContent).toContain(es.panels.order.unreadable);
    expect(panel(es.panels.order.title).textContent).not.toContain(es.panels.order.none);
  });
});

describe("the host's answer to a press that names no proposal (B62, captured from a running host)", () => {
  it("shows the verifier_error verdict with no proposal beside the notice, as a failed check", async () => {
    const { fake } = await turn(sampleEnvelope());
    await press(
      fake,
      failure("proposal_not_found", {
        events: [
          systemNotice(3, "proposal_not_found"),
          verdict(4, null, { verdict: "unverifiable", reason: "verifier_error" }),
        ],
        seq: 4,
        pending_proposal_id: null,
      }),
    );
    const text = panel(es.panels.verdict.title).textContent ?? "";
    expect(text).toContain(es.panels.verdict.label.unverifiable); // a turn came first: not "yet"
    expect(text).toContain(es.panels.verdict.noProposal);
    expect(panel(es.panels.order.title).textContent).toContain(es.panels.order.unreadable);
  });
});

describe("hostile tool text in the page (B15)", () => {
  it("makes a bidi override and a line separator visible and adds no element", async () => {
    const hostile = toolCalled(1, "\u202Eevil<img src=x>", { summary: "a\u2028b" });
    await turn(envelope({ events: [hostile], seq: 1 }));
    const trace = panel(es.panels.trace.title);
    expect(trace.textContent).toContain("⟨U+202E⟩evil<img src=x>");
    expect(trace.textContent).toContain("a⟨U+2028⟩b");
    expect(trace.textContent).not.toMatch(/[\u202E\u2028]/);
    expect(trace.querySelector("img")).toBeNull();
  });
});

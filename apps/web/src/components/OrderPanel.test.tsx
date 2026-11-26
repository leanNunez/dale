import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ChatItem } from "../state/reducer";
import type { StoredOrder, VerdictIssuedEvent } from "../contract";
import { es } from "../i18n/es";
import { PROPOSAL_A, PROPOSAL_B, storedOrder, summary, verdict } from "../test/factories";
import { sampleEvent } from "../test/samples";
import { OrderPanel } from "./OrderPanel";

const PRODUCT = "00000000-0000-4000-8000-000000000003";
const asVerdict = (event: ReturnType<typeof verdict>) => event as VerdictIssuedEvent;
const chatWith = (...seqs: [number, string][]): ChatItem[] =>
  seqs.map(([seq, id]) => ({ kind: "event", event: summary(seq, id) }) as ChatItem);
const shows = (verdicts: VerdictIssuedEvent[], chat: ChatItem[] = []) =>
  render(<OrderPanel verdicts={verdicts} chat={chat} />).container.textContent ?? "";
const verified = (seq: number, orders = [storedOrder()]) =>
  asVerdict(verdict(seq, PROPOSAL_A, { verdict: "verified", stored_orders: orders }));

describe("the order panel shows the order as the verifier read it (S15.2, D19)", () => {
  it("shows the lines and total of the sample's stored order, with the name from the summary", () => {
    const sampleVerdict = sampleEvent("VerdictIssued");
    const proposal = sampleVerdict.data.subject_proposal_id ?? "";
    const text = shows([sampleVerdict], chatWith([2, proposal]));
    expect(text).toContain("Harina 000 x 25 kg");
    expect(text).toContain("2 ×");
    expect(text).toContain("$ 1.850,00");
    expect(text).toContain("$ 3.700,00");
    expect(text).toContain("20/11/2026");
  });

  it("falls back to the product's short id when the page showed no summary for that proposal", () => {
    const unnamed = storedOrder(PROPOSAL_A, {
      lines: [
        {
          product_id: "abcdef12-0000-4000-8000-000000000003",
          quantity: 2,
          unit_price: { cents: 185000 },
          line_total: { cents: 370000 },
        },
      ],
    });
    const text = shows([verified(4, [unnamed])], chatWith([2, PROPOSAL_B]));
    expect(text).not.toContain("Harina");
    expect(text).toContain("2 × abcdef12");
  });

  it("has a Spanish heading and says where the order comes from", () => {
    shows([verified(4)]);
    expect(screen.getByRole("heading", { name: es.panels.order.title })).toBeTruthy();
    expect(screen.getByText(es.panels.order.lead)).toBeTruthy();
  });
});

describe("a verdict that is not verified shows the order as read, not as shown in chat (S15.3)", () => {
  it("shows the stored total and quantity even when the chat summary says something else", () => {
    const changed = storedOrder(PROPOSAL_A, {
      total: { cents: 360000 },
      lines: [
        {
          product_id: PRODUCT,
          quantity: 3,
          unit_price: { cents: 120000 },
          line_total: { cents: 360000 },
        },
      ],
    });
    const mismatch = asVerdict(
      verdict(5, PROPOSAL_A, { verdict: "mismatch", stored_orders: [changed] }),
    );
    const text = shows([mismatch], chatWith([2, PROPOSAL_A])); // the chat said 2 × and $ 3.700,00
    expect(text).toContain("3 ×");
    expect(text).toContain("$ 3.600,00");
    expect(text).not.toContain("$ 3.700,00");
    expect(text).not.toContain("2 ×");
  });

  it("shows an order of another proposal after the proposal's own, and says so", () => {
    const own = storedOrder(PROPOSAL_A, { order_id: "11111111-0000-4000-8000-000000000001" });
    const other = storedOrder("bbbbbbbb-0000-4000-8000-000000000002", {
      order_id: "22222222-0000-4000-8000-000000000002",
    });
    const unexpected = asVerdict(
      verdict(5, PROPOSAL_A, { verdict: "unexpected_write", stored_orders: [other, own] }),
    );
    render(<OrderPanel verdicts={[unexpected]} chat={[]} />);
    const items = screen.getAllByRole("heading", { level: 3 }).map((h) => h.parentElement);
    expect(items.map((item) => item?.querySelector("h3")?.textContent)).toEqual([
      `${es.panels.order.order} 11111111`,
      `${es.panels.order.order} 22222222`,
    ]);
    expect(items[0]?.textContent).toContain(`${es.panels.order.fromProposal}: 00000000`);
    expect(items[1]?.textContent).toContain(`${es.panels.order.otherProposal}: bbbbbbbb`);
  });
});

describe("with no stored order the panel says so truthfully", () => {
  it("says there is no order in the database when the verifier found none (S11.4)", () => {
    const missing = asVerdict(verdict(5, PROPOSAL_A, { verdict: "missing" }));
    expect(shows([missing])).toContain("No hay un pedido guardado en la base");
  });

  it("says there is no order in the database for a press with nothing confirmed", () => {
    expect(shows([asVerdict(verdict(5))])).toContain(es.panels.order.none);
  });

  it("does not claim the database is empty when the verifier could not read it", () => {
    const failed = asVerdict(
      verdict(5, PROPOSAL_A, { verdict: "unverifiable", reason: "verifier_error" }),
    );
    const text = shows([failed]);
    expect(text).toContain(es.panels.order.unreadable);
    expect(text).not.toContain(es.panels.order.none);
  });

  it("says it appears after the first verification when there is no verdict yet", () => {
    expect(shows([])).toContain(es.panels.order.noVerdict);
  });
});

describe("which verdict the panel follows", () => {
  const unexpected = (seq: number, orders: StoredOrder[]) =>
    asVerdict(verdict(seq, null, { verdict: "unexpected_write", stored_orders: orders }));
  const first = storedOrder(PROPOSAL_A, { order_id: "11111111-0000-4000-8000-000000000001" });
  const second = storedOrder(PROPOSAL_B, { order_id: "22222222-0000-4000-8000-000000000002" });

  it("shows the latest press of a proposal, replacing an earlier one", () => {
    const earlier = asVerdict(verdict(3, PROPOSAL_A, { verdict: "missing" }));
    const text = shows([earlier, verified(6)]);
    expect(text).toContain("$ 3.700,00");
    expect(text).not.toContain(es.panels.order.none);
  });

  it("shows exactly the orders of a later press with no proposal, all of another proposal", () => {
    render(<OrderPanel verdicts={[verified(6), unexpected(8, [first, second])]} chat={[]} />);
    const items = screen.getAllByRole("heading", { level: 3 }).map((h) => h.parentElement);
    expect(items.map((item) => item?.querySelector("h3")?.textContent)).toEqual([
      `${es.panels.order.order} 11111111`,
      `${es.panels.order.order} 22222222`,
    ]);
    for (const item of items) {
      expect(item?.textContent).toContain(es.panels.order.otherProposal);
      expect(item?.textContent).not.toContain(`${es.panels.order.fromProposal}:`);
    }
  });

  it("shows no order of an earlier press when the latest one read none", () => {
    const text = shows([verified(6), asVerdict(verdict(8, null))]);
    expect(text).not.toContain("$ 3.700,00");
    expect(text).toContain(es.panels.order.none);
  });

  it("shows only that the base could not be read after an unverifiable press, with no stale order", () => {
    const failed = asVerdict(
      verdict(8, PROPOSAL_A, { verdict: "unverifiable", reason: "verifier_error" }),
    );
    const text = shows([verified(6), failed]);
    expect(text).toContain(es.panels.order.unreadable);
    expect(text).not.toContain("$ 3.700,00");
    expect(text).not.toContain(es.panels.order.none);
    expect(screen.queryAllByRole("heading", { level: 3 })).toHaveLength(0);
  });
});

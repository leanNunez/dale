import { cleanup, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ToolCalledEvent, VerdictIssuedEvent } from "../contract";
import { es } from "../i18n/es";
import type { ChatItem } from "../state/reducer";
import { PROPOSAL_A, assistantText, storedOrder, toolCalled, verdict } from "../test/factories";
import { sampleEvent } from "../test/samples";
import { VerdictPanel } from "./VerdictPanel";

const label = es.panels.verdict.label;
const asVerdict = (event: ReturnType<typeof verdict>) => event as VerdictIssuedEvent;
const said = (seq: number): ChatItem => ({ kind: "event", event: assistantText(seq) }) as ChatItem;
const used = (seq: number) => toolCalled(seq) as ToolCalledEvent;
const shows = (events: VerdictIssuedEvent[], chat: ChatItem[] = [], trace: ToolCalledEvent[] = []) => {
  const view = render(<VerdictPanel verdicts={events} chat={chat} trace={trace} />);
  return view.container.textContent ?? "";
};

describe("the verdict panel says what the verifier found, in words and a mark (S15.3)", () => {
  it("shows the sample verdict as verified, with the proposal it judged", () => {
    const text = shows([sampleEvent("VerdictIssued")]);
    expect(text).toContain(label.verified);
    expect(text).toContain("00000000"); // the proposal's short id
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
  });

  it.each([
    ["mismatch", label.mismatch],
    ["missing", label.missing],
    ["unexpected_write", label.unexpected_write],
    ["nothing_confirmed", label.nothing_confirmed],
  ] as const)("shows %s as a Spanish label that never says verified", (word, text) => {
    const shown = shows([asVerdict(verdict(3, PROPOSAL_A, { verdict: word }))]);
    expect(shown).toContain(text);
    expect(shown).not.toContain(label.verified);
  });

  it.each([
    ["verified", "✔"],
    ["mismatch", "✖"],
    ["missing", "✖"],
    ["unexpected_write", "✖"],
    ["nothing_confirmed", "○"],
    ["unverifiable", "⚠"],
  ] as const)("marks %s with %s as well as the words, so color is never the only sign", (word, mark) => {
    shows([asVerdict(verdict(3, PROPOSAL_A, { verdict: word }))]);
    const marker = screen.getByRole("listitem").querySelector('[aria-hidden="true"]');
    expect(marker?.textContent?.trim()).toBe(mark);
    expect(screen.getByRole("listitem").textContent?.length).toBeGreaterThan(mark.length + 10);
  });

  it("names the fields that differ in a mismatch", () => {
    const finding = { kind: "mismatch", proposal_id: PROPOSAL_A, order_id: null, fields: ["total"] };
    const text = shows([
      asVerdict(verdict(3, PROPOSAL_A, { verdict: "mismatch", findings: [finding as never] })),
    ]);
    expect(text).toContain(`${es.panels.verdict.differs}: total`);
  });

  it("names each differing field in Spanish, and an unknown one as the host sent it", () => {
    const fields = ["lines", "total", "delivery_date", "order_count", "customer", "something_new"];
    const finding = { kind: "mismatch", proposal_id: PROPOSAL_A, order_id: null, fields };
    const text = shows([
      asVerdict(verdict(3, PROPOSAL_A, { verdict: "mismatch", findings: [finding as never] })),
    ]);
    expect(text).toContain(
      `${es.panels.verdict.differs}: líneas, total, fecha de entrega, cantidad de pedidos, cliente, something_new`,
    );
    expect(text).not.toContain("delivery_date");
  });

  it("labels every field the verifier can name, and a prototype key stays as it came", () => {
    const named = ["company", "proposal", "order_id", "message", "zone", "minimum", "delivery_rule"];
    const finding = { kind: "mismatch", proposal_id: PROPOSAL_A, order_id: null, fields: [...named, "__proto__"] };
    const text = shows([
      asVerdict(verdict(3, PROPOSAL_A, { verdict: "mismatch", findings: [finding as never] })),
    ]);
    for (const field of named) {
      expect(text).not.toContain(field);
      expect(Object.keys(es.panels.verdict.fields)).toContain(field);
    }
    expect(text).toContain("__proto__");
  });

  it("lists every press's verdict in the order the host sent them", () => {
    shows([
      asVerdict(verdict(3, PROPOSAL_A, { verdict: "mismatch" })),
      asVerdict(verdict(6, PROPOSAL_A, { verdict: "verified", stored_orders: [storedOrder()] })),
    ]);
    const items = screen.getAllByRole("listitem").map((item) => item.textContent ?? "");
    expect(items[0]).toContain(label.mismatch);
    expect(items[1]).toContain(label.verified);
  });

  it("says that a verdict is shown without a proposal when none was pending", () => {
    expect(shows([asVerdict(verdict(3, null))])).toContain(es.panels.verdict.noProposal);
  });
});

describe("a verdict the verifier could not give is not an order fault (B37, B62)", () => {
  const unverifiable = (reason: string) =>
    asVerdict(verdict(3, PROPOSAL_A, { verdict: "unverifiable", reason: reason as never }));

  const faults = [label.mismatch, label.missing, label.unexpected_write, label.verified];

  it("reads 'Todavía no se pudo verificar' for the verifier_error of a press before any turn", () => {
    const text = shows([unverifiable("verifier_error")]);
    expect(text).toContain("Todavía no se pudo verificar");
    expect(text).toContain(es.panels.verdict.unverifiableNote);
    for (const fault of faults) expect(text).not.toContain(fault);
  });

  it.each([
    ["an assistant turn", [said(2)], []],
    ["a tool call", [], [used(2)]],
  ])("reads 'No se pudo verificar' for a verifier_error after %s: the verifier failed", (_what, chat, trace) => {
    const text = shows([unverifiable("verifier_error")], chat, trace);
    expect(text).toContain(label.unverifiable);
    expect(text).not.toContain("Todavía");
    expect(text).toContain(es.panels.verdict.reasons.verifier_error);
    expect(text).toContain(es.panels.verdict.unverifiableNote);
    for (const fault of faults) expect(text).not.toContain(fault);
  });

  it("judges each verifier_error by the turns before it, not by the page's last state", () => {
    shows([unverifiable("verifier_error"), asVerdict(verdict(9, PROPOSAL_A, { verdict: "unverifiable", reason: "verifier_error" }))], [said(5)]);
    const items = screen.getAllByRole("listitem").map((item) => item.textContent ?? "");
    expect(items[0]).toContain("Todavía no se pudo verificar");
    expect(items[1]).not.toContain("Todavía");
    expect(items[1]).toContain(label.unverifiable);
  });

  it.each(Object.entries(es.panels.verdict.reasons).filter(([key]) => key !== "verifier_error"))(
    "shows the Spanish reason for %s",
    (reason, text) => {
      const shown = shows([unverifiable(reason)]);
      expect(shown).toContain(label.unverifiable);
      expect(shown).toContain(text);
      expect(shown).toContain(es.panels.verdict.unverifiableNote);
    },
  );

  it("shows a reason it does not know as unverifiable, in Spanish", () => {
    const text = shows([unverifiable("exit_3")]);
    expect(text).toContain(label.unverifiable);
    expect(text).toContain(es.panels.verdict.unknownReason);
  });

  it.each(["__proto__", "constructor", "toString", "hasOwnProperty"])(
    "reads %s as a verdict or a reason as not verified: the page renders and never says verified",
    (word) => {
      const asWord = shows([asVerdict(verdict(3, PROPOSAL_A, { verdict: word as never }))]);
      expect(asWord).toContain(label.unknown);
      expect(asWord).not.toContain(label.verified);
      cleanup();
      const asReason = shows([unverifiable(word)]);
      expect(asReason).toContain(label.unverifiable);
      expect(asReason).toContain(es.panels.verdict.unknownReason);
      expect(asReason).not.toContain(label.verified);
    },
  );

  it("never reads a verdict word it does not know as verified", () => {
    const text = shows([asVerdict(verdict(3, PROPOSAL_A, { verdict: "all_good" as never }))]);
    expect(text).toContain(label.unknown);
    expect(text).not.toContain(label.verified);
  });
});

describe("the verdict panel as a region", () => {
  it("has a Spanish heading and an empty state before any press", () => {
    const text = shows([]);
    expect(screen.getByRole("heading", { name: es.panels.verdict.title })).toBeTruthy();
    expect(text).toContain(es.panels.verdict.empty);
    expect(screen.queryByRole("list")).toBeNull();
  });

  it("announces a new verdict politely and holds no status role of its own", () => {
    const { container } = render(<VerdictPanel verdicts={[]} chat={[]} trace={[]} />);
    expect(container.querySelector('[aria-live="polite"]')).not.toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

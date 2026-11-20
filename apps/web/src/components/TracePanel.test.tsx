import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ToolCalledEvent } from "../contract";
import { es } from "../i18n/es";
import { toolCalled } from "../test/factories";
import { sampleEnvelope, sampleEvent } from "../test/samples";
import { TracePanel } from "./TracePanel";

const tool = (seq: number, name?: string, patch: Partial<ToolCalledEvent["data"]> = {}) =>
  toolCalled(seq, name, patch) as ToolCalledEvent;

describe("the trace panel lists each tool with its summary and result (S15.1)", () => {
  it("shows the sample's tool by name, summary and a word for its result", () => {
    render(<TracePanel trace={[sampleEvent("ToolCalled")]} />);
    const item = screen.getByRole("listitem");
    expect(within(item).getByText("search_products")).toBeTruthy();
    expect(within(item).getByText('{"query":"harina 000"}')).toBeTruthy();
    expect(item.textContent).toContain(es.panels.trace.ok);
  });

  it("shows a failed tool as an error with its code in Spanish as text, not by color", () => {
    const failed = tool(2, "confirm", { ok: false, code: "price_changed" });
    render(<TracePanel trace={[failed]} />);
    const text = screen.getByRole("listitem").textContent;
    expect(text).toContain(`${es.panels.trace.error}: ${es.panels.trace.codes.price_changed}`);
    expect(text).not.toContain("price_changed");
    expect(text).not.toContain(es.panels.trace.ok);
  });

  it.each(Object.entries(es.panels.trace.codes))("labels the shared code %s in Spanish", (code, label) => {
    render(<TracePanel trace={[tool(2, "confirm", { ok: false, code: code as never })]} />);
    const text = screen.getByRole("listitem").textContent ?? "";
    expect(text).toContain(label);
    expect(text).not.toContain(code);
  });

  it("shows a code it has no label for as the host sent it", () => {
    render(<TracePanel trace={[tool(2, "confirm", { ok: false, code: "brand_new_code" as never })]} />);
    expect(screen.getByRole("listitem").textContent).toContain(`${es.panels.trace.error}: brand_new_code`);
  });

  it.each(["__proto__", "constructor", "toString"])("does not read %s as a labelled code", (code) => {
    render(<TracePanel trace={[tool(2, "confirm", { ok: false, code: code as never })]} />);
    expect(screen.getByRole("listitem").textContent).toContain(`${es.panels.trace.error}: ${code}`);
  });

  it("shows a failed tool with no code as an error", () => {
    render(<TracePanel trace={[tool(2, "confirm", { ok: false })]} />);
    expect(screen.getByRole("listitem").textContent).toContain(es.panels.trace.error);
  });

  it("lists the tools of the sample envelope in the order the host sent them", () => {
    const events = sampleEnvelope().events.filter((e) => e.type === "ToolCalled");
    render(<TracePanel trace={[...events, tool(9, "get_prices")]} />);
    const names = screen.getAllByRole("listitem").map((item) => item.querySelector("bdi")?.textContent);
    expect(names).toEqual(["search_products", "get_prices"]);
  });

  it("says in Spanish that no tool was used yet, under a heading of its own", () => {
    render(<TracePanel trace={[]} />);
    expect(screen.getByRole("heading", { name: es.panels.trace.title })).toBeTruthy();
    expect(screen.getByText(es.panels.trace.empty)).toBeTruthy();
    expect(screen.queryByRole("list")).toBeNull();
  });
});

describe("tool text is model-controlled and cannot break the page (B15, S10.2)", () => {
  const MARKUP = "<img src=x onerror=alert(1)>";

  it("shows markup in the name, summary and code as literal characters and creates no element", () => {
    const hostile = tool(1, MARKUP, { summary: MARKUP, ok: false, code: MARKUP as never });
    const { container } = render(<TracePanel trace={[hostile]} />);
    expect(container.textContent?.split(MARKUP).length).toBe(4);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("[onerror]")).toBeNull();
  });

  it.each([
    ["a right-to-left override", "\u202Egnp.exe"],
    ["a left-to-right embedding", "a\u202Ab"],
    ["an isolate", "a\u2067b\u2069"],
    ["a right-to-left mark", "a\u200Fb"],
    ["a line separator", "one\u2028two"],
    ["a paragraph separator", "one\u2029two"],
    ["a line feed", "one\ntwo"],
    ["a zero-width space", "one\u200Btwo"],
  ])("makes %s visible instead of acting on it", (_what, text) => {
    const { container } = render(
      <TracePanel trace={[tool(1, text, { summary: text, ok: false, code: text as never })]} />,
    );
    const shown = container.textContent ?? "";
    expect(shown).not.toMatch(/[\u202A-\u202E\u2066-\u2069\u200B-\u200F\u2028\u2029\n]/);
    expect(shown).toMatch(/⟨U\+[0-9A-F]{4}⟩/);
  });

  it("keeps each model-controlled field in its own isolated element", () => {
    const { container } = render(
      <TracePanel trace={[tool(1, "\u202Ename", { summary: "\u202Esummary" })]} />,
    );
    const isolated = Array.from(container.querySelectorAll("li bdi"));
    expect(isolated.map((el) => el.textContent)).toEqual(["⟨U+202E⟩name", "⟨U+202E⟩summary"]);
  });
});

describe("an unbroken name, summary or code stays inside its card", () => {
  // jsdom does no layout, so the guarantee is checked as the class that makes the browser wrap
  // (`overflow-wrap: anywhere`, which also shrinks the min-content width a grid column would
  // otherwise grow to); the real width is covered by the browser smoke on the built page.
  const LONG = "x".repeat(64);

  it("wraps the name, the summary and the code anywhere, with no inline style", () => {
    const failed = tool(1, LONG, { summary: LONG, ok: false, code: LONG as never });
    const { container } = render(<TracePanel trace={[failed]} />);
    const paragraphs = Array.from(container.querySelectorAll("li > p"));
    expect(paragraphs).toHaveLength(3);
    for (const paragraph of paragraphs) {
      expect(paragraph.className).toContain("break-words");
      expect(paragraph.className).toContain("[overflow-wrap:anywhere]");
    }
    expect(container.querySelectorAll("[style]")).toHaveLength(0);
  });

  it("keeps the same wrapping once invisible characters are expanded into long text", () => {
    const padded = `${LONG}\u202E${LONG}\u200B${LONG}`;
    const { container } = render(<TracePanel trace={[tool(1, padded, { summary: padded })]} />);
    const name = container.querySelector("li > p");
    expect(name?.textContent).toBe(`${LONG}⟨U+202E⟩${LONG}⟨U+200B⟩${LONG}`);
    expect(name?.className).toContain("[overflow-wrap:anywhere]");
  });
});

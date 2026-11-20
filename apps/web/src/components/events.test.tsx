import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { OrderConfirmedEvent, ProposalSummaryEvent } from "../contract";
import { es } from "../i18n/es";
import { orderConfirmed, summary } from "../test/factories";
import { ChatText } from "./ChatText";
import { HandoffNotice } from "./HandoffNotice";
import { Notice } from "./Notice";
import { OrderConfirmation } from "./OrderConfirmation";
import { OrderSummary } from "./OrderSummary";

const MARKUP = "<img src=x onerror=alert(1)>";

/** Whatever a component renders from a model-controlled string must stay literal text. */
function expectLiteral(container: HTMLElement) {
  expect(container.textContent).toContain(MARKUP);
  expect(container.querySelector("img")).toBeNull();
  expect(container.querySelector("[onerror]")).toBeNull();
}

const summaryData = (summary(1) as ProposalSummaryEvent).data;
const confirmedData = (orderConfirmed(1) as OrderConfirmedEvent).data;

describe("model-controlled text is rendered as text (S10.2)", () => {
  it("shows assistant text with markup as literal characters and creates no element", () => {
    const { container } = render(<ChatText who="assistant" text={MARKUP} />);
    expectLiteral(container);
  });

  it("shows the customer's own text as literal characters too", () => {
    const { container } = render(<ChatText who="customer" text={MARKUP} />);
    expectLiteral(container);
  });

  it("shows a product name with markup as literal characters in the summary", () => {
    const lines = summaryData.lines.map((line) => ({ ...line, name: MARKUP }));
    const { container } = render(
      <OrderSummary data={{ ...summaryData, lines }} status="current" />,
    );
    expectLiteral(container);
  });

  it("shows a confirmation message and a looked-up name with markup as literal characters", () => {
    const { container } = render(
      <OrderConfirmation data={{ ...confirmedData, message: MARKUP }} nameOf={() => MARKUP} />,
    );
    expectLiteral(container);
    expect(container.textContent?.split(MARKUP).length).toBe(3); // the message and the name
  });

  it("shows notice and handoff text with markup as literal characters", () => {
    expectLiteral(render(<Notice kind="notice" message={MARKUP} />).container);
    expectLiteral(render(<Notice kind="error" message={MARKUP} />).container);
    expectLiteral(render(<HandoffNotice message={MARKUP} />).container);
  });
});

describe("what each component shows", () => {
  it("shows a summary's lines, delivery date and total, and says it is not confirmed yet", () => {
    render(<OrderSummary data={summaryData} status="current" />);
    expect(screen.getByText(/Harina 000 x 25 kg/)).toBeTruthy();
    expect(screen.getByText("24/11/2026")).toBeTruthy();
    expect(screen.getByText("$ 3.700,00", { selector: "dd" })).toBeTruthy();
    expect(screen.getByText(es.summary.notConfirmed)).toBeTruthy();
  });

  it.each([
    ["current", es.summary.status.current, true],
    ["confirmed", es.summary.status.confirmed, false],
    ["cancelled", es.summary.status.cancelled, false],
    ["superseded", es.summary.status.superseded, false],
  ] as const)("says in words that a %s proposal is so", (status, text, notConfirmed) => {
    render(<OrderSummary data={summaryData} status={status} />);
    expect(screen.getByText(text)).toBeTruthy();
    for (const other of Object.values(es.summary.status)) {
      if (other !== text) expect(screen.queryByText(other)).toBeNull();
    }
    // "Not confirmed yet" is true only of the proposal Dale could still confirm.
    expect(screen.queryByText(es.summary.notConfirmed) !== null).toBe(notConfirmed);
  });

  it("names a confirmed line from the shown proposal, or by the short product id", () => {
    const { rerender } = render(
      <OrderConfirmation data={confirmedData} nameOf={() => "Harina 000 x 25 kg"} />,
    );
    expect(screen.getByText(/Harina 000 x 25 kg/)).toBeTruthy();
    rerender(<OrderConfirmation data={confirmedData} nameOf={() => null} />);
    expect(screen.getByText(/00000000: \$ 3\.700,00/)).toBeTruthy();
  });

  it("announces an error as an alert and a notice as a status, each with a word for its kind", () => {
    const { rerender } = render(<Notice kind="error" message="Falló" />);
    expect(screen.getByRole("alert").textContent).toContain(es.notice.errorTitle);
    rerender(<Notice kind="notice" message="Aviso del host" />);
    expect(screen.getByRole("status").textContent).toContain(es.notice.title);
  });

  it("adds no live region of its own when it sits in one that announces it already", () => {
    const { container, rerender } = render(<Notice kind="notice" message="Aviso" live={false} />);
    expect(container.querySelector("[role]")).toBeNull();
    expect(container.textContent).toContain(es.notice.title);
    rerender(<Notice kind="error" message="Falló" live={false} />);
    expect(container.querySelector("[role]")).toBeNull();
    expect(container.textContent).toContain(es.notice.errorTitle);
  });
});

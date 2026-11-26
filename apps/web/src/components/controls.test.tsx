import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { es } from "../i18n/es";
import type { WebEvent } from "../contract";
import type { ChatEvent, ChatItem } from "../state/reducer";
import {
  PROPOSAL_A,
  PROPOSAL_B,
  assistantText,
  handoffNotice,
  orderConfirmed,
  orderRejected,
  summary,
  systemNotice,
} from "../test/factories";
import { ChatPane } from "./ChatPane";
import { DaleButton } from "./DaleButton";
import { PendingStatus } from "./PendingStatus";

describe("DaleButton", () => {
  it("is a real button with a clear Spanish name, disabled with its reason when not enabled", () => {
    render(<DaleButton enabled={false} busy={false} onPress={vi.fn()} />);
    const button = screen.getByRole("button", { name: es.dale.label });
    expect(button).toHaveProperty("disabled", true);
    expect(button.getAttribute("type")).toBe("button");
    expect(button.getAttribute("aria-describedby")).toBeTruthy();
    expect(screen.getByText(es.dale.disabledHint)).toBeTruthy();
  });

  it("says it is waiting while a request runs, and presses nothing", () => {
    const onPress = vi.fn();
    render(<DaleButton enabled={false} busy onPress={onPress} />);
    expect(screen.getByText(es.dale.busyHint)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: es.dale.label }));
    expect(onPress).not.toHaveBeenCalled();
  });

  it("presses once per click when enabled, and can take the keyboard's focus", () => {
    const onPress = vi.fn();
    render(<DaleButton enabled busy={false} onPress={onPress} />);
    const button = screen.getByRole("button", { name: es.dale.label });
    button.focus();
    expect(document.activeElement).toBe(button);
    fireEvent.click(button);
    expect(onPress).toHaveBeenCalledTimes(1);
    expect(screen.getByText(es.dale.enabledHint)).toBeTruthy();
  });
});

describe("PendingStatus", () => {
  afterEach(() => vi.useRealTimers());

  it("names what it waits for and counts the seconds from when the action began", () => {
    vi.useFakeTimers();
    render(<PendingStatus kind="message" since={Date.now()} />);
    expect(screen.getByRole("status").textContent).toContain(`${es.pending.message}…`);
    expect(screen.getByText("0 s")).toBeTruthy();
    act(() => vi.advanceTimersByTime(3000));
    expect(screen.getByText("3 s")).toBeTruthy();
  });

  it("counts from the time it is given, not from when it appeared", () => {
    vi.useFakeTimers();
    render(<PendingStatus kind="message" since={Date.now() - 7000} />);
    expect(screen.getByText("7 s")).toBeTruthy();
  });

  it("announces the start only: the live region holds the label, never the seconds", () => {
    vi.useFakeTimers();
    render(<PendingStatus kind="message" since={Date.now()} />);
    const region = screen.getByRole("status");
    expect(region.textContent).not.toMatch(/\d/);
    act(() => vi.advanceTimersByTime(5000));
    expect(region.textContent).not.toMatch(/\d/);
    expect(region.textContent).toContain(es.pending.message);
    const counter = screen.getByText("5 s");
    expect(counter.closest("[role='status'], [aria-live]")).toBeNull();
    expect(screen.getAllByRole("status")).toHaveLength(1);
  });

  it("says what a press waits for, in Spanish", () => {
    render(<PendingStatus kind="press" since={Date.now()} />);
    expect(screen.getByRole("status").textContent).toContain(es.pending.press);
  });

  it("stops counting when it is removed", () => {
    vi.useFakeTimers();
    const { unmount } = render(<PendingStatus kind="create" since={Date.now()} />);
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe("ChatPane", () => {
  const host = (event: WebEvent): ChatItem => ({ kind: "event", event: event as ChatEvent });
  const chat: ChatItem[] = [
    { kind: "customer", id: 0, text: "dos bolsas de harina" },
    host(assistantText(1, "Te armo la propuesta.")),
    host(summary(2, PROPOSAL_A)),
    host(summary(3, PROPOSAL_B)),
    host(orderRejected(4)),
    host(systemNotice(5)),
    host(handoffNotice(6)),
  ];

  it("shows an empty conversation with a Spanish invitation", () => {
    render(<ChatPane chat={[]} pendingProposalId={null} cancelledProposalIds={[]} />);
    expect(screen.getByRole("log", { name: es.chat.title }).textContent).toContain(es.chat.empty);
  });

  it("shows every item in the order it happened, as text", () => {
    render(<ChatPane chat={chat} pendingProposalId={PROPOSAL_B} cancelledProposalIds={[]} />);
    const log = screen.getByRole("log", { name: es.chat.title });
    const text = log.textContent ?? "";
    const order = [
      "dos bolsas de harina",
      "Te armo la propuesta.",
      es.summary.title,
      "Cambió el precio.",
      "Ya no se puede.",
      "Te contacta una persona.",
    ];
    const positions = order.map((part) => text.indexOf(part));
    expect(positions.every((position) => position >= 0)).toBe(true);
    expect([...positions].sort((a, b) => a - b)).toEqual(positions);
  });

  it("marks only the summary the host holds as pending as the current one (S15.5)", () => {
    render(<ChatPane chat={chat} pendingProposalId={PROPOSAL_B} cancelledProposalIds={[]} />);
    expect(screen.getAllByText(es.summary.status.current)).toHaveLength(1);
    expect(screen.getAllByText(es.summary.status.superseded)).toHaveLength(1);
  });

  it("marks no summary as current when nothing is pending", () => {
    render(<ChatPane chat={chat} pendingProposalId={null} cancelledProposalIds={[]} />);
    expect(screen.queryByText(es.summary.status.current)).toBeNull();
    expect(screen.getAllByText(es.summary.status.superseded)).toHaveLength(2);
  });

  it("says a summary is confirmed, not 'not yet confirmed', once its order exists", () => {
    const confirmed = [host(summary(1, PROPOSAL_A)), host(orderConfirmed(2, PROPOSAL_A))];
    render(<ChatPane chat={confirmed} pendingProposalId={PROPOSAL_A} cancelledProposalIds={[]} />);
    expect(screen.getByText(es.summary.status.confirmed)).toBeTruthy();
    expect(screen.queryByText(es.summary.notConfirmed)).toBeNull();
    expect(screen.queryByText(es.summary.status.current)).toBeNull();
  });

  it("says a summary the page cancelled is cancelled, and no summary is current", () => {
    const shown = [host(summary(1, PROPOSAL_A)), host(summary(2, PROPOSAL_B))];
    render(<ChatPane chat={shown} pendingProposalId={null} cancelledProposalIds={[PROPOSAL_B]} />);
    expect(screen.getAllByText(es.summary.status.cancelled)).toHaveLength(1);
    expect(screen.getAllByText(es.summary.status.superseded)).toHaveLength(1);
    expect(screen.queryByText(es.summary.status.current)).toBeNull();
  });

  it("adds no live region inside the log: its notices are announced by the log itself", () => {
    render(<ChatPane chat={chat} pendingProposalId={PROPOSAL_B} cancelledProposalIds={[]} />);
    const log = screen.getByRole("log", { name: es.chat.title });
    expect(within(log).queryAllByRole("status")).toHaveLength(0);
    expect(within(log).queryAllByRole("alert")).toHaveLength(0);
    expect(log.textContent).toContain("Ya no se puede.");
  });

  it("names a confirmed product from the summary of the same proposal", () => {
    const confirmed = [host(summary(1, PROPOSAL_A)), host(orderConfirmed(2, PROPOSAL_A))];
    render(<ChatPane chat={confirmed} pendingProposalId={null} cancelledProposalIds={[]} />);
    expect(screen.getAllByText(/Harina 000 x 25 kg/)).toHaveLength(2);
    expect(screen.getByRole("article", { name: es.confirmation.title })).toBeTruthy();
  });

  it("falls back to the short product id when the proposal was never shown", () => {
    render(
      <ChatPane
        chat={[host(orderConfirmed(1, PROPOSAL_B))]}
        pendingProposalId={null}
        cancelledProposalIds={[]}
      />,
    );
    expect(screen.getByText(/00000000: \$ 3\.700,00/)).toBeTruthy();
  });
});

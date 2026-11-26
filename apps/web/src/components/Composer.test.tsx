import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { es } from "../i18n/es";
import { Composer } from "./Composer";

describe("Composer", () => {
  const field = () => screen.getByLabelText(es.composer.label) as HTMLTextAreaElement;
  const accepting = () => vi.fn<(text: string) => Promise<boolean>>().mockResolvedValue(true);
  const type = (value: string) => fireEvent.change(field(), { target: { value } });
  /** A send the test settles by hand: the host's answer arrives after the customer kept typing. */
  function held() {
    let settle: (accepted: boolean) => void = () => undefined;
    const onSend = vi.fn<(text: string) => Promise<boolean>>(
      () => new Promise<boolean>((resolve) => (settle = resolve)),
    );
    return { onSend, settle: (accepted: boolean) => act(async () => settle(accepted)) };
  }

  afterEach(() => vi.useRealTimers());

  it("sends what was typed, trimmed, and clears the field once the host took it", async () => {
    const onSend = accepting();
    render(<Composer disabled={false} onSend={onSend} />);
    type("  dos bolsas de harina \n");
    await act(async () => fireEvent.click(screen.getByRole("button", { name: es.composer.send })));
    expect(onSend).toHaveBeenCalledExactlyOnceWith("dos bolsas de harina");
    expect(field().value).toBe("");
  });

  it("keeps the text while the host has not answered, and when it did not take the message", async () => {
    const pending = held();
    render(<Composer disabled={false} onSend={pending.onSend} />);
    type("dos bolsas");
    fireEvent.click(screen.getByRole("button", { name: es.composer.send }));
    expect(field().value).toBe("dos bolsas");
    await pending.settle(false);
    expect(field().value).toBe("dos bolsas");
  });

  it("clears only what was sent: words typed while it waited stay", async () => {
    const pending = held();
    render(<Composer disabled={false} onSend={pending.onSend} />);
    type("dos bolsas");
    fireEvent.click(screen.getByRole("button", { name: es.composer.send }));
    type("dos bolsas y un cajón");
    await pending.settle(true);
    expect(field().value).toBe("dos bolsas y un cajón");
  });

  it("keeps the text when the send itself fails", async () => {
    const onSend = vi.fn<(text: string) => Promise<boolean>>().mockRejectedValue(new Error("x"));
    render(<Composer disabled={false} onSend={onSend} />);
    type("hola");
    await act(async () => fireEvent.click(screen.getByRole("button", { name: es.composer.send })));
    expect(field().value).toBe("hola");
  });

  it("sends nothing when the text is blank", () => {
    const onSend = accepting();
    render(<Composer disabled={false} onSend={onSend} />);
    type("   ");
    expect(screen.getByRole("button", { name: es.composer.send })).toHaveProperty("disabled", true);
    fireEvent.keyDown(field(), { key: "Enter" });
    expect(onSend).not.toHaveBeenCalled();
  });

  it("sends nothing while a request is running, by button or by Enter, and keeps the text", () => {
    const onSend = accepting();
    render(<Composer disabled onSend={onSend} />);
    type("dale");
    expect(screen.getByRole("button", { name: es.composer.send })).toHaveProperty("disabled", true);
    fireEvent.keyDown(field(), { key: "Enter" });
    expect(onSend).not.toHaveBeenCalled();
    expect(field().value).toBe("dale");
  });

  it("sends on Enter and breaks the line on Shift+Enter", async () => {
    const onSend = accepting();
    render(<Composer disabled={false} onSend={onSend} />);
    type("hola");
    fireEvent.keyDown(field(), { key: "Enter", shiftKey: true });
    expect(onSend).not.toHaveBeenCalled();
    await act(async () => fireEvent.keyDown(field(), { key: "Enter" }));
    expect(onSend).toHaveBeenCalledExactlyOnceWith("hola");
  });

  describe("an Enter that belongs to an IME does not send", () => {
    it.each([
      ["a key flagged as composing", { key: "Enter", isComposing: true }],
      ["a key with keyCode 229", { key: "Enter", keyCode: 229 }],
      [
        "Process, the key some browsers report during a composition",
        { key: "Process", keyCode: 229 },
      ],
    ])("ignores %s", (_name, key) => {
      const onSend = accepting();
      render(<Composer disabled={false} onSend={onSend} />);
      type("こんにちは");
      fireEvent.keyDown(field(), key);
      expect(onSend).not.toHaveBeenCalled();
    });

    it("ignores an Enter while a composition is open, even when the key claims otherwise", () => {
      const onSend = accepting();
      render(<Composer disabled={false} onSend={onSend} />);
      type("こんにちは");
      fireEvent.compositionStart(field());
      fireEvent.keyDown(field(), { key: "Enter", keyCode: 13 });
      expect(onSend).not.toHaveBeenCalled();
    });

    it("ignores an Enter in the same tick as compositionend (Safari), and sends in the next", async () => {
      vi.useFakeTimers();
      const onSend = accepting();
      render(<Composer disabled={false} onSend={onSend} />);
      type("こんにちは");
      fireEvent.compositionStart(field());
      fireEvent.compositionEnd(field());
      fireEvent.keyDown(field(), { key: "Enter", keyCode: 13 });
      expect(onSend).not.toHaveBeenCalled();
      act(() => vi.advanceTimersByTime(1));
      await act(async () => fireEvent.keyDown(field(), { key: "Enter", keyCode: 13 }));
      expect(onSend).toHaveBeenCalledExactlyOnceWith("こんにちは");
    });

    it("leaves no timer behind when it is removed right after a composition", () => {
      vi.useFakeTimers();
      const { unmount } = render(<Composer disabled={false} onSend={accepting()} />);
      fireEvent.compositionEnd(field());
      unmount();
      expect(vi.getTimerCount()).toBe(0);
    });
  });

  it("only sends: typed text is not a confirmation, and the page says so", () => {
    render(<Composer disabled={false} onSend={accepting()} />);
    expect(screen.getByText(es.composer.hint)).toBeTruthy();
    expect(field().maxLength).toBe(2000);
  });
});

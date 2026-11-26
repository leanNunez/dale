import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { es } from "../i18n/es";
import { CancelButton } from "./CancelButton";

describe("CancelButton", () => {
  const button = () => screen.getByRole("button", { name: es.cancel.label });

  it("is a real button, disabled with its reason when not enabled, and cancels nothing", () => {
    const onCancel = vi.fn();
    render(<CancelButton enabled={false} onCancel={onCancel} />);
    expect(button()).toHaveProperty("disabled", true);
    expect(button().getAttribute("type")).toBe("button");
    expect(button().getAttribute("aria-describedby")).toBeTruthy();
    expect(screen.getByText(es.cancel.disabledHint)).toBeTruthy();
    fireEvent.click(button());
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("cancels once per click when enabled, and can take the keyboard's focus", () => {
    const onCancel = vi.fn();
    render(<CancelButton enabled onCancel={onCancel} />);
    button().focus();
    expect(document.activeElement).toBe(button());
    fireEvent.click(button());
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(screen.getByText(es.cancel.enabledHint)).toBeTruthy();
  });
});

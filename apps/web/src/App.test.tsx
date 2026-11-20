import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import { App } from "./App";
import { es } from "./i18n/es";

it("renders the page title in Spanish", () => {
  render(<App />);
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Dale");
});

it("opens with the chat, the composer and a disabled Dale button, and calls nothing", () => {
  render(<App />);
  expect(screen.getByRole("log", { name: es.chat.title })).toBeTruthy();
  expect(screen.getByLabelText(es.composer.label)).toBeTruthy();
  expect(screen.getByRole("button", { name: es.dale.label })).toHaveProperty("disabled", true);
  expect(screen.queryByRole("status")).toBeNull();
});

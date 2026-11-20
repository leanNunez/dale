import { describe, expect, it } from "vitest";

import { dateLabel, pesos, shortId } from "./format";

describe("formatting plain data", () => {
  it.each([
    [0, "$ 0,00"],
    [5, "$ 0,05"],
    [100, "$ 1,00"],
    [370000, "$ 3.700,00"],
    [4900000, "$ 49.000,00"],
    [123456789, "$ 1.234.567,89"],
  ])("writes %i cents as %s, like the terminal", (cents, text) => {
    expect(pesos(cents)).toBe(text);
  });

  it("writes an ISO date as day, month and year, and leaves anything else as it came", () => {
    expect(dateLabel("2026-11-24")).toBe("24/11/2026");
    expect(dateLabel("mañana")).toBe("mañana");
  });

  it("keeps the first group of an id", () => {
    expect(shortId("00000000-0000-4000-8000-0000000000c3")).toBe("00000000");
  });
});

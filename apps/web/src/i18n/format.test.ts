import { describe, expect, it } from "vitest";

import { dateLabel, pesos, shortId, visible } from "./format";

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

  it("leaves ordinary text, accents and emoji alone", () => {
    expect(visible('{"query":"harina 000 ñandú"}')).toBe('{"query":"harina 000 ñandú"}');
    expect(visible("tilde á, flecha →, mate 🧉")).toBe("tilde á, flecha →, mate 🧉");
  });

  it.each([
    ["\u202E", "⟨U+202E⟩"],
    ["\u202A", "⟨U+202A⟩"],
    ["\u2066", "⟨U+2066⟩"],
    ["\u2069", "⟨U+2069⟩"],
    ["\u200F", "⟨U+200F⟩"],
    ["\u061C", "⟨U+061C⟩"],
    ["\u200B", "⟨U+200B⟩"],
    ["\u2028", "⟨U+2028⟩"],
    ["\u2029", "⟨U+2029⟩"],
    ["\n", "⟨U+000A⟩"],
    ["\r", "⟨U+000D⟩"],
    ["\u0085", "⟨U+0085⟩"],
    ["\u0000", "⟨U+0000⟩"],
  ])("shows %j as %s", (char, shown) => {
    expect(visible(`a${char}b`)).toBe(`a${shown}b`);
  });
});

describe("visible also shows the characters that draw as nothing", () => {
  it.each([
    ["Hangul filler U+3164", "\u3164", "⟨U+3164⟩"],
    ["Hangul choseong filler U+115F", "\u115F", "⟨U+115F⟩"],
    ["Hangul jungseong filler U+1160", "\u1160", "⟨U+1160⟩"],
    ["halfwidth Hangul filler U+FFA0", "\uFFA0", "⟨U+FFA0⟩"],
    ["variation selector U+FE0F", "\uFE0F", "⟨U+FE0F⟩"],
    ["combining grapheme joiner U+034F", "\u034F", "⟨U+034F⟩"],
    ["soft hyphen U+00AD", "\u00AD", "⟨U+00AD⟩"],
    ["blank Braille U+2800", "\u2800", "⟨U+2800⟩"],
    ["variation selector U+E0100 (astral)", "\u{E0100}", "⟨U+E0100⟩"],
    ["tag letter U+E0041 (astral)", "\u{E0041}", "⟨U+E0041⟩"],
    ["musical beam format U+1D173 (astral)", "\u{1D173}", "⟨U+1D173⟩"],
  ])("shows %s", (_what, char, shown) => {
    expect(visible(`a${char}b`)).toBe(`a${shown}b`);
  });

  it("cannot hide a lookalike behind padding", () => {
    expect(visible("conf\u3164irm\u2800")).toBe("conf⟨U+3164⟩irm⟨U+2800⟩");
  });

  it("leaves a space, a no-break space and an astral emoji alone", () => {
    expect(visible("a b\u00A0c 🧉")).toBe("a b\u00A0c 🧉");
  });
});


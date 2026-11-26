// Formatting for what the host sends as plain data: integer cents, ISO dates, UUIDs.

/** Argentine notation as the terminal prints it: `$ 49.000,00`. Integer cents, no floats. */
export function pesos(cents: number): string {
  const value = BigInt(cents);
  const whole = (value / 100n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return `$ ${whole},${(value % 100n).toString().padStart(2, "0")}`;
}

/** `2026-11-24` as `24/11/2026`; anything else is shown as the host sent it. */
export function dateLabel(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  return match ? `${match[3]}/${match[2]}/${match[1]}` : iso;
}

/** The first group of an id: enough to tell two apart on screen. */
export function shortId(id: string): string {
  return id.slice(0, 8);
}

/** What `visible` shows instead of itself; the global flag is reset by `replace` on each call. */
const HIDDEN = /[\p{Cc}\p{Cf}\p{Zl}\p{Zp}\p{Default_Ignorable_Code_Point}\u2800]/gu;

/**
 * Model-controlled text with its invisible characters made visible, each as `⟨U+XXXX⟩`. Covered:
 * controls (`Cc`, a line break), format characters (`Cf`: every bidirectional override,
 * embedding, isolate and mark, zero-width joiners, tag characters), the line and paragraph
 * separators (`Zl`, `Zp`) and every Default_Ignorable_Code_Point (the Hangul fillers U+115F,
 * U+1160, U+3164 and U+FFA0, the variation selectors such as U+FE0F, U+034F, the soft hyphen).
 * U+2800, the blank Braille cell, is not default-ignorable but draws as empty padding, so it is
 * listed on its own. Nothing in it can reorder the text around it, start a new line or pad a
 * lookalike, and what was there can be read. Other spacing characters are left alone: they show
 * as spaces. A variation selector in a model's emoji shows too, which is the price of the rule.
 */
export function visible(text: string): string {
  return text.replace(HIDDEN, (char) => {
    const code = (char.codePointAt(0) ?? 0).toString(16).toUpperCase().padStart(4, "0");
    return `⟨U+${code}⟩`;
  });
}

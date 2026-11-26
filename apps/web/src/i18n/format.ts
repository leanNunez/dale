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

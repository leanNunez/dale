import { useEffect, useState } from "react";

import type { InFlight } from "../state/reducer";
import { es } from "../i18n/es";

interface Props {
  kind: Exclude<InFlight, "none">;
  /** When the customer's action began (`Date.now()`): one send keeps one clock across its requests. */
  since: number;
}

/**
 * A request is running and the host has no deadline (B6), so the page says what it waits for and
 * for how long. Only the start is announced: the label is the one live region, and the seconds
 * sit outside it so a screen reader is not interrupted every tick.
 */
export function PendingStatus({ kind, since }: Props) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const seconds = Math.max(0, Math.floor((now - since) / 1000));
  return (
    <div className="flex flex-wrap items-baseline gap-x-2 text-sm font-medium text-slate-800">
      <p role="status">
        <span aria-hidden="true">⏳ </span>
        {es.pending[kind]}…
      </p>
      <p>
        {seconds} {es.pending.seconds}
      </p>
    </div>
  );
}

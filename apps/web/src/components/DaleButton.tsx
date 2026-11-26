import { useId } from "react";

import { es } from "../i18n/es";

interface Props {
  /** The page's rule (`canPressDale`): nothing here decides whether a press is possible. */
  enabled: boolean;
  /** A request is running while a proposal waits: the button says it comes back with the answer. */
  busy: boolean;
  onPress: () => void;
}

/** The one decisive action: it confirms the pending proposal and nothing else does. */
export function DaleButton({ enabled, busy, onPress }: Props) {
  const hintId = useId();
  const hint = enabled ? es.dale.enabledHint : busy ? es.dale.busyHint : es.dale.disabledHint;
  return (
    <div className="flex flex-col gap-1">
      <button
        type="button"
        disabled={!enabled}
        aria-describedby={hintId}
        onClick={onPress}
        className="rounded-lg border-2 border-emerald-950 bg-emerald-800 px-6 py-3 text-lg font-bold text-white hover:bg-emerald-900 focus-visible:outline-4 focus-visible:outline-offset-2 focus-visible:outline-emerald-950 active:bg-emerald-950 disabled:cursor-not-allowed disabled:border-dashed disabled:border-slate-500 disabled:bg-slate-200 disabled:text-slate-700"
      >
        {es.dale.label}
      </button>
      <p id={hintId} className="text-sm text-slate-700">
        {hint}
      </p>
    </div>
  );
}

import { useId } from "react";

import { es } from "../i18n/es";

interface Props {
  /** The page's rule (`canPressDale`): the same proposal Dale would confirm is the one cancelled. */
  enabled: boolean;
  onCancel: () => void;
}

/** The secondary action: it discards the pending proposal so Dale can no longer confirm it. */
export function CancelButton({ enabled, onCancel }: Props) {
  const hintId = useId();
  return (
    <div className="flex flex-col gap-1">
      <button
        type="button"
        disabled={!enabled}
        aria-describedby={hintId}
        onClick={onCancel}
        className="rounded-lg border-2 border-slate-900 bg-white px-4 py-3 font-semibold text-slate-900 hover:bg-slate-100 focus-visible:outline-4 focus-visible:outline-offset-2 focus-visible:outline-slate-900 active:bg-slate-200 disabled:cursor-not-allowed disabled:border-dashed disabled:border-slate-500 disabled:bg-slate-200 disabled:text-slate-700"
      >
        {es.cancel.label}
      </button>
      <p id={hintId} className="text-sm text-slate-700">
        {enabled ? es.cancel.enabledHint : es.cancel.disabledHint}
      </p>
    </div>
  );
}

import { es } from "../i18n/es";

/** The host's note that a person follows up. Its text is the host's, shown as text. */
export function HandoffNotice({ message }: { message: string }) {
  return (
    <div className="rounded-lg border-2 border-sky-800 bg-sky-50 p-3 text-sm text-sky-950">
      <p className="font-semibold">
        <span aria-hidden="true">☎ </span>
        {es.handoff.title}
      </p>
      <p>{message}</p>
    </div>
  );
}

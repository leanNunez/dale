import { es } from "../i18n/es";

interface Props {
  /** A refusal or warning from the host, or an error of the page's own request. */
  kind: "notice" | "error";
  message: string;
  /**
   * False inside a live region that already announces what is added to it (the chat log): a
   * second `status` or `alert` there would be read twice.
   */
  live?: boolean;
  children?: React.ReactNode;
}

/** A short message with a word and a mark, so its kind never rests on color. An error is announced. */
export function Notice({ kind, message, live = true, children }: Props) {
  const error = kind === "error";
  const role = live ? (error ? "alert" : "status") : undefined;
  return (
    <div
      role={role}
      className={
        error
          ? "rounded-lg border-2 border-red-800 bg-red-50 p-3 text-sm text-red-950"
          : "rounded-lg border-2 border-amber-800 bg-amber-50 p-3 text-sm text-amber-950"
      }
    >
      <p className="font-semibold">
        <span aria-hidden="true">{error ? "✖ " : "⚠ "}</span>
        {error ? es.notice.errorTitle : es.notice.title}
      </p>
      <p>{message}</p>
      {children}
    </div>
  );
}

import { es } from "../i18n/es";

interface Props {
  who: "customer" | "assistant";
  /** Model or customer text: rendered as a React text node only. */
  text: string;
}

/** One chat message. Who spoke is said in words and by side, never by color alone. */
export function ChatText({ who, text }: Props) {
  const mine = who === "customer";
  return (
    <div className={mine ? "flex flex-col items-end" : "flex flex-col items-start"}>
      <p className="text-xs font-semibold text-slate-700">
        {mine ? es.chat.customer : es.chat.assistant}
      </p>
      <p
        className={
          mine
            ? "max-w-prose whitespace-pre-wrap break-words rounded-lg bg-slate-800 px-3 py-2 text-white"
            : "max-w-prose whitespace-pre-wrap break-words rounded-lg border border-slate-300 bg-white px-3 py-2 text-slate-900"
        }
      >
        {text}
      </p>
    </div>
  );
}

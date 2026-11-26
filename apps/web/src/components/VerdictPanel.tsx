import type { ToolCalledEvent, VerdictIssuedEvent } from "../contract";
import { es } from "../i18n/es";
import type { ChatItem } from "../state/reducer";
import { Verdict } from "./Verdict";

/**
 * The seq of the first event a turn of the conversation produced (what the assistant said or
 * proposed, or a tool it used), or null while none has. A verdict before it judged a press
 * made before the conversation had any turn.
 */
function firstTurnSeq(chat: ChatItem[], trace: ToolCalledEvent[]): number | null {
  const seqs = trace.map((event) => event.seq);
  for (const item of chat) {
    if (
      item.kind === "event" &&
      (item.event.type === "AssistantText" || item.event.type === "ProposalSummary")
    ) {
      seqs.push(item.event.seq);
    }
  }
  return seqs.length === 0 ? null : Math.min(...seqs);
}

interface Props {
  verdicts: VerdictIssuedEvent[];
  /** With `trace`, what says whether the conversation had a turn before each verdict. */
  chat: ChatItem[];
  trace: ToolCalledEvent[];
}

/**
 * The verifier's result for every press, in the order the host sent them. Polite live region: a
 * verdict that arrives is read once, and nothing in it is a `status` of its own.
 */
export function VerdictPanel({ verdicts, chat, trace }: Props) {
  const turn = firstTurnSeq(chat, trace);
  return (
    <section
      aria-labelledby="verdict-title"
      className="rounded-lg border border-slate-300 bg-slate-50 p-4"
    >
      <h2 id="verdict-title" className="mb-2 text-lg font-semibold">
        {es.panels.verdict.title}
      </h2>
      <div aria-live="polite">
        {verdicts.length === 0 ? (
          <p className="text-sm text-slate-700">{es.panels.verdict.empty}</p>
        ) : (
          <ol className="flex flex-col gap-2">
            {verdicts.map((event) => (
              <Verdict
                key={event.seq}
                data={event.data}
                beforeAnyTurn={turn === null || event.seq < turn}
              />
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}

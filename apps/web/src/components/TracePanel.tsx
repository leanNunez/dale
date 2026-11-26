import type { ToolCalledEvent } from "../contract";
import { es } from "../i18n/es";
import { ToolTrace } from "./ToolTrace";

/** The tools the agent used, in the order the host sent them. */
export function TracePanel({ trace }: { trace: ToolCalledEvent[] }) {
  return (
    <section
      aria-labelledby="trace-title"
      className="rounded-lg border border-slate-300 bg-slate-50 p-4"
    >
      <h2 id="trace-title" className="mb-2 text-lg font-semibold">
        {es.panels.trace.title}
      </h2>
      {trace.length === 0 ? (
        <p className="text-sm text-slate-700">{es.panels.trace.empty}</p>
      ) : (
        <ol className="flex flex-col gap-2">
          {trace.map((event) => (
            <ToolTrace key={event.seq} data={event.data} />
          ))}
        </ol>
      )}
    </section>
  );
}

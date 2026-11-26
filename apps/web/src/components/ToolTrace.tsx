import type { ToolCalledEvent } from "../contract";
import { es } from "../i18n/es";
import { visible } from "../i18n/format";

const codes: Record<string, string> = es.panels.trace.codes;

/**
 * One tool call of a turn. Name, summary and code are model-controlled: React text nodes only,
 * with invisible characters made visible (they cannot reorder or break what is around them)
 * and each inside `<bdi>`, so text in a right-to-left script cannot reorder its neighbors either.
 * Each wraps anywhere, so one unbroken word never pushes the card past its column. The outcome
 * is a word and a mark, never color alone; a known error code reads as its Spanish label.
 */
export function ToolTrace({ data }: { data: ToolCalledEvent["data"] }) {
  return (
    <li className="rounded-lg border border-slate-300 bg-white p-3 text-sm">
      <p className="break-words font-semibold text-slate-900 [overflow-wrap:anywhere]">
        <bdi className="font-mono">{visible(data.name)}</bdi>
      </p>
      <p className="break-words text-slate-800 [overflow-wrap:anywhere]">
        <bdi className="font-mono">{visible(data.summary)}</bdi>
      </p>
      <p
        className={`break-words [overflow-wrap:anywhere] ${data.ok ? "text-emerald-900" : "font-semibold text-red-900"}`}
      >
        <span aria-hidden="true">{data.ok ? "✔ " : "✖ "}</span>
        {data.ok ? es.panels.trace.ok : es.panels.trace.error}
        {!data.ok && data.code !== null && (
          <>
            :{" "}
            {Object.hasOwn(codes, data.code) ? (
              codes[data.code]
            ) : (
              <bdi className="font-mono">{visible(data.code)}</bdi>
            )}
          </>
        )}
      </p>
    </li>
  );
}

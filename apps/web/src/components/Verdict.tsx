import type { VerdictIssuedEvent } from "../contract";
import { es } from "../i18n/es";
import { shortId } from "../i18n/format";

type Data = VerdictIssuedEvent["data"];
const labels: Record<string, string> = es.panels.verdict.label;
const reasons: Record<string, string> = es.panels.verdict.reasons;
const fields: Record<string, string> = es.panels.verdict.fields;

/** An own entry of a table of words: a verdict named `__proto__` or `toString` finds none. */
function lookup(table: Record<string, string>, key: string): string | undefined {
  return Object.hasOwn(table, key) ? table[key] : undefined;
}

/** A mark for each outcome; the label beside it says the same in words. */
function mark(verdict: string): string {
  switch (verdict) {
    case "verified":
      return "✔";
    case "mismatch":
    case "missing":
    case "unexpected_write":
      return "✖";
    case "nothing_confirmed":
      return "○";
    default:
      return "⚠";
  }
}

/**
 * The verifier's headline. Only a `verified` verdict reads as verified. `verifier_error` is every
 * failed verifier call on the host (and any reason outside the closed set, B37): "not yet" only
 * when the conversation had no turn before it (a press before any turn, B62), else the verifier
 * failed and the headline is the plain "could not verify". Neither says a word of an order fault.
 */
function headline(data: Data, beforeAnyTurn: boolean): string {
  if (data.verdict === "unverifiable" && data.reason === "verifier_error" && beforeAnyTurn) {
    return es.panels.verdict.yet;
  }
  return lookup(labels, data.verdict) ?? es.panels.verdict.label.unknown;
}

function Unverifiable({ reason }: { reason: string }) {
  return (
    <p className="text-slate-800">
      {lookup(reasons, reason) ?? es.panels.verdict.unknownReason} {es.panels.verdict.unverifiableNote}
    </p>
  );
}

interface Props {
  data: Data;
  /** True when no turn of the conversation came before this verdict. */
  beforeAnyTurn: boolean;
}

/** One verdict: a word and a mark for the outcome, the proposal it judged, and what differed. */
export function Verdict({ data, beforeAnyTurn }: Props) {
  const differing = data.findings.filter((finding) => finding.fields.length > 0);
  return (
    <li className="rounded-lg border-2 border-slate-700 bg-white p-3 text-sm">
      <p className="font-semibold text-slate-900">
        <span aria-hidden="true">{mark(data.verdict)} </span>
        {headline(data, beforeAnyTurn)}
      </p>
      {data.verdict === "unverifiable" && <Unverifiable reason={data.reason} />}
      {differing.map((finding, index) => (
        <p key={index} className="text-slate-800">
          {es.panels.verdict.differs}: {finding.fields.map((field) => lookup(fields, field) ?? field).join(", ")}
        </p>
      ))}
      <p className="text-slate-700">
        {es.panels.verdict.proposal}:{" "}
        {data.subject_proposal_id === null
          ? es.panels.verdict.noProposal
          : shortId(data.subject_proposal_id)}
      </p>
    </li>
  );
}

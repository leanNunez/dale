// The contract's own sample envelopes (contracts/v1/samples): the tests that read them check the
// page against what the host's types actually produce, not against hand-written look-alikes.
import type { ResponseEnvelope, WebEvent } from "../contract";

const files = import.meta.glob<unknown>("../../../../contracts/v1/samples/*.json", {
  eager: true,
  import: "default",
});

function sample(name: string): unknown {
  const found = Object.entries(files).find(([path]) => path.endsWith(`/${name}.json`));
  if (found === undefined) throw new Error(`no sample named ${name}`);
  return found[1];
}

/** The sample event of a type, such as `ToolCalled` or `VerdictIssued`. */
export function sampleEvent<T extends WebEvent["type"]>(
  type: T,
): Extract<WebEvent, { type: T }> {
  const found = Object.entries(files).find(
    ([path, value]) =>
      path.includes("/event_") && (value as { type?: unknown } | null)?.type === type,
  );
  if (found === undefined) throw new Error(`no sample event of type ${type}`);
  return found[1] as Extract<WebEvent, { type: T }>;
}

export const sampleEnvelope = () => sample("response_envelope") as ResponseEnvelope;

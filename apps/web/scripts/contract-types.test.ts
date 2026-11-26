// @vitest-environment node
// The generated TypeScript types compiled over the contract's own sample JSON (S5.3, S4.3): each
// sample, written as the literal of its type, must typecheck, and a broken one must not.
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import ts from "typescript";
import { describe, expect, it } from "vitest";

const web = fileURLToPath(new URL("..", import.meta.url));
const samples = fileURLToPath(new URL("../../../contracts/v1/samples/", import.meta.url));
const virtualFile = join(web, "src", "__samples.ts");

/** The page's name for the type a sample file is an instance of. */
function typeOf(file: string, json: { type?: string }): string {
  const commands: Record<string, string> = {
    "command_cancel_proposal.json": "CancelProposal",
    "command_press_dale.json": "PressDale",
    "command_send_message.json": "SendMessage",
    "response_envelope.json": "ResponseEnvelope",
  };
  const found = commands[file] ?? (file.startsWith("event_") ? `${json.type}Event` : undefined);
  if (found === undefined) throw new Error(`${file} has no type to check it against`);
  return found;
}

/** The compiler's complaints about `source` as a module placed inside the page's `src`. */
function diagnose(source: string): string[] {
  const options: ts.CompilerOptions = {
    target: ts.ScriptTarget.ES2023,
    lib: ["lib.es2023.d.ts"],
    module: ts.ModuleKind.ESNext,
    moduleResolution: ts.ModuleResolutionKind.Bundler,
    strict: true,
    noUncheckedIndexedAccess: true,
    verbatimModuleSyntax: true,
    isolatedModules: true,
    skipLibCheck: true,
    types: [],
    noEmit: true,
  };
  const host = ts.createCompilerHost(options);
  const original = host.getSourceFile.bind(host);
  host.getSourceFile = (name, languageVersion, ...rest) =>
    name === virtualFile
      ? ts.createSourceFile(name, source, languageVersion)
      : original(name, languageVersion, ...rest);
  const fileExists = host.fileExists.bind(host);
  host.fileExists = (name) => name === virtualFile || fileExists(name);
  const program = ts.createProgram([virtualFile], options, host);
  return ts
    .getPreEmitDiagnostics(program)
    .map((d) => ts.flattenDiagnosticMessageText(d.messageText, "\n"));
}

/** `const sample0: Type = {json};` for every sample, with the page's own type names imported. */
function moduleOf(entries: { file: string; json: { type?: string } }[]): string {
  const names = [...new Set(entries.map(({ file, json }) => typeOf(file, json)))].sort();
  const body = entries
    .map(({ file, json }, i) => `export const s${i}: ${typeOf(file, json)} = ${JSON.stringify(json)};`)
    .join("\n");
  return `import type { ${names.join(", ")} } from "./contract";\n${body}\n`;
}

const files = readdirSync(samples).filter((name) => name.endsWith(".json")).sort();
const entries = files.map((file) => ({
  file,
  json: JSON.parse(readFileSync(join(samples, file), "utf8")) as { type?: string },
}));

describe("the generated types over the contract samples", () => {
  it("covers every sample file: a command, an envelope or an event of a type the page names", () => {
    expect(files.length).toBeGreaterThanOrEqual(12);
    expect(() => moduleOf(entries)).not.toThrow();
  });

  it("compiles every sample as the literal of its type, with no complaint", { timeout: 60_000 }, () => {
    expect(diagnose(moduleOf(entries))).toEqual([]);
  });

  it("rejects a sample that is wrong, so the check above can fail", { timeout: 60_000 }, () => {
    const only = (file: string) => entries.filter((entry) => entry.file === file);
    const wrong = (file: string, change: (json: Record<string, unknown>) => void) => {
      const copy = JSON.parse(JSON.stringify(only(file))) as typeof entries;
      change(copy[0]?.json as Record<string, unknown>);
      return diagnose(moduleOf(copy));
    };
    const data = (json: Record<string, unknown>) => json["data"] as Record<string, unknown>;
    expect(wrong("event_tool_called.json", (j) => (data(j)["ok"] = "yes"))).not.toEqual([]);
    expect(wrong("event_tool_called.json", (j) => delete data(j)["summary"])).not.toEqual([]);
    expect(wrong("event_verdict_issued.json", (j) => (data(j)["verdict"] = "all_good"))).not.toEqual([]);
    expect(wrong("event_proposal_summary.json", (j) => (data(j)["total"] = 3700))).not.toEqual([]);
    expect(wrong("response_envelope.json", (j) => (j["v"] = 2))).not.toEqual([]);
  });
});

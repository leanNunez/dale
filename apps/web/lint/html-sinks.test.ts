// @vitest-environment node
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { ESLint } from "eslint";
import { describe, expect, it } from "vitest";

const root = fileURLToPath(new URL("..", import.meta.url));
const fixture = "lint/fixtures/raw-html-sink.tsx";
const eslint = new ESLint({ cwd: root, ignore: false });

/** Each banned sink in the fixture and the rule that must report its marked line. */
const SINKS: Record<string, string> = {
  innerHTML: "no-restricted-syntax",
  outerHTML: "no-restricted-syntax",
  "computed string key": "no-restricted-syntax",
  "computed template key": "no-restricted-syntax",
  insertAdjacentHTML: "no-restricted-syntax",
  "srcdoc property": "no-restricted-syntax",
  "setAttribute srcdoc": "no-restricted-syntax",
  "setAttribute innerHTML": "no-restricted-syntax",
  "setAttributeNS any case": "no-restricted-syntax",
  "Reflect.set": "no-restricted-syntax",
  "Object.defineProperty": "no-restricted-syntax",
  setHTMLUnsafe: "no-restricted-syntax",
  parseHTMLUnsafe: "no-restricted-syntax",
  DOMParser: "no-restricted-syntax",
  createContextualFragment: "no-restricted-syntax",
  "document.write": "no-restricted-syntax",
  "document.writeln": "no-restricted-syntax",
  "window.document": "no-restricted-syntax",
  "computed document key": "no-restricted-syntax",
  "aliased document": "no-restricted-syntax",
  eval: "no-eval",
  "window.eval": "no-eval",
  "new Function": "no-new-func",
  "string setTimeout": "no-implied-eval",
  "object prop": "no-restricted-syntax",
  "JSX srcDoc on an iframe": "no-restricted-syntax",
  "JSX srcDoc on any element": "no-restricted-syntax",
  "JSX prop": "react/no-danger",
};

async function messages(path: string): Promise<{ rule: string | null; line: number }[]> {
  const [result] = await eslint.lintFiles([path]);
  return (result?.messages ?? []).map((m) => ({ rule: m.ruleId, line: m.line }));
}

let linted: ReturnType<typeof messages> | undefined;
const fixtureMessages = () => (linted ??= messages(fixture));

function markedLines(): [label: string, line: number][] {
  const source = readFileSync(`${root}/${fixture}`, "utf8").split("\n");
  return source.flatMap((text, index): [string, number][] => {
    const label = /\/\/ sink: (.+)$/.exec(text)?.[1];
    return label === undefined ? [] : [[label, index + 1]];
  });
}
const lineOf = (label: string) => markedLines().find(([name]) => name === label)?.[1];

describe("raw HTML sinks fail lint (S10.3)", () => {
  it("marks each banned sink once in the fixture", () => {
    expect(markedLines().map(([label]) => label).sort()).toEqual(Object.keys(SINKS).sort());
  });

  it.each(Object.entries(SINKS))("reports the %s sink with %s", async (label, rule) => {
    const line = lineOf(label);
    const found = await fixtureMessages();
    expect(found).toContainEqual({ rule, line });
  });

  it("reports the JSX prop with both rules", async () => {
    const line = lineOf("JSX prop");
    const found = await fixtureMessages();
    expect(found).toContainEqual({ rule: "no-restricted-syntax", line });
  });

  it("applies to the page's own source, not only to the fixture", async () => {
    const [result] = await eslint.lintText(
      "export const f = (e: Element, t: string) => {\n  e.outerHTML = t;\n};\n",
      { filePath: `${root}/src/unsafe.ts` },
    );
    expect(result?.messages.map((m) => m.ruleId)).toEqual(["no-restricted-syntax"]);
  });

  it("passes a component that renders model text as a text node", async () => {
    const [result] = await eslint.lintText(
      [
        'const root = document.getElementById("root");',
        "export function Safe({ text, out }: { text: string; out: WritableStreamDefaultWriter }) {",
        "  void out.write(text);",
        "  return <p title={document.title}>{text}{String(root)}</p>;",
        "}",
        "",
      ].join("\n"),
      { filePath: `${root}/lint/fixtures/safe.tsx` },
    );
    expect(result?.messages).toEqual([]);
  });
});

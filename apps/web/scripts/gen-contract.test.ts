// @vitest-environment node
import { execFileSync } from "node:child_process";
import { mkdtempSync, readdirSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { afterEach, expect, it } from "vitest";

const script = fileURLToPath(new URL("./gen-contract.mjs", import.meta.url));
const committed = fileURLToPath(new URL("../src/contract/generated", import.meta.url));
let scratch = "";

afterEach(() => {
  rmSync(scratch, { recursive: true, force: true });
});

function snapshot(dir: string): Record<string, string> {
  return Object.fromEntries(
    readdirSync(dir)
      .sort()
      .map((name) => [name, readFileSync(join(dir, name), "utf8")]),
  );
}

it("regenerating from contracts/v1 reproduces the committed types exactly (S5.3)", () => {
  scratch = mkdtempSync(join(tmpdir(), "gen-contract-"));
  execFileSync(process.execPath, [script], {
    env: { ...process.env, GEN_CONTRACT_OUT: scratch },
    stdio: "pipe",
  });
  expect(snapshot(scratch)).toEqual(snapshot(committed));
});

it("emits one module per wire type and the components map", () => {
  expect(readdirSync(committed).sort()).toEqual([
    "CancelProposal.ts",
    "PressDale.ts",
    "ResponseEnvelope.ts",
    "SendMessage.ts",
    "WebEvent.ts",
    "components.ts",
  ]);
});

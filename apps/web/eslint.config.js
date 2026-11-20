import js from "@eslint/js";
import { defineConfig, globalIgnores } from "eslint/config";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

import { htmlSinkRules } from "./lint/html-sinks.js";

export default defineConfig(
  // The fixture is a deliberate violation, linted only by lint/html-sinks.test.ts.
  globalIgnores(["dist", "node_modules", "src/contract/generated", "lint/fixtures"]),
  js.configs.recommended,
  tseslint.configs.strict,
  {
    files: ["**/*.{ts,tsx}"],
    ...react.configs.flat.recommended,
    languageOptions: { globals: globals.browser },
    settings: { react: { version: "19.3" } },
  },
  react.configs.flat["jsx-runtime"],
  reactHooks.configs.flat.recommended,
  {
    files: ["**/*.{ts,tsx,js}"],
    // The rule and its test name the sinks they ban; the fixture still gets the rules.
    ignores: ["lint/*.{js,ts}"],
    rules: { ...htmlSinkRules },
  },
  {
    files: ["*.config.{js,ts}", "vite.proxy*.ts", "lint/**/*.{js,ts}", "scripts/**/*.mjs"],
    languageOptions: { globals: globals.node },
  },
);

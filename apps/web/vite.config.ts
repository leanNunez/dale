import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

import { DEV_HOSTS, apiProxy } from "./vite.proxy.ts";

const hostPort = process.env["DALE_WEB_PORT"] ?? "8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { allowedHosts: DEV_HOSTS, proxy: apiProxy(`http://127.0.0.1:${hostPort}`) },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}", "*.test.ts", "lint/*.test.ts", "scripts/*.test.ts"],
  },
});

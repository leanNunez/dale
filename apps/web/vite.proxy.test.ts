// @vitest-environment node
import { request } from "node:http";
import type { AddressInfo } from "node:net";
import { fileURLToPath } from "node:url";

import { createServer } from "vite";
import { expect, it } from "vitest";

import { API_PATHS, DEV_HOSTS, apiProxy, rewriteOrigin } from "./vite.proxy.ts";

class FakeRequest {
  headers = new Map<string, string>();
  getHeader(name: string): unknown {
    return this.headers.get(name);
  }
  setHeader(name: string, value: string): void {
    this.headers.set(name, value);
  }
}

it("proxies the API paths and the health path to the host's own names", () => {
  const proxy = apiProxy("http://127.0.0.1:8000");
  expect(Object.keys(proxy)).toEqual([...API_PATHS]);
  for (const options of Object.values(proxy)) {
    expect(options.target).toBe("http://127.0.0.1:8000");
    expect(options.changeOrigin).toBe(true); // the Host header becomes the target's
  }
});

const TARGET = "http://127.0.0.1:8000";

function proxied(origin: string | undefined, host = "localhost:5173") {
  const request = new FakeRequest();
  if (origin !== undefined) request.setHeader("origin", origin);
  rewriteOrigin(request, { headers: { host } }, TARGET);
  return request.getHeader("origin");
}

it("presents the host's own origin for a page the dev server served itself", () => {
  expect(proxied("http://localhost:5173")).toBe(TARGET);
});

it("leaves a request from another site with its own origin, so the host rejects it", () => {
  expect(proxied("http://evil.example")).toBe("http://evil.example");
  expect(proxied("http://localhost:6000")).toBe("http://localhost:6000");
  expect(proxied("null")).toBe("null");
});

it("adds no origin to a request that had none", () => {
  expect(proxied(undefined)).toBeUndefined();
});

it("sets no timeout of any kind, because no request may be cut short (D17)", () => {
  for (const options of Object.values(apiProxy("http://127.0.0.1:8000"))) {
    expect(Object.keys(options).filter((key) => /timeout/i.test(key))).toEqual([]);
  }
});

function statusFor(bound: AddressInfo, host: string): Promise<number | undefined> {
  return new Promise((resolve, reject) => {
    // Connect where the server is bound: "localhost" is ::1 on some machines, 127.0.0.1 on others.
    const { address, port } = bound;
    const sent = request({ host: address, port, path: "/", headers: { host } }, (reply) => {
      reply.resume();
      resolve(reply.statusCode);
    });
    sent.on("error", reject);
    sent.end();
  });
}

it("answers only to loopback names, so a rebinding Host is refused", async () => {
  const server = await createServer({
    configFile: fileURLToPath(new URL("./vite.config.ts", import.meta.url)),
    logLevel: "silent",
    server: { port: 0, strictPort: true, hmr: false },
  });
  try {
    expect(server.config.server.allowedHosts).toEqual(DEV_HOSTS);
    await server.listen();
    const bound = server.httpServer?.address() as AddressInfo;
    const { port } = bound;
    expect(await statusFor(bound, `localhost:${port}`)).toBe(200);
    expect(await statusFor(bound, `127.0.0.1:${port}`)).toBe(200);
    expect(await statusFor(bound, `rebind.example:${port}`)).toBe(403);
    expect(await statusFor(bound, `localhost.rebind.example:${port}`)).toBe(403);
  } finally {
    await server.close();
  }
});

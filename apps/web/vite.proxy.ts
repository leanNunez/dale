import type { ProxyOptions } from "vite";

/**
 * The dev server proxies the API to the Python host (same-origin in production, so the build
 * needs none). The host's guard checks `Host` and `Origin` against its loopback allow-list, so
 * the proxy presents the target's own names instead of the dev server's. It does so for a page
 * served by the dev server itself (its `Origin` names the `Host` the dev server was called
 * with) and for nothing else: a request from another site keeps its own `Origin`, and the host
 * rejects it as it would in production. No timeout option is set anywhere: a sync turn cannot
 * be cancelled, and the server bounds it at its deadline, plus one round of tool statements,
 * plus the 30 s verifier (design D17, decision B6, ADR 0011).
 */
export const API_PATHS = ["/v1", "/health"] as const;

/**
 * The only names the dev server answers to. Vite also accepts an IP address, never another
 * name, so a rebinding `Host` (a DNS name pointed at 127.0.0.1) is refused with 403. Setting the
 * list keeps a future default or `--host` flag from widening it; `true` is never allowed.
 */
export const DEV_HOSTS: string[] = ["localhost", "127.0.0.1"];

interface HeaderSink {
  getHeader(name: string): unknown;
  setHeader(name: string, value: string): void;
}
interface Incoming {
  headers: Record<string, string | string[] | undefined>;
}
interface ProxyEvents {
  on(event: "proxyReq", listener: (request: HeaderSink, incoming: Incoming) => void): void;
}

function hostOf(origin: unknown): string | null {
  try {
    return typeof origin === "string" ? new URL(origin).host : null;
  } catch {
    return null; // "null" and anything that is not a URL: left alone, so the host rejects it
  }
}

export function rewriteOrigin(request: HeaderSink, incoming: Incoming, target: string): void {
  const host = hostOf(request.getHeader("origin"));
  if (host !== null && host === incoming.headers["host"]) {
    request.setHeader("origin", new URL(target).origin);
  }
}

export function apiProxy(target: string): Record<string, ProxyOptions> {
  const options: ProxyOptions = {
    target,
    changeOrigin: true,
    configure: (proxy: ProxyEvents) => {
      proxy.on("proxyReq", (request, incoming) => {
        rewriteOrigin(request, incoming, target);
      });
    },
  };
  return Object.fromEntries(API_PATHS.map((path) => [path, options]));
}

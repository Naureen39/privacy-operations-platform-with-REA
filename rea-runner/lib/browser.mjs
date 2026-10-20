/**
 * Website observation: serve a saved page (or open an allowlisted URL) in a headless
 * Chrome-family browser, then let REA observe it through the Chrome DevTools Protocol.
 *
 * REA keeps observation inside an origin boundary and does not retain DOM attribute values,
 * so third-party origins are passed explicitly (they come from the static analysis of the
 * page) and the page is reloaded during the observation window so that REA sees the requests.
 */
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { createServer } from "node:http";
import { createServer as createNetServer } from "node:net";
import { tmpdir } from "node:os";
import { basename, extname, join } from "node:path";
import { RunnerError } from "./errors.mjs";
import { runRea } from "./rea.mjs";
import { validateObservationUrl } from "./urlguard.mjs";

const BROWSER_CANDIDATES = [
  process.env.CHROME_PATH,
  "/usr/bin/chromium",
  "/usr/bin/chromium-browser",
  "/usr/bin/google-chrome",
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
].filter(Boolean);

const MIME = { ".html": "text/html; charset=utf-8", ".htm": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css" };

/**
 * Chrome host resolver rules for an observation. Only loopback (the DevTools endpoint and the
 * served snapshot) or one pinned, already validated address can be reached by name.
 */
export function hostResolverRules(host, address) {
  return host ? `MAP ${host} ${address}, MAP * ~NOTFOUND` : "MAP * ~NOTFOUND, EXCLUDE 127.0.0.1";
}

export function findBrowser() {
  const found = BROWSER_CANDIDATES.find((p) => existsSync(p));
  if (!found) throw new RunnerError("browser_unavailable", "no Chrome-family browser was found (set CHROME_PATH)");
  return found;
}

function freePort() {
  return new Promise((resolve, reject) => {
    const server = createNetServer();
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
    server.on("error", reject);
  });
}

/** Serve exactly one saved page on a random loopback port. Nothing else is reachable. */
function serveSnapshot(file) {
  const body = readFileSync(file);
  const route = `/${basename(file)}`;
  const server = createServer((req, res) => {
    if (req.url?.split("?")[0] === route || req.url === "/") {
      res.writeHead(200, { "content-type": MIME[extname(file).toLowerCase()] ?? "text/html; charset=utf-8", "cache-control": "no-store" });
      res.end(body);
    } else {
      res.writeHead(404).end();
    }
  });
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve({ server, port: server.address().port, route })));
}

async function waitForJson(url, attempts = 80, delayMs = 125) {
  for (let i = 0; i < attempts; i += 1) {
    try {
      const response = await fetch(url);
      if (response.ok) return await response.json();
    } catch {
      /* browser still starting */
    }
    await new Promise((r) => setTimeout(r, delayMs));
  }
  throw new RunnerError("browser_unavailable", "the browser did not open its debugging endpoint");
}

function cdpSend(wsUrl, method, params = {}) {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(wsUrl);
    const timer = setTimeout(() => {
      socket.close();
      reject(new RunnerError("cdp_timeout", `${method} timed out`));
    }, 10_000);
    socket.onopen = () => socket.send(JSON.stringify({ id: 1, method, params }));
    socket.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.id === 1) {
        clearTimeout(timer);
        socket.close();
        message.error ? reject(new RunnerError("cdp_error", message.error.message)) : resolve(message.result);
      }
    };
    socket.onerror = () => {
      clearTimeout(timer);
      reject(new RunnerError("cdp_error", `${method} failed`));
    };
  });
}

/**
 * @param {{file?: string, url?: string, allowedOrigins?: string[], observationMs?: number,
 *          hardTimeoutMs?: number, urlPolicy?: object}} request
 */
export async function observeWebsite({ file, url, allowedOrigins = [], observationMs = 2500, hardTimeoutMs = 60_000, urlPolicy = {} }) {
  const browserPath = findBrowser();
  let snapshot = null;
  let targetUrl = url;
  // The browser never resolves names on its own: everything except the page itself is "not found".
  let resolverRule = hostResolverRules();
  if (file) {
    snapshot = await serveSnapshot(file);
    targetUrl = `http://127.0.0.1:${snapshot.port}${snapshot.route}`;
  } else {
    const checked = await validateObservationUrl(url, urlPolicy);
    // Pin the browser to the address that was just validated (no second lookup).
    resolverRule = hostResolverRules(checked.host, checked.addresses[0]);
  }

  const profile = mkdtempSync(join(tmpdir(), "rea-browser-"));
  const debugPort = await freePort();
  const args = [
    "--headless=new", `--remote-debugging-port=${debugPort}`, "--remote-debugging-address=127.0.0.1",
    `--user-data-dir=${profile}`, "--no-first-run", "--no-default-browser-check", "--disable-extensions",
    "--disable-background-networking", "--disable-sync", "--disable-gpu", "--disable-dev-shm-usage",
    "--mute-audio", "--disable-component-update", "--disable-default-apps",
  ];
  // Chrome's sandbox needs kernel features that a locked down container does not grant. The
  // container itself is the isolation boundary: non root, no capabilities, read only, no egress.
  if (process.env.REA_BROWSER_NO_SANDBOX === "1") args.push("--no-sandbox");
  args.push(`--host-resolver-rules=${resolverRule}`);
  args.push("about:blank");

  const browser = spawn(browserPath, args, { stdio: "ignore", shell: false });
  const hardTimer = setTimeout(() => browser.kill("SIGKILL"), hardTimeoutMs);
  const endpoint = `http://127.0.0.1:${debugPort}`;
  try {
    await waitForJson(`${endpoint}/json/version`);
    const targets = await waitForJson(`${endpoint}/json/list`);
    const page = targets.find((t) => t.type === "page");
    if (!page) throw new RunnerError("browser_unavailable", "the browser opened no page");
    await cdpSend(page.webSocketDebuggerUrl, "Page.navigate", { url: targetUrl });

    // Wait until the page has loaded so that REA can list it as an HTTP(S) target.
    let loaded = false;
    for (let i = 0; i < 80 && !loaded; i += 1) {
      const list = await waitForJson(`${endpoint}/json/list`, 2, 50);
      loaded = list.some((t) => t.id === page.id && t.url.startsWith("http"));
      if (!loaded) await new Promise((r) => setTimeout(r, 125));
    }
    if (!loaded) throw new RunnerError("navigation_failed", "the page did not load");

    const pageOrigin = new URL(targetUrl).origin;
    const origins = [...new Set([pageOrigin, ...allowedOrigins])];
    const reaArgs = [
      "inspect-web-page", endpoint, page.id, "--observation-ms", String(observationMs),
      "--include-accessibility-text", "--include-storage-keys", "--json",
    ];
    for (const origin of origins) reaArgs.push("--allowed-origins", origin);

    const observation = runRea(reaArgs, { timeoutMs: hardTimeoutMs });
    // Reload while REA is attached so that the page's requests fall inside the observation window.
    await new Promise((r) => setTimeout(r, Math.min(600, observationMs / 3)));
    const fresh = await waitForJson(`${endpoint}/json/list`, 4, 50);
    const live = fresh.find((t) => t.id === page.id) ?? page;
    await cdpSend(live.webSocketDebuggerUrl, "Page.reload", {}).catch(() => {});
    const result = await observation;
    return { page_origin: pageOrigin, allowed_origins: origins, evidence: result };
  } finally {
    clearTimeout(hardTimer);
    browser.kill("SIGKILL");
    snapshot?.server.close();
    try {
      rmSync(profile, { recursive: true, force: true });
    } catch {
      /* profile may still be locked briefly on some systems */
    }
  }
}

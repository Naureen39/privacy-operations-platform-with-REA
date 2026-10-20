import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { findBrowser } from "../lib/browser.mjs";
import { execute } from "../lib/commands.mjs";

let browserAvailable = true;
try {
  findBrowser();
} catch {
  browserAvailable = false;
}

const input = mkdtempSync(join(tmpdir(), "runner-browser-"));
mkdirSync(join(input, "r1"));
writeFileSync(
  join(input, "r1", "page.html"),
  `<!doctype html><html><head><title>Observation test</title></head><body>
  <form action="/send" method="post"><label for="e">Email address</label><input id="e" name="email" type="email" required></form>
  <script src="https://tracker.invalid.example/t.js"></script>
  <img src="https://pixel.invalid.example/p.gif"></body></html>`,
);
const ctx = { inputRoot: input, reaTimeoutMs: 60_000, browserTimeoutMs: 45_000, allowOffline: true, allowBrowser: true, urlPolicy: {} };

test("observes a saved page: hosts as referenced, labels as the browser exposes them", { skip: !browserAvailable && "no Chrome-family browser" }, async () => {
  const out = await execute(ctx, {
    command: "observe-website",
    path: "r1/page.html",
    options: { allowed_origins: ["https://tracker.invalid.example", "https://pixel.invalid.example"], observation_ms: 1500 },
  });
  const evidence = out.result.evidence.normalized_result;
  assert.match(out.result.page_origin, /^http:\/\/127\.0\.0\.1:\d+$/);
  const urls = [...evidence.resources.map((r) => r.url), ...evidence.metadata.dom_urls.map((d) => d.url)].filter(Boolean);
  assert.ok(urls.some((u) => u.startsWith("https://tracker.invalid.example/")));
  assert.ok(urls.some((u) => u.startsWith("https://pixel.invalid.example/")));
  const textbox = evidence.accessibility.nodes.find((n) => n.role === "textbox");
  assert.equal(textbox?.name, "Email address");
  // Name resolution is switched off, so the page's third-party requests could not leave the machine.
  assert.equal(evidence.network.requests.filter((r) => r.status === 200 && !r.url.startsWith("http://127.0.0.1")).length, 0);
});

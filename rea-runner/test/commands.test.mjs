import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { DatabaseSync } from "node:sqlite";
import { hostResolverRules } from "../lib/browser.mjs";
import { COMMANDS, execute } from "../lib/commands.mjs";

const input = mkdtempSync(join(tmpdir(), "runner-input-"));
mkdirSync(join(input, "r1"));
const ctx = {
  inputRoot: input,
  reaTimeoutMs: 60_000,
  browserTimeoutMs: 30_000,
  allowOffline: true,
  allowBrowser: true,
  urlPolicy: {},
};

const entry = {
  startedDateTime: "2026-01-01T00:00:00.000Z",
  time: 5,
  request: {
    method: "GET",
    url: "https://own.test/page?x=1",
    httpVersion: "HTTP/2.0",
    headers: [],
    queryString: [{ name: "x", value: "1" }],
    cookies: [],
    headersSize: -1,
    bodySize: 0,
  },
  response: {
    status: 200,
    statusText: "OK",
    httpVersion: "HTTP/2.0",
    headers: [],
    cookies: [],
    content: { size: 2, mimeType: "text/html", text: "ok" },
    redirectURL: "",
    headersSize: -1,
    bodySize: 2,
  },
  cache: {},
  timings: { send: 1, wait: 1, receive: 1 },
};
writeFileSync(join(input, "r1", "capture.har"), JSON.stringify({ log: { version: "1.2", creator: { name: "test", version: "1" }, entries: [entry] } }));
const db = new DatabaseSync(join(input, "r1", "d.sqlite"));
db.exec("CREATE TABLE people (id INTEGER PRIMARY KEY, email TEXT); INSERT INTO people (email) VALUES ('a@b.example'), ('c@d.example');");
db.close();
writeFileSync(join(input, "r1", "app.js"), 'const axios = require("axios"); fetch("https://api.test/v1/x");');
writeFileSync(join(input, "r1", "page.html"), "<html><body><form><input name=email></form></body></html>");
writeFileSync(join(input, "r1", "notes.txt"), "text");

const fails = (request, code, overrides = {}) => assert.rejects(() => execute({ ...ctx, ...overrides }, request), { code });

test("lists exactly the supported commands", () => {
  assert.deepEqual(Object.keys(COMMANDS).sort(), [
    "analyze-javascript-application",
    "inspect-sqlite-database",
    "inspect-web-network-capture",
    "observe-website",
  ]);
});

test("rejects unknown commands and malformed requests", async () => {
  await fails({ command: "native-analysis", path: "r1/app.js" }, "unknown_command");
  await fails({ command: "constructor", path: "r1/app.js" }, "unknown_command");
  await fails(null, "invalid_request");
  await fails({ command: "inspect-web-network-capture", path: "r1/capture.har", options: [] }, "invalid_option");
  await fails({ command: "inspect-web-network-capture", path: "r1/capture.har", url: "https://x.test" }, "invalid_request");
  await fails({ command: "observe-website" }, "invalid_request");
  await fails({ command: "observe-website", path: "r1/page.html", url: "https://own.test" }, "invalid_request");
});

test("validates paths, extensions and options", async () => {
  await fails({ command: "inspect-web-network-capture", path: "../outside.har" }, "not_found");
  await fails({ command: "inspect-web-network-capture", path: "r1/notes.txt" }, "invalid_path");
  await fails({ command: "inspect-sqlite-database", path: "r1/capture.har" }, "invalid_path");
  await fails({ command: "inspect-sqlite-database", path: "r1/d.sqlite", options: { row_limit: 0 } }, "invalid_option");
  await fails({ command: "inspect-sqlite-database", path: "r1/d.sqlite", options: { row_limit: 5, shell: "rm -rf /" } }, "invalid_option");
  await fails({ command: "observe-website", path: "r1/page.html", options: { allowed_origins: ["javascript:alert(1)"] } }, "invalid_option");
  await fails({ command: "observe-website", path: "r1/page.html", options: { observation_ms: 5 } }, "invalid_option");
});

test("a runner only provides the commands of its role", async () => {
  await fails({ command: "observe-website", path: "r1/page.html" }, "unsupported_here", { allowBrowser: false });
  await fails({ command: "inspect-web-network-capture", path: "r1/capture.har" }, "unsupported_here", { allowOffline: false });
});

test("observation URLs are checked before a browser is started", async () => {
  await fails({ command: "observe-website", url: "http://169.254.169.254/latest" }, "url_rejected", {
    urlPolicy: { allowedHosts: ["169.254.169.254"] },
  });
  await fails({ command: "observe-website", url: "https://evil.test/" }, "url_rejected", { urlPolicy: { allowedHosts: ["shop.test"] } });
});

test("the browser may resolve only loopback or the one pinned address", () => {
  assert.equal(hostResolverRules(), "MAP * ~NOTFOUND, EXCLUDE 127.0.0.1");
  assert.equal(hostResolverRules("shop.test", "93.184.216.34"), "MAP shop.test 93.184.216.34, MAP * ~NOTFOUND");
});

test("runs REA on a network capture", async () => {
  const out = await execute(ctx, { command: "inspect-web-network-capture", path: "r1/capture.har" });
  assert.equal(out.ok, true);
  assert.equal(out.rea_version, "6.7.0");
  assert.equal(out.result.normalized_result.total_records, 1);
  assert.ok(out.duration_ms >= 0);
});

test("runs REA on a SQLite snapshot and samples each table", async () => {
  const out = await execute(ctx, { command: "inspect-sqlite-database", path: "r1/d.sqlite", options: { row_limit: 1 } });
  assert.equal(out.result.tables_sampled, 1);
  const rows = out.result.samples.people.rows;
  assert.deepEqual(rows.columns, ["id", "email"]);
  assert.equal(rows.values.length, 1);
});

test("runs REA on a single script", async () => {
  const out = await execute(ctx, { command: "analyze-javascript-application", path: "r1/app.js" });
  const specifiers = out.result.normalized_result.graph.nodes
    .flatMap((n) => n.observations.map((o) => o.properties?.declared_specifier))
    .filter(Boolean);
  assert.ok(specifiers.includes("axios"));
});

test("reports a REA failure as a structured error", async () => {
  writeFileSync(join(input, "r1", "broken.har"), "{ not json");
  await fails({ command: "inspect-web-network-capture", path: "r1/broken.har" }, "rea_error");
});

import assert from "node:assert/strict";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, before, test } from "node:test";
import { createRunnerServer } from "../lib/server.mjs";

const ctx = {
  inputRoot: mkdtempSync(join(tmpdir(), "runner-srv-")),
  reaTimeoutMs: 30_000,
  browserTimeoutMs: 30_000,
  allowOffline: true,
  allowBrowser: false,
  urlPolicy: {},
};
let server;
let base;

before(async () => {
  server = createRunnerServer(ctx, { token: "secret-token" });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  base = `http://127.0.0.1:${server.address().port}`;
});
after(() => server.close());

const call = (path, { method = "GET", token = "secret-token", body } = {}) =>
  fetch(base + path, { method, headers: { "x-runner-token": token, "content-type": "application/json" }, body });

test("requires the runner token", async () => {
  assert.equal((await call("/v1/health", { token: "wrong" })).status, 401);
  assert.equal((await fetch(`${base}/v1/health`)).status, 401);
});

test("health reports the pinned version and only this role's commands", async () => {
  const response = await call("/v1/health");
  const body = await response.json();
  assert.equal(response.status, 200);
  assert.equal(body.rea_version, "6.7.0");
  assert.ok(!body.commands.includes("observe-website") && body.commands.includes("inspect-sqlite-database"));
});

test("rejects bad bodies, unknown routes and oversized requests", async () => {
  assert.equal((await call("/v1/run", { method: "POST", body: "not json" })).status, 422);
  assert.equal((await call("/v1/run", { method: "POST", body: JSON.stringify({ command: "bogus" }) })).status, 422);
  assert.equal((await call("/v1/nothing")).status, 404);
  const huge = JSON.stringify({ command: "inspect-sqlite-database", path: "x".repeat(70_000) });
  const response = await call("/v1/run", { method: "POST", body: huge }).catch(() => null);
  assert.ok(response === null || response.status === 413);
});

test("path traversal is refused over HTTP", async () => {
  const response = await call("/v1/run", {
    method: "POST",
    body: JSON.stringify({ command: "inspect-sqlite-database", path: "../../etc/passwd" }),
  });
  assert.equal(response.status, 422);
  assert.match((await response.json()).error.code, /not_found|path_outside_input/);
});

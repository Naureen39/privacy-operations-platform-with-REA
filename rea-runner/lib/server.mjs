import { timingSafeEqual } from "node:crypto";
import { createServer } from "node:http";
import { execute, COMMANDS } from "./commands.mjs";
import { RunnerError } from "./errors.mjs";
import { reaVersion } from "./rea.mjs";

const MAX_BODY_BYTES = 64 * 1024;
const MAX_CONCURRENT = Number(process.env.REA_MAX_CONCURRENT || 2);

function sameToken(provided, expected) {
  const a = Buffer.from(provided ?? "");
  const b = Buffer.from(expected);
  return a.length === b.length && timingSafeEqual(a, b);
}

function readBody(request) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    request.on("data", (chunk) => {
      size += chunk.length;
      if (size > MAX_BODY_BYTES) {
        reject(new RunnerError("request_too_large", "request body is too large"));
        request.destroy();
        return;
      }
      chunks.push(chunk);
    });
    request.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    request.on("error", reject);
  });
}

/** HTTP service used by the worker. It listens only on the private runner network. */
export function createRunnerServer(ctx, { token = process.env.REA_RUNNER_TOKEN } = {}) {
  let running = 0;
  return createServer(async (req, res) => {
    const send = (status, body) => {
      const text = JSON.stringify(body);
      res.writeHead(status, { "content-type": "application/json", "content-length": Buffer.byteLength(text) });
      res.end(text);
    };
    try {
      if (token && !sameToken(req.headers["x-runner-token"], token)) {
        return send(401, { ok: false, error: { code: "unauthorized", message: "missing or wrong runner token" } });
      }
      if (req.method === "GET" && req.url === "/v1/health") {
        return send(200, {
          ok: true,
          rea_version: await reaVersion(),
          node_version: process.version,
          role: { offline: ctx.allowOffline, browser: ctx.allowBrowser },
          commands: Object.entries(COMMANDS)
            .filter(([, c]) => (c.browser ? ctx.allowBrowser : ctx.allowOffline))
            .map(([name]) => name),
        });
      }
      if (req.method !== "POST" || req.url !== "/v1/run") return send(404, { ok: false, error: { code: "not_found", message: "unknown route" } });
      if (running >= MAX_CONCURRENT) return send(429, { ok: false, error: { code: "busy", message: "runner is at capacity" } });
      running += 1;
      try {
        let request;
        try {
          request = JSON.parse(await readBody(req));
        } catch (error) {
          if (error instanceof RunnerError) throw error;
          throw new RunnerError("invalid_request", "body must be JSON");
        }
        return send(200, await execute(ctx, request));
      } finally {
        running -= 1;
      }
    } catch (error) {
      const known = error instanceof RunnerError;
      const status = known && error.code === "request_too_large" ? 413 : known ? 422 : 500;
      return send(status, { ok: false, error: known ? error.toJSON() : { code: "internal_error", message: "unexpected runner failure" } });
    }
  });
}

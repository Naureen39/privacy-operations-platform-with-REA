import { copyFileSync, mkdtempSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, join } from "node:path";
import { observeWebsite } from "./browser.mjs";
import { RunnerError } from "./errors.mjs";
import { resolveInput } from "./paths.mjs";
import { reaVersion, runRea } from "./rea.mjs";

const SQLITE_EXTENSIONS = [".sqlite", ".sqlite3", ".db"];

function integerOption(options, name, fallback, min, max) {
  const value = options[name] ?? fallback;
  if (!Number.isInteger(value) || value < min || value > max) {
    throw new RunnerError("invalid_option", `${name} must be an integer between ${min} and ${max}`);
  }
  return value;
}

function rejectUnknown(options, allowed) {
  const extra = Object.keys(options).filter((k) => !allowed.includes(k));
  if (extra.length) throw new RunnerError("invalid_option", `unknown option(s): ${extra.join(", ")}`);
}

function requireFile(ctx, request, extensions) {
  const abs = resolveInput(ctx.inputRoot, request.path);
  if (!statSync(abs).isFile()) throw new RunnerError("invalid_path", "expected a file");
  if (!extensions.some((e) => abs.toLowerCase().endsWith(e))) {
    throw new RunnerError("invalid_path", `file extension must be one of ${extensions.join(", ")}`);
  }
  return abs;
}

async function inspectNetworkCapture(ctx, request) {
  rejectUnknown(request.options, []);
  const file = requireFile(ctx, request, [".har"]);
  return runRea(["inspect-web-network-capture", file, "har", "--json"], { timeoutMs: ctx.reaTimeoutMs });
}

async function inspectSqlite(ctx, request) {
  rejectUnknown(request.options, ["row_limit", "max_tables"]);
  const rowLimit = integerOption(request.options, "row_limit", 20, 1, 200);
  const maxTables = integerOption(request.options, "max_tables", 100, 1, 500);
  const file = requireFile(ctx, request, SQLITE_EXTENSIONS);

  // One call for the complete schema, then one bounded row sample per ordinary table.
  const schema = await runRea(["inspect-sqlite-database", file, "--schema-scope", "database", "--json"], {
    timeoutMs: ctx.reaTimeoutMs,
  });
  const tables = (schema.normalized_result?.schema?.tables ?? [])
    .filter((t) => t.kind === "table" && !t.name.startsWith("sqlite_"))
    .slice(0, maxTables);
  const samples = {};
  for (const table of tables) {
    try {
      const sampled = await runRea(
        ["inspect-sqlite-database", file, "--table", table.name, "--row-limit", String(rowLimit), "--json"],
        { timeoutMs: ctx.reaTimeoutMs },
      );
      samples[table.name] = { ok: true, rows: sampled.normalized_result?.rows ?? null };
    } catch (error) {
      samples[table.name] = { ok: false, error: error instanceof RunnerError ? error.toJSON() : { code: "unknown", message: String(error) } };
    }
  }
  return { schema, samples, tables_sampled: tables.length };
}

async function analyzeJavascript(ctx, request) {
  rejectUnknown(request.options, []);
  const abs = resolveInput(ctx.inputRoot, request.path);
  const stats = statSync(abs);
  let temp = null;
  let target = abs;
  if (stats.isFile()) {
    // REA analyses an application directory. Present a single saved script as one.
    temp = mkdtempSync(join(tmpdir(), "rea-js-"));
    copyFileSync(abs, join(temp, basename(abs)));
    target = temp;
  }
  try {
    return await runRea(["analyze-javascript-application", target, "--json"], { timeoutMs: ctx.reaTimeoutMs });
  } finally {
    if (temp) rmSync(temp, { recursive: true, force: true });
  }
}

async function observeSite(ctx, request) {
  rejectUnknown(request.options, ["allowed_origins", "observation_ms"]);
  const observationMs = integerOption(request.options, "observation_ms", 2500, 500, 20_000);
  const origins = request.options.allowed_origins ?? [];
  if (!Array.isArray(origins) || origins.length > 50 || !origins.every((o) => typeof o === "string" && /^https?:\/\/[^/\s]+$/.test(o))) {
    throw new RunnerError("invalid_option", "allowed_origins must be a list of at most 50 http(s) origins");
  }
  const common = { allowedOrigins: origins, observationMs, hardTimeoutMs: ctx.browserTimeoutMs, urlPolicy: ctx.urlPolicy };
  if (request.url) return observeWebsite({ ...common, url: request.url });
  const file = requireFile(ctx, request, [".html", ".htm"]);
  return observeWebsite({ ...common, file });
}

export const COMMANDS = {
  "inspect-web-network-capture": { run: inspectNetworkCapture, browser: false },
  "inspect-sqlite-database": { run: inspectSqlite, browser: false },
  "analyze-javascript-application": { run: analyzeJavascript, browser: false },
  "observe-website": { run: observeSite, browser: true },
};

/**
 * Validate and run one request. Returns a success envelope or throws RunnerError.
 * @param {object} ctx      {inputRoot, reaTimeoutMs, browserTimeoutMs, urlPolicy, allowBrowser}
 * @param {object} request  {command, path?, url?, options?}
 */
export async function execute(ctx, request) {
  if (!request || typeof request !== "object") throw new RunnerError("invalid_request", "request must be an object");
  const entry = Object.hasOwn(COMMANDS, request.command) ? COMMANDS[request.command] : null;
  if (!entry) throw new RunnerError("unknown_command", `command must be one of ${Object.keys(COMMANDS).join(", ")}`);
  if (entry.browser && !ctx.allowBrowser) throw new RunnerError("unsupported_here", "this runner does not provide a browser");
  if (!entry.browser && !ctx.allowOffline) throw new RunnerError("unsupported_here", "this runner only performs website observation");
  const options = request.options ?? {};
  if (typeof options !== "object" || Array.isArray(options)) throw new RunnerError("invalid_option", "options must be an object");
  if (request.url !== undefined && request.command !== "observe-website") throw new RunnerError("invalid_request", "url is only valid for observe-website");
  if (request.command === "observe-website" && Boolean(request.url) === Boolean(request.path)) {
    throw new RunnerError("invalid_request", "give exactly one of path or url");
  }
  const started = Date.now();
  const result = await entry.run(ctx, { ...request, options });
  return {
    ok: true,
    command: request.command,
    rea_version: await reaVersion(),
    duration_ms: Date.now() - started,
    result,
  };
}

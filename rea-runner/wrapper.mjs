#!/usr/bin/env node
/**
 * Thin wrapper around the REA command line.
 *
 *   node wrapper.mjs run <command> [--path RELATIVE_PATH | --url URL] [--options JSON]
 *       Runs one command and prints one JSON envelope: {ok, command, rea_version, duration_ms, result}
 *       or {ok: false, error: {code, message, details}}. Exit status 0 on success, 1 on failure.
 *
 *   node wrapper.mjs health
 *       Prints the REA version and the commands this runner provides.
 *
 *   node wrapper.mjs serve [--port 8080] [--host 0.0.0.0]
 *       HTTP service: POST /v1/run with the same request as JSON, GET /v1/health.
 *
 * Commands: inspect-web-network-capture, inspect-sqlite-database,
 *           analyze-javascript-application, observe-website.
 * Paths are relative to REA_INPUT_DIR (mounted read only in the container).
 * Environment: REA_INPUT_DIR, REA_RUNNER_ROLE (offline|browser|all), REA_RUNNER_TOKEN,
 *   REA_TIMEOUT_SECONDS, REA_BROWSER_TIMEOUT_SECONDS, OBSERVATION_ALLOWED_HOSTS (JSON list),
 *   OBSERVATION_ALLOWED_NETWORKS, OBSERVATION_ALLOWED_PORTS, CHROME_PATH, REA_BROWSER_NO_SANDBOX.
 */
import { execute } from "./lib/commands.mjs";
import { buildContext } from "./lib/context.mjs";
import { RunnerError } from "./lib/errors.mjs";
import { createRunnerServer } from "./lib/server.mjs";

function parseFlags(argv) {
  const flags = {};
  for (let i = 0; i < argv.length; i += 2) {
    const key = argv[i];
    if (!key?.startsWith("--") || argv[i + 1] === undefined) throw new RunnerError("invalid_request", `bad argument ${key ?? ""}`);
    flags[key.slice(2)] = argv[i + 1];
  }
  return flags;
}

async function main() {
  const [mode, ...rest] = process.argv.slice(2);
  const ctx = buildContext();

  if (mode === "serve") {
    const flags = parseFlags(rest);
    const server = createRunnerServer(ctx);
    const port = Number(flags.port ?? process.env.PORT ?? 8080);
    server.listen(port, flags.host ?? "0.0.0.0", () => console.log(JSON.stringify({ listening: port, role: process.env.REA_RUNNER_ROLE || "all" })));
    const stop = () => server.close(() => process.exit(0));
    process.on("SIGTERM", stop);
    process.on("SIGINT", stop);
    return;
  }

  if (mode === "health") {
    const { reaVersion } = await import("./lib/rea.mjs");
    const { COMMANDS } = await import("./lib/commands.mjs");
    const commands = Object.entries(COMMANDS)
      .filter(([, c]) => (c.browser ? ctx.allowBrowser : ctx.allowOffline))
      .map(([name]) => name);
    process.stdout.write(JSON.stringify({ ok: true, rea_version: await reaVersion(), node_version: process.version, commands }));
    return;
  }

  if (mode === "run") {
    const [command, ...flagArgs] = rest;
    try {
      const flags = parseFlags(flagArgs);
      const request = { command, path: flags.path, url: flags.url, options: flags.options ? JSON.parse(flags.options) : {} };
      process.stdout.write(JSON.stringify(await execute(ctx, request)));
    } catch (error) {
      const body = error instanceof RunnerError ? error.toJSON() : { code: "internal_error", message: String(error?.message ?? error) };
      process.stdout.write(JSON.stringify({ ok: false, error: body }));
      process.exitCode = 1;
    }
    return;
  }

  console.error("usage: wrapper.mjs run <command> [--path P | --url U] [--options JSON]  |  wrapper.mjs serve [--port N]");
  process.exitCode = 2;
}

main();

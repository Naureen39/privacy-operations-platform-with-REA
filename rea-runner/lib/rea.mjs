import { spawn } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { RunnerError } from "./errors.mjs";

const here = dirname(fileURLToPath(import.meta.url));
export const REA_BIN = process.env.REA_BIN || resolve(here, "../node_modules/rea-agents/scripts/rea.mjs");
const MAX_OUTPUT_BYTES = Number(process.env.REA_MAX_OUTPUT_BYTES || 256 * 1024 * 1024);
const STDERR_TAIL_BYTES = 8192;
// REA gets a minimal environment: no secrets from the runner's own configuration.
const PASS_THROUGH = ["PATH", "HOME", "USERPROFILE", "TMPDIR", "TEMP", "TMP", "SystemRoot", "LANG", "LC_ALL"];

function childEnv() {
  return Object.fromEntries(PASS_THROUGH.filter((k) => process.env[k] !== undefined).map((k) => [k, process.env[k]]));
}

/**
 * Run one REA command line (no shell) and parse its JSON output.
 * REA reports failures as JSON on stdout with exit status 1; those become RunnerError("rea_error").
 *
 * @param {string[]} args   arguments after the REA entry point
 * @param {{timeoutMs?: number, cwd?: string}} [options]
 */
export function runRea(args, { timeoutMs = 120_000, cwd } = {}) {
  return new Promise((resolvePromise, reject) => {
    const child = spawn(process.execPath, [REA_BIN, ...args], {
      cwd,
      shell: false,
      stdio: ["ignore", "pipe", "pipe"],
      env: childEnv(),
    });
    const chunks = [];
    let bytes = 0;
    let tail = "";
    let overflow = false;
    let timedOut = false;

    const timer = setTimeout(() => {
      timedOut = true;
      child.kill("SIGKILL");
    }, timeoutMs);

    child.stdout.on("data", (chunk) => {
      bytes += chunk.length;
      if (bytes > MAX_OUTPUT_BYTES) {
        overflow = true;
        child.kill("SIGKILL");
        return;
      }
      chunks.push(chunk);
    });
    child.stderr.on("data", (chunk) => {
      tail = (tail + chunk.toString("utf8")).slice(-STDERR_TAIL_BYTES);
    });
    child.on("error", (error) => {
      clearTimeout(timer);
      reject(new RunnerError("spawn_failed", `could not start REA: ${error.message}`));
    });
    child.on("close", (exitCode) => {
      clearTimeout(timer);
      if (timedOut) return reject(new RunnerError("timeout", `REA exceeded ${Math.round(timeoutMs / 1000)} seconds`));
      if (overflow) return reject(new RunnerError("output_too_large", `REA output exceeded ${MAX_OUTPUT_BYTES} bytes`));
      const text = Buffer.concat(chunks).toString("utf8").trim();
      let parsed;
      try {
        parsed = text ? JSON.parse(text) : null;
      } catch {
        return reject(new RunnerError("invalid_output", "REA did not return JSON", { exit_code: exitCode, stderr_tail: tail.slice(-500) }));
      }
      if (exitCode !== 0) {
        const error = parsed && typeof parsed === "object" ? parsed : {};
        return reject(
          new RunnerError("rea_error", String(error.message ?? "REA failed"), {
            rea_code: error.code ?? null,
            rea_category: error.category ?? null,
            rea_details: error.details ?? null,
            exit_code: exitCode,
          }),
        );
      }
      resolvePromise(parsed);
    });
  });
}

let cachedVersion;
export async function reaVersion() {
  if (cachedVersion) return cachedVersion;
  const child = spawn(process.execPath, [REA_BIN, "--version"], { shell: false, stdio: ["ignore", "pipe", "ignore"] });
  let out = "";
  child.stdout.on("data", (c) => (out += c));
  await new Promise((r) => child.on("close", r));
  cachedVersion = out.trim().split(/\s+/).pop() || "unknown";
  return cachedVersion;
}

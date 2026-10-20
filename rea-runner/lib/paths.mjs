import { realpathSync } from "node:fs";
import { isAbsolute, resolve, sep } from "node:path";
import { RunnerError } from "./errors.mjs";

/**
 * Resolve a path given relative to the input root and refuse anything that escapes it,
 * including through symbolic links. The input root is mounted read only in the container.
 */
export function resolveInput(inputRoot, relative) {
  if (typeof relative !== "string" || relative === "" || relative.includes("\0") || isAbsolute(relative)) {
    throw new RunnerError("invalid_path", "path must be a non-empty relative path");
  }
  const root = realpathSync(inputRoot);
  let real;
  try {
    real = realpathSync(resolve(root, relative));
  } catch {
    throw new RunnerError("not_found", "input file or directory does not exist");
  }
  if (real !== root && !real.startsWith(root + sep)) {
    throw new RunnerError("path_outside_input", "path resolves outside the input directory");
  }
  return real;
}

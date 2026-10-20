import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { RunnerError } from "../lib/errors.mjs";
import { resolveInput } from "../lib/paths.mjs";

function fixture() {
  const root = mkdtempSync(join(tmpdir(), "runner-paths-"));
  mkdirSync(join(root, "input", "run1"), { recursive: true });
  writeFileSync(join(root, "input", "run1", "a.har"), "{}");
  writeFileSync(join(root, "secret.txt"), "outside");
  return { root, input: join(root, "input") };
}

const code = (fn) => {
  try {
    fn();
  } catch (error) {
    assert.ok(error instanceof RunnerError);
    return error.code;
  }
  return null;
};

test("resolves a relative file inside the input directory", () => {
  const { input } = fixture();
  assert.ok(resolveInput(input, "run1/a.har").endsWith("a.har"));
});

test("rejects traversal, absolute paths, empty values and null bytes", () => {
  const { root, input } = fixture();
  assert.equal(code(() => resolveInput(input, "../secret.txt")), "path_outside_input");
  assert.equal(code(() => resolveInput(input, "run1/../../secret.txt")), "path_outside_input");
  assert.equal(code(() => resolveInput(input, join(root, "secret.txt"))), "invalid_path");
  assert.equal(code(() => resolveInput(input, "")), "invalid_path");
  assert.equal(code(() => resolveInput(input, "a\0.har")), "invalid_path");
  assert.equal(code(() => resolveInput(input, "run1/missing.har")), "not_found");
  assert.equal(code(() => resolveInput(input, 42)), "invalid_path");
});

test("rejects a symbolic link that leads outside", (t) => {
  const { root, input } = fixture();
  try {
    symlinkSync(join(root, "secret.txt"), join(input, "link.txt"));
  } catch {
    t.skip("symbolic links are not permitted here");
    return;
  }
  assert.equal(code(() => resolveInput(input, "link.txt")), "path_outside_input");
});

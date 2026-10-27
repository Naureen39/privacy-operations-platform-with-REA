// Fails if any source file contains the long dash characters (U+2014 or U+2013), per the team standard.
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const skip = new Set(["node_modules", "dist", "test-results", "playwright-report"]);
const textual = /\.(ts|tsx|js|mjs|cjs|css|html|json|md|svg|txt|webmanifest)$/;
// Built from code points so this file does not contain the characters it forbids.
const DASHES = new RegExp(`[${String.fromCharCode(0x2013, 0x2014)}]`);
const bad = [];

async function walk(dir) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    if (skip.has(entry.name)) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) await walk(full);
    else if (textual.test(entry.name) && entry.name !== "package-lock.json") {
      const text = await readFile(full, "utf8");
      if (DASHES.test(text)) bad.push(path.relative(root, full));
    }
  }
}

await walk(root);
if (bad.length > 0) {
  console.error(`Long dash characters found in:\n${bad.join("\n")}`);
  process.exit(1);
}
console.log("No long dash characters.");

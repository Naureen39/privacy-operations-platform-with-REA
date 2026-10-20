/**
 * Optional Playwright capture against the real open source stacks from compose_estate.yml.
 *
 *   npm i -D playwright tsx && npx playwright install chromium
 *   npx tsx datasets/scripts/capture_evidence.ts web_shop http://127.0.0.1:8101/checkout/
 *
 * For each URL it records a HAR file (full content) and saves the rendered page as the website
 * snapshot, in the layout the platform expects:
 *
 *   datasets/estate/<system_id>/evidence/capture.har
 *   datasets/estate/<system_id>/evidence/website_snapshot.html
 *
 * Status: written against the Playwright API but NOT exercised by the automated tests or by the
 * committed evidence, which is produced offline by capture_evidence.py. Only point it at
 * systems you own or are authorized to examine, and use synthetic data only.
 */
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const [systemId, url] = process.argv.slice(2);
if (!systemId || !url) {
  console.error("usage: capture_evidence.ts <system_id> <url>");
  process.exit(1);
}

const outDir = join("datasets", "estate", systemId, "evidence");
mkdirSync(outDir, { recursive: true });

const browser = await chromium.launch();
const context = await browser.newContext({
  recordHar: { path: join(outDir, "capture.har"), content: "embed", mode: "full" },
});
const page = await context.newPage();
await page.goto(url, { waitUntil: "networkidle" });

// Fill visible text inputs with synthetic values so the flow produces realistic submissions.
for (const input of await page.locator("input[type=text], input[type=email], input[type=tel], textarea").all()) {
  const name = (await input.getAttribute("name")) ?? "";
  const value = name.includes("email") ? "sample.person@mail.example" : "Sample value";
  if (await input.isVisible()) await input.fill(value);
}
const submit = page.locator("button[type=submit], input[type=submit]").first();
if (await submit.count()) {
  await Promise.allSettled([page.waitForLoadState("networkidle"), submit.click()]);
}

writeFileSync(join(outDir, "website_snapshot.html"), await page.content(), "utf-8");
await context.close(); // flushes the HAR file
await browser.close();
console.log(`wrote ${outDir}`);

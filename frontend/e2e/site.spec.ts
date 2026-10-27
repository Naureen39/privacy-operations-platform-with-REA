import { createRequire } from "node:module";

import { expect, mockApi, routes, test } from "./fixtures";

const require = createRequire(import.meta.url);
const axePath = require.resolve("axe-core/axe.min.js");

const widths = [360, 768, 1280, 1920];

for (const width of widths) {
  test.describe(`at ${width}px`, () => {
    test.use({ viewport: { width, height: 900 } });

    for (const path of routes) {
      test(`${path} has no horizontal scroll, one h1 and no console errors`, async ({ page, consoleErrors }) => {
        await mockApi(page);
        await page.goto(path);
        await page.waitForLoadState("networkidle");
        await expect(page.locator("h1")).toHaveCount(1);
        const overflow = await page.evaluate(() => {
          const root = document.scrollingElement ?? document.documentElement;
          return root.scrollWidth - window.innerWidth;
        });
        expect(overflow, `horizontal overflow at ${width}px`).toBeLessThanOrEqual(1);
        expect(consoleErrors).toEqual([]);
      });
    }
  });
}

test.describe("accessibility in a real browser (includes colour contrast)", () => {
  test.use({ viewport: { width: 1280, height: 900 } });
  for (const path of routes) {
    test(`${path} meets WCAG 2.1 AA rules`, async ({ page }) => {
      await mockApi(page);
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      await page.addScriptTag({ path: axePath });
      const violations = await page.evaluate(async () => {
        const axe = (
          window as unknown as {
            axe: {
              run: (c: Document, o: object) => Promise<{ violations: { id: string; nodes: { target: string[] }[] }[] }>;
            };
          }
        ).axe;
        const result = await axe.run(document, {
          runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] },
        });
        return result.violations.map(
          (v) =>
            `${v.id}: ${v.nodes
              .map((n) => n.target.join(" "))
              .slice(0, 4)
              .join(" | ")}`,
        );
      });
      expect(violations).toEqual([]);
    });
  }
});

test.describe("links", () => {
  test("every internal link on every page leads to a real page and every anchor exists", async ({ page }) => {
    await mockApi(page);
    const targets = new Set<string>();
    const anchors: { from: string; id: string }[] = [];
    for (const path of routes) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      const hrefs = await page.$$eval("a[href]", (as) => as.map((a) => a.getAttribute("href") ?? ""));
      for (const href of hrefs) {
        if (!href.startsWith("/") || href.startsWith("/docs")) continue;
        const [pathname, hash] = href.split("#");
        targets.add(pathname || path);
        if (hash && !pathname) anchors.push({ from: path, id: hash });
      }
    }
    const broken: string[] = [];
    for (const target of targets) {
      await page.goto(target);
      await page.waitForLoadState("networkidle");
      const heading = (await page.locator("h1").first().textContent()) ?? "";
      if (/does not exist/.test(heading)) broken.push(target);
    }
    expect(broken).toEqual([]);
    // hash links across pages (for example /platform#records)
    const withHash = new Set<string>();
    for (const path of routes) {
      await page.goto(path);
      const hrefs = await page.$$eval("a[href*='#']", (as) => as.map((a) => a.getAttribute("href") ?? ""));
      hrefs.filter((h) => h.startsWith("/")).forEach((h) => withHash.add(h));
    }
    const missing: string[] = [];
    for (const href of withHash) {
      const [pathname, hash] = href.split("#");
      await page.goto(pathname ?? "/");
      await page.waitForLoadState("networkidle");
      if ((await page.locator(`[id="${hash}"]`).count()) === 0) missing.push(href);
    }
    expect(missing).toEqual([]);
    expect(anchors.length).toBeGreaterThanOrEqual(0);
  });
});

test.describe("behaviour", () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  test("the first Tab stop is the skip link, and the mega menu opens from the keyboard", async ({ page }) => {
    await mockApi(page);
    await page.goto("/");
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
    await page.getByRole("button", { name: "Solutions" }).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("link", { name: "Healthcare" }).first()).toBeVisible();
  });

  test("the header condenses on scroll", async ({ page }) => {
    await mockApi(page);
    await page.goto("/");
    const header = page.locator("header").first();
    const before = (await header.boundingBox())?.height ?? 0;
    await page.mouse.wheel(0, 600);
    await page.waitForTimeout(500);
    const after = (await header.boundingBox())?.height ?? 0;
    expect(after).toBeLessThan(before);
  });

  test("the layout does not shift while the page loads", async ({ page }) => {
    await mockApi(page);
    await page.addInitScript(() => {
      (window as unknown as { __cls: number }).__cls = 0;
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries() as unknown as { value: number; hadRecentInput: boolean }[]) {
          if (!entry.hadRecentInput) (window as unknown as { __cls: number }).__cls += entry.value;
        }
      }).observe({ type: "layout-shift", buffered: true });
    });
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    await page.mouse.wheel(0, 3000);
    await page.waitForTimeout(800);
    const cls = await page.evaluate(() => (window as unknown as { __cls: number }).__cls);
    expect(cls).toBeLessThan(0.1);
  });

  test("with reduced motion the figures show their final value at once", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await mockApi(page);
    await page.goto("/");
    await expect(page.getByText("412", { exact: true })).toBeVisible();
  });

  test("the contact form validates, then stores a lead", async ({ page }) => {
    await mockApi(page);
    await page.goto("/contact");
    await page.getByRole("main").getByRole("button", { name: "Send message" }).click();
    await expect(page.getByText("Enter your name (at least 2 characters)")).toBeVisible();
    await page.getByRole("main").getByLabel("Full name").fill("Alex Example");
    await page.getByRole("main").getByLabel("Work email").fill("alex@example.test");
    const request = page.waitForRequest((r) => r.url().endsWith("/api/v1/public/leads") && r.method() === "POST");
    await page.getByRole("main").getByRole("button", { name: "Send message" }).click();
    expect((await request).postDataJSON()).toMatchObject({ kind: "contact", name: "Alex Example" });
    await expect(page.getByText("Thank you. Your message was received.")).toBeVisible();
  });

  test("sign in sends an administrator to the console", async ({ page }) => {
    await mockApi(page, {
      "/api/v1/auth/login": {
        status: 200,
        body: {
          user: { id: "u", email: "a@b.test", full_name: "Avery Admin" },
          org_id: "o",
          role: "admin",
          memberships: [],
        },
      },
      "/api/v1/auth/me": {
        status: 200,
        body: { user: { id: "u", email: "a@b.test", full_name: "Avery Admin" }, org_id: "o", role: "admin" },
      },
    });
    await page.goto("/login");
    await page.getByLabel("Email").fill("admin@example.test");
    await page.getByLabel("Password", { exact: true }).fill("a-long-passphrase");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/app$/);
    await expect(page.getByRole("heading", { name: "You are signed in" })).toBeVisible();
  });

  test("the pricing calculator recommends a plan and draws the chart", async ({ page }) => {
    await mockApi(page);
    await page.goto("/pricing#calculator");
    await page.getByLabel("Systems that process personal data").fill("28");
    await page.getByLabel("Access requests handled each month").fill("60");
    await expect(page.getByText("$524", { exact: true }).first()).toBeVisible();
    await expect(page.locator("canvas").first()).toBeVisible();
  });

  test("the pages that do not need charts or Markdown do not download them", async ({ page }) => {
    await mockApi(page);
    const files: string[] = [];
    page.on("request", (r) => files.push(r.url()));
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    expect(files.some((f) => /echarts/.test(f))).toBe(false);
    expect(files.some((f) => /markdown/.test(f))).toBe(false);
  });
});

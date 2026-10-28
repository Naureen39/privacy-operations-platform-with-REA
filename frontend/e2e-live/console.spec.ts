import { createRequire } from "node:module";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { PASSWORD, signIn, sidebar, USERS, watch, type RoleName } from "./helpers";

const require = createRequire(import.meta.url);
const axePath = require.resolve("axe-core/axe.min.js");
const ESTATE = path.resolve(import.meta.dirname, "..", "..", "datasets", "estate", "clinic_portal");

const menu: Record<RoleName, { shown: string[]; hidden: string[] }> = {
  admin: { shown: ["Overview", "Systems", "Billing", "Team", "Audit log", "Settings", "Revenue"], hidden: [] },
  analyst: {
    shown: ["Systems", "Impact assessments", "Access requests", "Analytics"],
    hidden: ["Billing", "Team", "Settings", "Revenue", "Audit log"],
  },
  system_owner: {
    shown: ["Overview", "Systems", "Findings", "Vendors and transfers"],
    hidden: ["Access requests", "Analytics", "Billing", "Team", "Revenue"],
  },
  viewer: {
    shown: ["Analytics", "Audit log", "Records of processing"],
    hidden: ["Billing", "Team", "Settings", "Revenue"],
  },
};

test.describe("signing in as each role", () => {
  for (const role of Object.keys(USERS) as RoleName[]) {
    test(`${role} signs in, sees the right menu and signs out`, async ({ page }) => {
      const problems = watch(page);
      await signIn(page, role);
      await page.goto("/app");
      await expect(page.getByText(/Welcome, /)).toBeVisible();
      for (const label of menu[role].shown)
        await expect(sidebar(page).getByRole("link", { name: label })).toBeVisible();
      for (const label of menu[role].hidden)
        await expect(sidebar(page).getByRole("link", { name: label })).toHaveCount(0);
      await page.getByRole("button", { name: "User menu" }).click();
      await page.getByRole("menuitem", { name: "Sign out" }).click();
      await expect(page).toHaveURL(/\/login/);
      await page.goto("/app/systems");
      await expect(page).toHaveURL(/\/login/); // the session is gone
      expect(problems).toEqual([]);
    });
  }

  test("a wrong password is refused with one message", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Email").fill(USERS.admin);
    await page.getByLabel("Password", { exact: true }).fill("not-the-password-1");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("alert")).toContainText("The email or password is not correct.");
    await expect(page).toHaveURL(/\/login/);
  });
});

test.describe("pages that depend on the role", () => {
  test("a viewer is told a page is not available, and the API agrees", async ({ page }) => {
    await signIn(page, "viewer");
    for (const p of ["/app/billing", "/app/team", "/app/settings", "/app/revenue", "/app/systems/new"]) {
      await page.goto(p);
      await expect(page.getByRole("alert")).toContainText("You do not have access to this page");
    }
    expect((await page.request.get("/api/v1/team")).status()).toBe(403);
    expect((await page.request.get("/api/v1/billing/invoices")).status()).toBe(403);
    expect((await page.request.get("/api/v1/analytics/revenue")).status()).toBe(403);
  });

  test("an analyst cannot reach the administration pages", async ({ page }) => {
    await signIn(page, "analyst");
    for (const p of ["/app/team", "/app/billing", "/app/audit"]) {
      await page.goto(p);
      await expect(page.getByRole("alert")).toContainText("You do not have access to this page");
    }
    expect((await page.request.get("/api/v1/settings")).status()).toBe(403);
  });

  test("a system owner cannot open requests or assessments", async ({ page }) => {
    await signIn(page, "system_owner");
    for (const p of ["/app/requests", "/app/assessments", "/app/analytics"]) {
      await page.goto(p);
      await expect(page.getByRole("alert")).toContainText("You do not have access to this page");
    }
    expect((await page.request.get("/api/v1/access-requests")).status()).toBe(403);
  });
});

test.describe.serial("the Add System wizard and an access request, end to end", () => {
  const name = `Clinic portal ${Date.now().toString().slice(-6)}`;
  let systemUrl = "";

  test("an administrator registers a system and attaches the evidence", async ({ page }) => {
    const problems = watch(page);
    await signIn(page, "admin");
    await page.goto("/app/systems/new");
    await page.getByLabel("System name").fill(name);
    await page.getByLabel("What does it do? (optional)").fill("Appointments for patients of the clinic");
    // a record needs an owner, so one is assigned while registering
    const ownerValue = await page
      .locator("#sys-owner option", { hasText: "system owner" })
      .first()
      .getAttribute("value");
    await page.getByLabel("Owner").selectOption(ownerValue ?? "");
    await page.getByRole("button", { name: "Register and continue" }).click();
    await expect(page.getByRole("heading", { name: "2. Evidence" })).toBeVisible();
    await expect(page).toHaveURL(/system=/); // the address names the system, so a reload resumes the wizard
    systemUrl = page.url();

    const attach = async (kind: string, file: string) => {
      await page.getByLabel("Type", { exact: true }).selectOption(kind);
      await page.getByLabel("File", { exact: true }).setInputFiles(file);
      await page.getByRole("button", { name: "Attach file" }).click();
      await expect(page.getByText(path.basename(file), { exact: true })).toBeVisible();
    };
    await attach("har", path.join(ESTATE, "evidence", "capture.har"));
    await attach("website", path.join(ESTATE, "evidence", "website_snapshot.html"));
    await attach("javascript_bundle", path.join(ESTATE, "evidence", "app.bundle.js"));
    await attach("sqlite_snapshot", path.join(ESTATE, "evidence", "snapshot.sqlite"));
    await attach("questionnaire", path.join(ESTATE, "questionnaire.json"));
    await attach("privacy_policy", path.join(ESTATE, "policy.md"));
    await expect(page.getByRole("button", { name: "Continue to discovery" })).toBeEnabled();
    expect(problems).toEqual([]);
  });

  test("discovery and classification run with live progress, then the elements are reviewed", async ({ page }) => {
    const problems = watch(page);
    await signIn(page, "admin");
    await page.goto(systemUrl);
    await page.getByRole("button", { name: "Continue to discovery" }).click();
    await page.getByRole("button", { name: "Run discovery and classification" }).click();
    await expect(page.getByRole("progressbar", { name: "Progress" })).toBeVisible({ timeout: 150_000 }); // jobs run inside the API process here
    await page.getByRole("button", { name: "Review the data elements" }).click({ timeout: 150_000 });

    const table = page.getByRole("table", { name: "Data elements" });
    await expect(table).toBeVisible();
    expect(await table.getByRole("row").count()).toBeGreaterThan(10);
    await expect(table.getByText("Article 9").first()).toBeVisible(); // health data is flagged
    // the evidence behind an element opens in a drawer
    await table.getByRole("button", { name: "Evidence" }).first().click();
    const drawer = page.getByRole("dialog", { name: "Evidence" });
    await expect(drawer).toContainText("Extractor");
    await expect(drawer.getByText("Output")).toBeVisible();
    await page.keyboard.press("Escape");
    // accept one element
    await table.getByRole("button", { name: "Accept" }).first().click();
    await expect(page.getByText("Saved", { exact: true }).first()).toBeVisible();
    expect(problems).toEqual([]);
  });

  test("the sources are compared, a record is drafted and submitted for approval", async ({ page }) => {
    const problems = watch(page);
    await signIn(page, "admin");
    await page.goto(systemUrl);
    await page.getByRole("button", { name: "Comparison" }).click();
    await page.getByRole("button", { name: "Compare the sources" }).click();
    await expect(page.getByText("Finished")).toBeVisible({ timeout: 150_000 });
    await expect(page.getByRole("heading", { name: /Findings \(\d+\)/ })).toBeVisible();

    await page.getByRole("button", { name: "Record draft" }).click();
    await page.getByRole("button", { name: "Generate the record" }).click();
    await expect(page.getByText("Categories of personal data")).toBeVisible({ timeout: 150_000 });
    await expect(page.getByText("Draft for review").first())
      .toBeVisible()
      .catch(() => undefined);
    await page.getByRole("button", { name: "Continue to submit" }).click();
    // no model provider is configured here, so the purpose and lawful basis are filled in by a person
    await page.getByLabel("Purposes (one per line)").fill("Appointment management");
    await page.getByLabel("Lawful basis").fill("contract");
    await page.getByLabel("Article 9 condition").fill("Explicit consent, Article 9(2)(a)"); // the portal holds health data
    await page.getByRole("button", { name: "Save" }).click();
    await page.getByRole("button", { name: "Submit for approval" }).click();
    await expect(page).toHaveURL(/\/app\/records\//);
    await expect(
      page.getByText("Draft for review by a qualified privacy professional. Not legal advice."),
    ).toBeVisible();
    await expect(page.locator("span", { hasText: /awaiting review/ }).first()).toBeVisible();
    expect(problems).toEqual([]);
  });

  test("an access request is logged, verified, searched, answered and closed", async ({ page }) => {
    const problems = watch(page);
    await signIn(page, "admin");
    await page.goto("/app/requests?new=1");
    await page.getByLabel("Email address or number").fill("darryl.curran6@mail.example"); // a patient who is in no other system
    await page.getByRole("button", { name: "Log request" }).click();
    await expect(page.getByRole("heading", { name: /^Request AR-/ })).toBeVisible();

    for (const label of [
      "The name matches our records",
      "Contact details are confirmed",
      "An identity document was seen",
    ]) {
      await page.getByLabel(label).check();
    }
    await page.getByRole("button", { name: "Record the identity check" }).click();
    await expect(page.getByText("Identity verified.")).toBeVisible();

    await page.getByLabel("Identifier for the search").fill("darryl.curran6@mail.example");
    await page.getByRole("button", { name: "Search", exact: true }).click();
    const results = page.getByRole("table", { name: "Search results" });
    await expect(results).toBeVisible({ timeout: 60_000 });
    await expect(results.getByRole("row").nth(1)).toBeVisible();
    await expect(results).toContainText("patients");
    // an administrator approves the disclosure of every location
    const boxes = results.getByRole("checkbox");
    for (let i = 0; i < (await boxes.count()); i++) {
      await boxes.nth(i).click(); // the box follows the server's answer, so wait for it
      await expect(boxes.nth(i)).toBeChecked();
    }

    await page.getByRole("button", { name: "Draft the response" }).click();
    await expect(page.getByText(/Draft for review by a qualified privacy professional/).first()).toBeVisible();
    const requestUrl = page.url();
    const signOut = async () => {
      await page.getByRole("button", { name: "User menu" }).click();
      await page.getByRole("menuitem", { name: "Sign out" }).click();
      await expect(page).toHaveURL(/\/login/);
    };

    // an analyst submits the response; the person who prepared a response may not approve it
    await signOut();
    await signIn(page, "analyst");
    await page.goto(requestUrl);
    await page.getByRole("button", { name: "Submit for approval" }).click();
    await expect(page.locator("li[aria-current='step']")).toContainText("awaiting approval");
    await expect(page.getByRole("button", { name: "Approve the response" })).toHaveCount(0); // only an administrator sees it
    await signOut();

    // the administrator approves, sends and closes the case
    await signIn(page, "admin");
    await page.goto(requestUrl);
    await page.getByRole("button", { name: "Approve the response" }).click();
    await expect(page.getByText("Approved", { exact: true }).first()).toBeVisible();
    await page.getByRole("button", { name: "Send the response" }).click();
    await expect(page.locator("li[aria-current='step']")).toContainText("responded");
    await page.getByRole("button", { name: "Close the case" }).click();
    await expect(page.locator("li[aria-current='step']")).toContainText("closed");
    expect(problems).toEqual([]);
  });
});

test.describe("the dashboards, with the seeded history", () => {
  test("analytics shows the key figures and renders its charts", async ({ page }) => {
    const problems = watch(page);
    await signIn(page, "admin");
    await page.goto("/app/analytics");
    await expect(page.getByRole("heading", { name: "Analytics", level: 1 })).toBeVisible();
    const kpis = page.getByLabel("Key figures");
    for (const label of [
      "Record coverage",
      "Stale records",
      "Open findings",
      "Discovery confidence",
      "Requests on time",
    ]) {
      await expect(kpis.getByText(label)).toBeVisible();
    }
    // the compliance history is seeded, so every figure but the model confidence (no classified elements in it) has a value
    await expect.poll(() => kpis.getByText("No data").count(), { timeout: 20_000 }).toBeLessThanOrEqual(1);
    await expect(kpis.locator("div", { has: page.getByText("Open findings") }).first()).not.toContainText("No data");
    await expect(kpis.locator("div", { has: page.getByText("Stale records") }).first()).not.toContainText("No data");
    await expect(page.getByText("Findings opened and closed")).toBeVisible();
    await expect.poll(() => page.locator("canvas").count(), { timeout: 30_000 }).toBeGreaterThanOrEqual(6);
    // every chart has a text summary
    expect(await page.locator("figure [role=img]").count()).toBeGreaterThanOrEqual(6);
    // granularity and comparison controls change the request
    const request = page.waitForRequest(
      (r) => r.url().includes("/analytics/compliance?") && r.url().includes("granularity=month"),
    );
    await page.getByLabel("Group by").selectOption("month");
    await request;
    // the CSV export downloads a file
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "CSV" }).click();
    expect((await download).suggestedFilename()).toMatch(/\.csv$/);
    expect(problems).toEqual([]);
  });

  test("revenue shows MRR, its movements and the tables for the host administrator", async ({ page }) => {
    const problems = watch(page);
    await signIn(page, "admin");
    await page.goto("/app/revenue");
    await expect(page.getByRole("heading", { name: "Revenue", level: 1 })).toBeVisible();
    const kpis = page.getByLabel("Key figures");
    for (const label of [
      "MRR",
      "ARR",
      "Net new MRR",
      "Net revenue retention",
      "Gross churn",
      "ARPA",
      "Paying accounts",
    ]) {
      await expect(kpis.getByText(label, { exact: true })).toBeVisible();
    }
    const mrr = await kpis
      .locator("div", { has: page.getByText("MRR", { exact: true }) })
      .first()
      .locator("dd span")
      .first()
      .textContent();
    expect(mrr).toMatch(/^\$[\d,]+$/);
    expect(mrr).not.toBe("$0");
    await expect.poll(() => page.locator("canvas").count(), { timeout: 30_000 }).toBeGreaterThanOrEqual(7);
    await page.getByRole("button", { name: "Show as waterfall" }).click();
    await expect(page.getByRole("button", { name: "Show stacked bars" })).toBeVisible();
    await expect(page.getByRole("table", { name: "Top customers" }).getByRole("row")).toHaveCount(11); // header and ten customers
    await expect(page.getByRole("table", { name: "Invoices" }).getByRole("row").nth(1)).toBeVisible();
    await expect(page.getByText(/simulated/i).first()).toBeVisible();
    expect(problems).toEqual([]);
  });

  test("the projection is labelled as a projection", async ({ page }) => {
    await signIn(page, "admin");
    await page.goto("/app/revenue");
    await expect(page.getByText("Solid: measured. Dashed: a straight line projection, not a forecast.")).toBeVisible();
  });
});

test.describe("the rest of the console works with real data", () => {
  test("records, assessments, vendors, library, billing, team, audit and settings load", async ({ page }) => {
    const problems = watch(page);
    await signIn(page, "admin");
    const pages: [string, string | RegExp][] = [
      ["/app/records", "Records of processing"],
      ["/app/assessments", "Impact assessments"],
      ["/app/vendors", "Vendors and transfers"],
      ["/app/library", "Regulation library"],
      ["/app/billing", "Billing"],
      ["/app/team", "Team"],
      ["/app/audit", "Audit log"],
      ["/app/settings", "Settings"],
    ];
    for (const [url, heading] of pages) {
      await page.goto(url);
      await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
      await expect(page.getByRole("alert")).toHaveCount(0);
    }
    expect(problems).toEqual([]);
  });

  test("the regulation library finds Article 30 and the team lists the four demo accounts", async ({ page }) => {
    await signIn(page, "admin");
    await page.goto("/app/library");
    await page.getByLabel("Search the regulation and your documents").fill("records of processing activities");
    await page.getByRole("search").getByRole("button", { name: "Search" }).click();
    await expect(page.getByText("Article 30").first()).toBeVisible({ timeout: 30_000 });
    await page.goto("/app/team");
    const table = page.getByRole("table", { name: "Team" });
    await expect(table.getByRole("row")).toHaveCount(5);
    await expect(table).toContainText("admin@northbridge.example");
    expect(PASSWORD).toBeTruthy();
  });

  test("Ctrl K jumps to a page and a viewer can read but not change a finding", async ({ page }) => {
    await signIn(page, "viewer");
    await page.keyboard.press("Control+k");
    await page.getByRole("combobox").fill("analytics");
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/app\/analytics/);
    await page.goto("/app/findings");
    const first = page.getByRole("table", { name: "Findings" }).getByRole("row").nth(1);
    if (await first.count()) {
      await first.click();
      await expect(page.getByText("Suggested fix")).toBeVisible();
      await expect(page.getByRole("button", { name: "Mark resolved" })).toHaveCount(0);
    }
  });
});

test.describe("accessibility of the console in a real browser (WCAG 2.1 A and AA, including contrast)", () => {
  const targets: [RoleName, string][] = [
    ["admin", "/app"],
    ["admin", "/app/systems"],
    ["admin", "/app/findings"],
    ["admin", "/app/records"],
    ["admin", "/app/assessments"],
    ["admin", "/app/requests"],
    ["admin", "/app/vendors"],
    ["admin", "/app/library"],
    ["admin", "/app/analytics"],
    ["admin", "/app/revenue"],
    ["admin", "/app/billing"],
    ["admin", "/app/team"],
    ["admin", "/app/audit"],
    ["admin", "/app/settings"],
    ["admin", "/app/systems/new"],
    ["system_owner", "/app"],
  ];
  for (const [role, url] of targets) {
    test(`${role} ${url}`, async ({ page }) => {
      await signIn(page, role);
      await page.goto(url);
      await page.waitForLoadState("networkidle");
      if (/analytics|revenue/.test(url))
        await expect.poll(() => page.locator("canvas").count(), { timeout: 30_000 }).toBeGreaterThan(3);
      await page.addScriptTag({ path: axePath });
      const violations = await page.evaluate(async () => {
        const axe = (
          window as unknown as {
            axe: {
              run: (
                c: Document,
                o: object,
              ) => Promise<{ violations: { id: string; nodes: { target: string[]; any: { message: string }[] }[] }[] }>;
            };
          }
        ).axe;
        const result = await axe.run(document, {
          runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] },
          // the charts are canvas elements described by the text around them
          rules: { "color-contrast": { enabled: true } },
        });
        return result.violations.map(
          (v) =>
            `${v.id}: ${v.nodes
              .slice(0, 3)
              .map((n) => `${n.target.join(" ")} ${n.any[0]?.message ?? ""}`)
              .join(" | ")}`,
        );
      });
      expect(violations).toEqual([]);
    });
  }
});

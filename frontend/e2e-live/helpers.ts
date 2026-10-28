import { expect, type Page } from "@playwright/test";

export const PASSWORD = "E2e-Demo-Pass-12345";
export const USERS = {
  admin: "admin@northbridge.example",
  analyst: "analyst@northbridge.example",
  system_owner: "owner@northbridge.example",
  viewer: "auditor@northbridge.example",
} as const;
export type RoleName = keyof typeof USERS;

export async function signIn(page: Page, role: RoleName) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(USERS[role]);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/app/);
  await expect(page.getByRole("navigation", { name: "Console" })).toBeVisible();
}

export function sidebar(page: Page) {
  return page.getByRole("navigation", { name: "Console" });
}

/** Console errors and failed API calls seen while a test runs. */
export function watch(page: Page) {
  const problems: string[] = [];
  page.on("pageerror", (e) => problems.push(`page error: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error" && !/Failed to load resource/.test(m.text())) problems.push(`console: ${m.text()}`);
  });
  page.on("response", (r) => {
    const url = new URL(r.url());
    if (url.pathname.startsWith("/api/") && r.status() >= 500) problems.push(`${r.status()} ${url.pathname}`);
  });
  return problems;
}

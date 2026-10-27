import { test as base, expect, type Page } from "@playwright/test";

export const plans = [
  {
    code: "starter",
    name: "Starter",
    monthly_fee_cents: 0,
    included_systems: 3,
    included_requests: 5,
    extra_system_cents: 0,
    extra_request_cents: 0,
  },
  {
    code: "professional",
    name: "Professional",
    monthly_fee_cents: 39900,
    included_systems: 25,
    included_requests: 50,
    extra_system_cents: 1500,
    extra_request_cents: 800,
  },
  {
    code: "enterprise",
    name: "Enterprise",
    monthly_fee_cents: 180000,
    included_systems: 150,
    included_requests: 500,
    extra_system_cents: 600,
    extra_request_cents: 400,
  },
];

export const metrics = {
  as_of: "2026-10-26",
  accounts: 98,
  systems: 412,
  requests: 17,
  cache_hits: 3,
  failovers: 1,
  regulation_passages: 520,
  simulated: true,
  note: "Figures marked simulated are generated for the demonstration; there are no real customers.",
};

export const routes = [
  "/",
  "/platform",
  "/solutions",
  "/solutions/healthcare",
  "/solutions/retail",
  "/solutions/financial-services",
  "/solutions/public-sector",
  "/solutions/technology",
  "/regulations",
  "/pricing",
  "/security",
  "/resources",
  "/resources/docs/architecture",
  "/resources/docs/database",
  "/resources/docs/security",
  "/resources/articles/evidence-based-records",
  "/resources/articles/token-efficient-classification",
  "/resources/articles/access-request-search",
  "/company",
  "/contact",
  "/legal/privacy",
  "/legal/terms",
  "/status",
  "/login",
];

/** Stand in for the API: the price list, the public figures, health and leads. */
export async function mockApi(page: Page, overrides: Record<string, { status: number; body: unknown }> = {}) {
  const table: Record<string, { status: number; body: unknown }> = {
    "/api/v1/public/plans": { status: 200, body: plans },
    "/api/v1/public/metrics": { status: 200, body: metrics },
    "/api/v1/public/leads": { status: 202, body: { status: "accepted" } },
    "/health": { status: 200, body: { status: "ok" } },
    "/ready": { status: 200, body: { status: "ready" } },
    ...overrides,
  };
  await page.route(/\/(api\/v1\/.*|health|ready)$/, async (route) => {
    const path = new URL(route.request().url()).pathname;
    const hit = table[path];
    if (!hit) return route.fulfill({ status: 404, json: { detail: "Not found" } });
    return route.fulfill({ status: hit.status, json: hit.body });
  });
}

export const test = base.extend<{ consoleErrors: string[] }>({
  consoleErrors: async ({ page }, provide) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("console", (m) => {
      if (m.type() === "error") errors.push(m.text());
    });
    await provide(errors);
  },
});

export { expect };

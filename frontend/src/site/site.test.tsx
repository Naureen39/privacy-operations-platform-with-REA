import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import App from "@/App";
import { a11yViolations, mockFetch, renderAt } from "@/test/render";

vi.mock("@/charts/CostChart", () => ({ default: () => <div data-testid="cost-chart" /> }));

afterEach(() => vi.unstubAllGlobals());

const plans = [
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

const metrics = {
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

const api = { "/api/v1/public/plans": { body: plans }, "/api/v1/public/metrics": { body: metrics } };

describe("layout", () => {
  it("offers the six menus, Sign in and Open console, and a skip link", async () => {
    mockFetch(api);
    renderAt(<App />, "/");
    const main = screen.getByRole("navigation", { name: "Main" });
    for (const label of ["Platform", "Solutions", "Regulations", "Pricing", "Resources", "Company"]) {
      expect(within(main).getByRole("button", { name: label })).toBeInTheDocument();
    }
    const banner = within(screen.getByRole("banner"));
    expect(banner.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login");
    expect(banner.getByRole("link", { name: "Open console" })).toHaveAttribute("href", "/login");
    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute("href", "#main");
    const utility = screen.getByRole("navigation", { name: "Utility" });
    expect(
      within(utility)
        .getAllByRole("link")
        .map((a) => a.textContent),
    ).toEqual(["Contact", "Documentation", "Status"]);
  });

  it("opens the mobile drawer with every section", async () => {
    mockFetch(api);
    renderAt(<App />, "/");
    await userEvent.click(screen.getByRole("button", { name: "Open menu" }));
    const drawer = await screen.findByRole("navigation", { name: "Mobile" });
    expect(within(drawer).getByRole("link", { name: "Pricing" })).toHaveAttribute("href", "/pricing");
    expect(within(drawer).getByRole("link", { name: "Healthcare" })).toHaveAttribute("href", "/solutions/healthcare");
  });

  it("has a footer with five link columns, a contact form and the demonstration notice", async () => {
    mockFetch(api);
    renderAt(<App />, "/");
    const footer = screen.getByRole("navigation", { name: "Footer" });
    expect(within(footer).getAllByRole("heading", { level: 2 })).toHaveLength(5);
    expect(screen.getByRole("form", { name: "Quick message" })).toBeInTheDocument();
    expect(screen.getAllByText(/demonstration project/i).length).toBeGreaterThan(0);
  });
});

describe("home", () => {
  it("shows the headline, six capabilities, the metric band and the FAQ", async () => {
    mockFetch(api);
    renderAt(<App />, "/");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Know where personal data lives. Prove it with evidence.",
    );
    expect(screen.getByText("Compliance Analytics")).toBeInTheDocument();
    expect(await screen.findByText(/Demo environment figures/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Is this a finished commercial product?" }));
    expect(await screen.findByText(/revenue figures are simulated/i)).toBeInTheDocument();
  });

  it("hides the metric band when the figures cannot be loaded", async () => {
    mockFetch({});
    renderAt(<App />, "/");
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByText(/Demo environment figures/)).not.toBeInTheDocument();
  });

  it("has no structural accessibility violations", async () => {
    mockFetch(api);
    const { container } = renderAt(<App />, "/");
    await screen.findByText(/Demo environment figures/);
    expect(await a11yViolations(container)).toEqual([]);
  });
});

describe("pricing", () => {
  it("shows the plans from the API and a working calculator", async () => {
    mockFetch(api);
    renderAt(<App />, "/pricing");
    expect(await screen.findByRole("heading", { name: "Enterprise" })).toBeInTheDocument();
    expect(screen.getAllByText("$399").length).toBeGreaterThan(0);
    const systems = await screen.findByLabelText("Systems that process personal data");
    const requests = screen.getByLabelText("Access requests handled each month");
    await userEvent.clear(systems);
    await userEvent.type(systems, "28");
    await userEvent.clear(requests);
    await userEvent.type(requests, "60");
    const table = screen.getByRole("table", { name: "Estimated monthly cost by plan" });
    const pro = within(table).getByRole("row", { name: /Professional/ });
    expect(pro).toHaveTextContent("$524"); // 399 + 3 * 15 + 10 * 8
    expect(within(table).getByRole("row", { name: /Starter/ })).toHaveTextContent("Not available");
    expect(await screen.findByTestId("cost-chart")).toBeInTheDocument();
  });

  it("falls back to the default plans and says so when the API is down", async () => {
    mockFetch({});
    renderAt(<App />, "/pricing");
    expect(await screen.findByText(/could not be loaded, so the default plans are shown/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Professional" })).toBeInTheDocument();
  });
});

describe("content pages", () => {
  it.each([
    ["/platform", "One pipeline from evidence to an approved record"],
    ["/solutions", "The same evidence based approach, five sectors"],
    ["/solutions/healthcare", "Patient and staff data across clinical and administrative systems."],
    ["/regulations", "Three parts of the GDPR, covered end to end"],
    ["/security", "What is implemented, and nothing more"],
    ["/resources", "Documentation and technical writing"],
    ["/company", "A demonstration of evidence based privacy operations"],
    ["/contact", "Get in touch"],
    ["/legal/privacy", "Privacy policy (sample)"],
    ["/legal/terms", "Terms of use (sample)"],
    ["/status", "System status"],
    ["/no-such-page", "This page does not exist"],
  ])("renders %s with one h1 and no structural violations", async (path, heading) => {
    mockFetch(api);
    const { container } = renderAt(<App />, path);
    expect(await screen.findByRole("heading", { level: 1, name: heading })).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(await a11yViolations(container)).toEqual([]);
  });

  it("answers an unknown industry with the not found page", async () => {
    mockFetch(api);
    renderAt(<App />, "/solutions/mining");
    expect(await screen.findByRole("heading", { name: "This page does not exist" })).toBeInTheDocument();
  });

  it("lists the documents and three articles", async () => {
    mockFetch(api);
    renderAt(<App />, "/resources");
    expect(await screen.findByRole("link", { name: "Architecture" })).toHaveAttribute(
      "href",
      "/resources/docs/architecture",
    );
    expect(screen.getByRole("link", { name: "Security model" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Evidence based record generation" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Token efficient classification" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Searching for a person without exposing them" })).toBeInTheDocument();
  });

  it("renders a project document as Markdown", async () => {
    mockFetch(api);
    renderAt(<App />, "/resources/docs/security");
    expect(await screen.findByRole("heading", { name: /Security Model/ }, { timeout: 5000 })).toBeInTheDocument();
  });

  it("renders an article", async () => {
    mockFetch(api);
    renderAt(<App />, "/resources/articles/access-request-search");
    expect(
      await screen.findByRole("heading", { name: "Searching for a person without exposing them" }),
    ).toBeInTheDocument();
  });

  it("shows live status from the health endpoints", async () => {
    mockFetch({ "/health": { body: { status: "ok" } }, "/ready": { status: 503, body: {} } });
    renderAt(<App />, "/status");
    expect(await screen.findByText("Operational")).toBeInTheDocument();
    expect(await screen.findByText("Unavailable")).toBeInTheDocument();
  });
});

describe("contact page", () => {
  it("opens the demo request tab from the query string", async () => {
    mockFetch(api);
    renderAt(<App />, "/contact?tab=demo");
    expect(await screen.findByRole("button", { name: "Request a demo", pressed: undefined })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Request a demo" })).toHaveAttribute("aria-selected", "true");
  });
});

describe("console route", () => {
  it("sends a visitor without a session to the sign in page", async () => {
    mockFetch({ "/api/v1/auth/me": { status: 401, body: { detail: "Authentication required" } } });
    renderAt(<App />, "/app");
    expect(await screen.findByRole("heading", { level: 1, name: "Sign in" })).toBeInTheDocument();
  });
});

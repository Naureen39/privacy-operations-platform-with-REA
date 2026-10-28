import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes, useLocation } from "react-router-dom";

import App from "@/App";
import type { Role } from "@/lib/api";
import { a11yViolations, mockFetch, renderAt } from "@/test/render";

vi.mock("@/app/charts/Chart", () => ({ default: () => <div data-testid="chart" /> }));

afterEach(() => vi.unstubAllGlobals());

const user = (role: Role, host = false) => ({
  status: 200,
  body: {
    user: { id: "u1", email: `${role}@example.test`, full_name: `Pat ${role}` },
    org_id: "o1",
    role,
    is_host: host,
  },
});

const system = (id: string, name: string, extra: Record<string, unknown> = {}) => ({
  id,
  name,
  slug: name.toLowerCase().replaceAll(" ", "-"),
  description: null,
  owner_user_id: null,
  status: "CREATED",
  last_discovery_at: null,
  ...extra,
});

const finding = (id: string, title: string, severity: string, status = "open") => ({
  id,
  title,
  severity,
  status,
  type: "missing_agreement",
  description: "Described",
  suggested_fix: "Fix it",
  evidence_refs: ["har:cap.har"],
  system_id: "s1",
  activity_id: null,
  created_at: "2026-10-01T10:00:00Z",
});

function api(role: Role, host = false, extra: Record<string, { status?: number; body?: unknown }> = {}) {
  return mockFetch({
    "/api/v1/auth/me": user(role, host),
    "/api/v1/auth/organizations": {
      body: [
        { org_id: "o1", name: "Northbridge", role, current: true },
        { org_id: "o2", name: "Globex", role: "viewer", current: false },
      ],
    },
    "/api/v1/systems": { body: [system("s1", "Web shop"), system("s2", "CRM")] },
    "/api/v1/activities": {
      body: [
        {
          id: "a1",
          name: "Customer support",
          status: "approved",
          system_ids: ["s1"],
          next_review_date: "2020-01-01",
          missing_fields: [],
          current_version: 2,
          lawful_basis: "contract",
        },
      ],
    },
    "/api/v1/findings": {
      body: [finding("f1", "Recipient not declared", "high"), finding("f2", "Retention conflict", "medium")],
    },
    "/api/v1/dpias": {
      body: [
        {
          id: "d1",
          activity_id: "a1",
          activity_name: "Customer support",
          status: "draft",
          criteria_met: 3,
          risks: 2,
          residual_risk: null,
          created_at: "2026-10-01T10:00:00Z",
        },
      ],
    },
    "/api/v1/access-requests": {
      body: [
        {
          id: "r1",
          reference: "REQ-2026-0001",
          status: "searching",
          received_date: "2026-10-10",
          deadline_date: "2026-11-10",
          days_remaining: 5,
          overdue: false,
          possible_duplicates: [],
          identity_checklist: {},
        },
      ],
    },
    "/api/v1/access-requests/reminders": { body: [] },
    "/api/v1/tasks": { body: [] },
    "/api/v1/vendors": { body: [] },
    "/api/v1/notifications": {
      body: [
        {
          id: "n1",
          kind: "x",
          title: "A record needs review",
          body: null,
          entity_type: "processing_activity",
          entity_id: "a1",
          created_at: "2026-10-01T10:00:00Z",
          read_at: null,
        },
      ],
    },
    "/health": { body: { status: "ok" } },
    ...extra,
  });
}

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>;
}

const open = (path: string) =>
  renderAt(
    <>
      <App />
      <Routes>
        <Route path="*" element={<Where />} />
      </Routes>
    </>,
    path,
  );

const sidebar = () => within(screen.getAllByRole("navigation", { name: "Console" })[0] as HTMLElement);

describe("signing in to the console", () => {
  it("sends a visitor without a session to the sign in page", async () => {
    mockFetch({ "/api/v1/auth/me": { status: 401, body: { detail: "Authentication required" } } });
    renderAt(<App />, "/app/systems");
    expect(await screen.findByRole("heading", { level: 1, name: "Sign in" })).toBeInTheDocument();
  });

  it("shows an administrator the whole menu", async () => {
    api("admin");
    renderAt(<App />, "/app");
    await screen.findByText(/Welcome, Pat/);
    for (const label of ["Overview", "Systems", "Findings", "Billing", "Team", "Audit log", "Settings"]) {
      expect(sidebar().getByRole("link", { name: label })).toBeInTheDocument();
    }
    expect(sidebar().queryByRole("link", { name: "Revenue" })).not.toBeInTheDocument();
  });

  it("shows Revenue to the administrators of the host organization only", async () => {
    api("admin", true);
    renderAt(<App />, "/app");
    await screen.findByText(/Welcome, Pat/);
    expect(sidebar().getByRole("link", { name: "Revenue" })).toBeInTheDocument();
  });

  it.each([
    ["analyst", ["Impact assessments", "Access requests", "Analytics"], ["Billing", "Team", "Settings", "Revenue"]],
    ["viewer", ["Analytics", "Audit log"], ["Billing", "Team", "Settings"]],
    [
      "system_owner",
      ["Systems", "Findings", "Vendors and transfers"],
      ["Access requests", "Impact assessments", "Analytics", "Billing", "Audit log"],
    ],
  ] as [Role, string[], string[]][])("limits the menu of a %s", async (role, shown, hidden) => {
    api(role);
    renderAt(<App />, "/app");
    await screen.findByText(/Welcome, Pat/);
    for (const label of shown) expect(sidebar().getByRole("link", { name: label })).toBeInTheDocument();
    for (const label of hidden) expect(sidebar().queryByRole("link", { name: label })).not.toBeInTheDocument();
  });

  it("explains that a page is not available to the role instead of showing an empty screen", async () => {
    api("viewer");
    renderAt(<App />, "/app/billing");
    expect(await screen.findByRole("alert")).toHaveTextContent("You do not have access to this page");
    api("admin");
    renderAt(<App />, "/app/revenue");
    expect(await screen.findAllByText("You do not have access to this page")).not.toHaveLength(0);
  });

  it("hides the create buttons from a viewer", async () => {
    api("viewer");
    renderAt(<App />, "/app/systems");
    await screen.findByText("Web shop");
    expect(screen.queryByRole("link", { name: "Add a system" })).not.toBeInTheDocument();
  });
});

describe("overview", () => {
  it("counts approved, stale and open items from the lists", async () => {
    api("admin");
    renderAt(<App />, "/app");
    const posture = await screen.findByRole("group", { name: "Compliance posture" }).catch(() => null);
    expect(posture).toBeNull(); // a description list, not a group
    const dl = await screen.findByLabelText("Compliance posture");
    await waitFor(() => expect(within(dl).getByText("Open findings").nextSibling).toHaveTextContent("2"));
    expect(within(dl).getByText("Stale records").nextSibling).toHaveTextContent("1"); // review date 2020
    expect(within(dl).getByText("Approved records").nextSibling).toHaveTextContent("1");
    expect(within(dl).getByText("Systems").nextSibling).toHaveTextContent("2");
  });
});

describe("tables", () => {
  it("lists the systems with their record and open findings, and searches them", async () => {
    api("admin");
    renderAt(<App />, "/app/systems");
    const table = await screen.findByRole("table", { name: "Systems" });
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(3);
    expect(within(table).getByRole("row", { name: /Web shop/ })).toHaveTextContent("approved");
    await userEvent.type(screen.getByRole("textbox", { name: /Search systems in Systems/ }), "crm");
    await waitFor(() => expect(within(table).getAllByRole("row")).toHaveLength(2));
  });

  it("sorts a column when its header is pressed", async () => {
    api("admin");
    renderAt(<App />, "/app/systems");
    const table = await screen.findByRole("table", { name: "Systems" });
    await userEvent.click(within(table).getByRole("button", { name: /System/ }));
    expect(within(table).getByRole("columnheader", { name: /System/ })).toHaveAttribute("aria-sort", "ascending");
    expect(within(table).getAllByRole("row")[1]).toHaveTextContent("CRM");
    await userEvent.click(within(table).getByRole("button", { name: /System/ }));
    expect(within(table).getAllByRole("row")[1]).toHaveTextContent("Web shop");
  });

  it("filters findings by severity through the API and shows the evidence of one", async () => {
    const fetchMock = api("analyst");
    renderAt(<App />, "/app/findings");
    await screen.findByText("Recipient not declared");
    await userEvent.selectOptions(screen.getByLabelText("Severity"), "high");
    await waitFor(() => expect(fetchMock.mock.calls.some((c) => String(c[0]).includes("severity=high"))).toBe(true));
    await userEvent.click(screen.getByText("Recipient not declared"));
    expect(await screen.findByText("Suggested fix")).toBeInTheDocument();
    expect(screen.getByText("har:cap.har")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Mark resolved" })).toBeInTheDocument();
  });

  it("gives a viewer the finding without the buttons that change it", async () => {
    api("viewer");
    renderAt(<App />, "/app/findings");
    await userEvent.click(await screen.findByText("Recipient not declared"));
    await screen.findByText("Suggested fix");
    expect(screen.queryByRole("button", { name: "Mark resolved" })).not.toBeInTheDocument();
  });
});

describe("command palette", () => {
  it("opens with Ctrl K, filters, and goes to the choice with Enter", async () => {
    api("admin");
    open("/app");
    await screen.findByText(/Welcome, Pat/);
    await userEvent.keyboard("{Control>}k{/Control}");
    const box = await screen.findByRole("combobox", { name: /Search pages/ });
    await userEvent.type(box, "find");
    expect(await screen.findByRole("option", { name: /Findings/ })).toBeInTheDocument();
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(screen.getAllByTestId("where").at(-1)).toHaveTextContent("/app/findings"));
  });

  it("finds a system by name and offers actions only to editors", async () => {
    api("admin");
    renderAt(<App />, "/app");
    await screen.findByText(/Welcome, Pat/);
    await userEvent.keyboard("{Control>}k{/Control}");
    expect(await screen.findByRole("option", { name: /Add a system/ })).toBeInTheDocument();
    await userEvent.type(screen.getByRole("combobox"), "crm");
    expect(await screen.findByRole("option", { name: /CRM/ })).toBeInTheDocument();
  });

  it("does not offer actions to a viewer", async () => {
    api("viewer");
    renderAt(<App />, "/app");
    await screen.findByText(/Welcome, Pat/);
    await userEvent.keyboard("{Control>}k{/Control}");
    await screen.findByRole("combobox");
    expect(screen.queryByRole("option", { name: /Add a system/ })).not.toBeInTheDocument();
  });
});

describe("top bar", () => {
  it("shows the unread count and the organizations of the person", async () => {
    api("admin");
    renderAt(<App />, "/app");
    expect(await screen.findByRole("button", { name: "Notifications, 1 unread" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /switch organization/ }));
    expect(await screen.findByRole("menuitem", { name: /Globex/ })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /Northbridge/ })).toHaveAttribute("aria-disabled", "true");
  });

  it("collapses the sidebar and remembers it", async () => {
    api("admin");
    renderAt(<App />, "/app");
    await screen.findByText(/Welcome, Pat/);
    await userEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toHaveAttribute("aria-pressed", "true");
    expect(localStorage.getItem("pl_nav_collapsed")).toBe("1");
    await userEvent.click(screen.getByRole("button", { name: "Expand sidebar" }));
  });
});

describe("add system wizard", () => {
  it("registers a system and moves to the evidence step", async () => {
    const fetchMock = api("analyst", false, {
      "/api/v1/systems/s9": { body: system("s9", "Helpdesk") },
      "/api/v1/systems/s9/evidence": { body: [] },
    });
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);
      if (url === "/api/v1/systems" && init?.method === "POST") {
        return new Response(JSON.stringify(system("s9", "Helpdesk")), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.startsWith("/api/v1/systems/s9/evidence"))
        return new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } });
      if (url.startsWith("/api/v1/systems/s9"))
        return new Response(JSON.stringify(system("s9", "Helpdesk")), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      if (url.startsWith("/api/v1/auth/me"))
        return new Response(JSON.stringify(user("analyst").body), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      if (url.startsWith("/api/v1/auth/organizations"))
        return new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } });
      if (
        url.startsWith("/api/v1/notifications") ||
        url.startsWith("/api/v1/systems") ||
        url.startsWith("/api/v1/activities")
      ) {
        return new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } });
      }
      return new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } });
    });
    renderAt(<App />, "/app/systems/new");
    await userEvent.type(await screen.findByLabelText("System name"), "Helpdesk");
    await userEvent.click(screen.getByRole("button", { name: "Register and continue" }));
    expect(await screen.findByRole("heading", { name: "2. Evidence" })).toBeInTheDocument();
    const call = fetchMock.mock.calls.find((c) => (c[1] as RequestInit | undefined)?.method === "POST");
    expect(JSON.parse((call?.[1] as RequestInit).body as string)).toMatchObject({ name: "Helpdesk" });
    expect(screen.getByRole("button", { name: /Attach technical evidence to continue/ })).toBeDisabled();
  });

  it("is closed to a viewer", async () => {
    api("viewer");
    renderAt(<App />, "/app/systems/new");
    expect(await screen.findByRole("alert")).toHaveTextContent("You do not have access");
  });
});

describe("structural accessibility", () => {
  it.each(["/app", "/app/systems", "/app/findings", "/app/vendors", "/app/requests"])(
    "%s has none of the structural violations axe checks",
    async (path) => {
      api("admin");
      const { container } = renderAt(<App />, path);
      await screen.findByRole("navigation", { name: "Console" });
      await waitFor(() => expect(screen.queryByRole("status", { name: "Loading" })).not.toBeInTheDocument());
      expect(await a11yViolations(container)).toEqual([]);
    },
  );
});

import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import App from "@/App";
import { renderAt } from "@/test/render";

vi.mock("@/app/charts/Chart", () => ({ default: () => <div data-testid="chart" /> }));

afterEach(() => vi.unstubAllGlobals());

type Handler = (init: RequestInit | undefined, url: string) => { status?: number; body?: unknown };

interface Mock {
  calls: { method: string; path: string; body: unknown }[];
  state: Record<string, unknown>;
}

/** A fetch that answers "METHOD /path" from a table and keeps every call, so a test can say what the
 *  wizard sent. State lives in `state`, so one answer can change after another call. */
function api(handlers: Record<string, Handler>): Mock {
  const mock: Mock = { calls: [], state: {} };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const path = url.split("?")[0] ?? url;
      const method = (init?.method ?? "GET").toUpperCase();
      const raw = init?.body;
      mock.calls.push({
        method,
        path,
        body:
          typeof raw === "string"
            ? (JSON.parse(raw) as unknown)
            : raw instanceof FormData
              ? Object.fromEntries(raw.entries())
              : raw,
      });
      const hit = handlers[`${method} ${path}`];
      if (!hit)
        return new Response(JSON.stringify({ detail: "Not found" }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        });
      const out = hit(init, url);
      return new Response(JSON.stringify(out.body ?? {}), {
        status: out.status ?? 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return mock;
}

const SYSTEM = {
  id: "s1",
  name: "Clinic portal",
  slug: "clinic-portal",
  description: null,
  owner_user_id: null,
  status: "CREATED",
  last_discovery_at: null,
};
const me = {
  user: { id: "u1", email: "a@x.test", full_name: "Avery Admin" },
  org_id: "o1",
  role: "analyst",
  is_host: false,
};
const job = (state: string, stages: Record<string, { state: string }>, id = "j1") => ({
  id,
  system_id: "s1",
  kind: "onboarding",
  state,
  stages,
  result: {},
  error: null,
  progress: {
    done: Object.values(stages).filter((s) => s.state === "succeeded").length,
    total: Object.keys(stages).length,
  },
  created_at: "2026-10-27T10:00:00Z",
  started_at: null,
  finished_at: state === "succeeded" ? "2026-10-27T10:00:05Z" : null,
});
const element = (id: string, name: string, over: Record<string, unknown> = {}) => ({
  id,
  name,
  path: null,
  data_type: null,
  pattern_class: null,
  category: "contact_email",
  special_category: false,
  special_category_label: null,
  confidence: 0.93,
  review_status: "pending",
  evidence_id: "ev1",
  source_kind: null,
  context: {},
  ...over,
});

const base: Record<string, Handler> = {
  "GET /api/v1/auth/me": () => ({ body: me }),
  "GET /api/v1/auth/organizations": () => ({ body: [] }),
  "GET /api/v1/systems/s1": () => ({ body: SYSTEM }),
  "GET /api/v1/notifications": () => ({ body: [] }),
  "GET /api/v1/systems": () => ({ body: [SYSTEM] }),
  "GET /api/v1/activities": () => ({ body: [] }),
  "GET /health": () => ({ body: { status: "ok" } }),
  "GET /api/v1/taxonomy": () => ({
    body: [
      { id: "contact_email", label: "Email address", definition: "", sensitivity: "low", special_category: false },
    ],
  }),
};

const open = () => renderAt(<App />, "/app/systems/new?system=s1", "*").container;
const goTo = async (name: RegExp) => userEvent.click(await screen.findByRole("button", { name }));

describe("Add System wizard", () => {
  it("starts with the registration form when no system is chosen", async () => {
    api({ ...base, "POST /api/v1/systems": () => ({ status: 201, body: SYSTEM }) });
    renderAt(<App />, "/app/systems/new");
    expect(await screen.findByRole("heading", { name: "1. Register" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^2\s?Evidence$/ })).toBeDisabled(); // nothing to work on yet
  });

  it("step 2: technical evidence is needed to continue, and a file is sent with its type", async () => {
    const mock = api({
      ...base,
      "GET /api/v1/systems/s1/evidence": () => ({
        body: mock.state.evidence ?? [
          {
            id: "e1",
            kind: "privacy_policy",
            filename: "policy.md",
            size_bytes: 10,
            checksum_sha256: "x",
            encrypted: true,
            created_at: "2026-10-27T10:00:00Z",
            system_id: "s1",
          },
        ],
      }),
      "POST /api/v1/systems/s1/evidence": () => {
        mock.state.evidence = [
          {
            id: "e1",
            kind: "privacy_policy",
            filename: "policy.md",
            size_bytes: 10,
            checksum_sha256: "x",
            encrypted: true,
            created_at: "2026-10-27T10:00:00Z",
            system_id: "s1",
          },
          {
            id: "e2",
            kind: "har",
            filename: "capture.har",
            size_bytes: 20,
            checksum_sha256: "y",
            encrypted: true,
            created_at: "2026-10-27T10:01:00Z",
            system_id: "s1",
          },
        ];
        return { status: 201, body: (mock.state.evidence as unknown[])[1] };
      },
    });
    open();
    expect(await screen.findByRole("heading", { name: "2. Evidence" })).toBeInTheDocument();
    const next = await screen.findByRole("button", { name: "Attach technical evidence to continue" });
    expect(next).toBeDisabled(); // a notice alone is not enough for discovery
    await userEvent.selectOptions(screen.getByLabelText("Type"), "har");
    await userEvent.upload(screen.getByLabelText("File"), new File(["{}"], "capture.har"));
    // jsdom does not count a file set by the test as the value of a required input, so the form is submitted directly
    fireEvent.submit(screen.getByRole("form", { name: "Attach a file" }));
    expect(await screen.findByRole("button", { name: "Continue to discovery" })).toBeEnabled();
    const sent = mock.calls.find((c) => c.method === "POST" && c.path.endsWith("/evidence"));
    expect(sent?.body).toMatchObject({ kind: "har" });
  });

  it("step 3: discovery and classification are queued as one job, progress is shown and the next step offered", async () => {
    const mock = api({
      ...base,
      "POST /api/v1/systems/s1/onboard": () => {
        mock.state.polls = 0;
        return { status: 202, body: job("queued", { discover: { state: "pending" }, classify: { state: "pending" } }) };
      },
      "GET /api/v1/jobs/j1": () => {
        mock.state.polls = Number(mock.state.polls ?? 0) + 1;
        return {
          body:
            Number(mock.state.polls) < 2
              ? job("running", { discover: { state: "succeeded" }, classify: { state: "running" } })
              : job("succeeded", { discover: { state: "succeeded" }, classify: { state: "succeeded" } }),
        };
      },
    });
    open();
    await goTo(/^3\s?Discovery$/);
    await userEvent.click(await screen.findByRole("button", { name: "Run discovery and classification" }));
    expect(mock.calls.find((c) => c.method === "POST" && c.path.endsWith("/onboard"))?.body).toEqual({
      stages: ["discover", "classify"],
    });
    expect(await screen.findByRole("progressbar", { name: "Progress" })).toBeInTheDocument();
    expect((await screen.findAllByText("Discovery")).length).toBeGreaterThan(0);
    expect(
      await screen.findByRole("button", { name: "Review the data elements" }, { timeout: 8000 }),
    ).toBeInTheDocument();
    expect(screen.getByText("Finished")).toBeInTheDocument();
  });

  it("step 3: a failed job says so and offers to run again", async () => {
    api({
      ...base,
      "POST /api/v1/systems/s1/onboard": () => ({
        status: 202,
        body: job("queued", { discover: { state: "pending" } }),
      }),
      "GET /api/v1/jobs/j1": () => ({
        body: { ...job("failed", { discover: { state: "failed" } }), error: "The capture could not be read" },
      }),
    });
    open();
    await goTo(/^3\s?Discovery$/);
    await userEvent.click(await screen.findByRole("button", { name: "Run discovery and classification" }));
    expect(await screen.findByText("The capture could not be read")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Run again" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Review the data elements" })).not.toBeInTheDocument();
  });

  it("step 4: elements are accepted or overridden and the evidence drawer shows the extractor output", async () => {
    const mock = api({
      ...base,
      "GET /api/v1/systems/s1/data-elements": () => ({
        body: [element("d1", "email"), element("d2", "dob", { category: null, confidence: null })],
      }),
      "PATCH /api/v1/systems/s1/data-elements/d1": () => ({
        body: element("d1", "email", { review_status: "accepted" }),
      }),
      "PATCH /api/v1/systems/s1/data-elements/d2": () => ({
        body: element("d2", "dob", { review_status: "overridden", category: "contact_email" }),
      }),
      "GET /api/v1/discovery-evidence/ev1": () => ({
        body: {
          id: "ev1",
          extractor: "rea",
          status: "ok",
          duration_ms: 812,
          command: "rea inspect",
          raw_output: { fields: ["email"] },
          raw_sha256: "a".repeat(64),
          raw_truncated: false,
          error: null,
          created_at: "2026-10-27T10:00:00Z",
        },
      }),
    });
    open();
    await goTo(/^4\s?Data elements$/);
    const table = await screen.findByRole("table", { name: "Data elements" });
    expect(within(table).getByText("93%")).toBeInTheDocument();
    expect(within(table).getByText("Not classified")).toBeInTheDocument();
    await userEvent.click(within(table).getAllByRole("button", { name: "Accept" })[0] as HTMLElement);
    await waitFor(() => expect(mock.calls.some((c) => c.method === "PATCH" && c.path.endsWith("/d1"))).toBe(true));
    expect(mock.calls.find((c) => c.path.endsWith("/d1") && c.method === "PATCH")?.body).toEqual({
      review_status: "accepted",
    });
    await userEvent.click(within(table).getAllByRole("button", { name: "Override" })[1] as HTMLElement);
    await userEvent.selectOptions(screen.getByLabelText("Category for dob"), "contact_email");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(mock.calls.find((c) => c.path.endsWith("/d2") && c.method === "PATCH")?.body).toEqual({
        review_status: "overridden",
        category: "contact_email",
      }),
    );
    await userEvent.click(within(table).getAllByRole("button", { name: "Evidence" })[0] as HTMLElement);
    const drawer = await screen.findByRole("dialog", { name: "Evidence" });
    expect(await within(drawer).findByText("rea inspect")).toBeInTheDocument();
    expect(within(drawer).getByText(/"fields"/)).toBeInTheDocument();
  });

  it("step 5: the comparison is queued and its findings are listed with their fix", async () => {
    const mock = api({
      ...base,
      "POST /api/v1/systems/s1/onboard": () => ({ status: 202, body: job("queued", { fuse: { state: "pending" } }) }),
      "GET /api/v1/jobs/j1": () => ({ body: job("succeeded", { fuse: { state: "succeeded" } }) }),
      "GET /api/v1/findings": () => ({
        body: [
          {
            id: "f1",
            title: "Recipient not declared",
            severity: "high",
            status: "open",
            type: "undeclared_recipient",
            description: "",
            suggested_fix: "Declare the vendor",
            evidence_refs: [],
            system_id: "s1",
            activity_id: null,
            created_at: "2026-10-27T10:00:00Z",
          },
        ],
      }),
    });
    open();
    await goTo(/^5\s?Comparison$/);
    await userEvent.click(await screen.findByRole("button", { name: "Compare the sources" }));
    expect(mock.calls.find((c) => c.path.endsWith("/onboard"))?.body).toEqual({ stages: ["fuse"] });
    expect(await screen.findByText("Recipient not declared")).toBeInTheDocument();
    expect(screen.getByText(/Declare the vendor/)).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Findings (1)" })).toBeInTheDocument();
  });

  it("step 6: the record appears when its job finishes, with missing fields marked", async () => {
    const record = {
      id: "a1",
      name: "Clinic portal",
      status: "draft",
      system_ids: ["s1"],
      purposes: [],
      data_subjects: ["patients"],
      data_categories: ["health_data"],
      recipients: [],
      transfers: [],
      retention: null,
      security_measures: null,
      lawful_basis: null,
      special_category_condition: null,
      next_review_date: null,
      citations: {},
      missing_fields: ["purposes", "lawful_basis"],
      current_version: 1,
      special_categories: [],
      summary: "",
    };
    const mock = api({
      ...base,
      "POST /api/v1/systems/s1/onboard": () => {
        mock.state.done = true;
        return { status: 202, body: job("queued", { record: { state: "pending" } }) };
      },
      "GET /api/v1/jobs/j1": () => ({ body: job("succeeded", { record: { state: "succeeded" } }) }),
      "GET /api/v1/activities": () => ({ body: mock.state.done ? [record] : [] }),
    });
    open();
    await goTo(/^6\s?Record draft$/);
    await userEvent.click(await screen.findByRole("button", { name: "Generate the record" }));
    expect(mock.calls.find((c) => c.path.endsWith("/onboard"))?.body).toEqual({ stages: ["record"] });
    expect(await screen.findByText("Categories of personal data")).toBeInTheDocument();
    expect(screen.getAllByText("Missing").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByRole("button", { name: "Continue to submit" })).toBeInTheDocument();
  });

  it("step 7: a record with missing fields cannot be submitted until they are filled in", async () => {
    const incomplete = {
      id: "a1",
      name: "Clinic portal",
      status: "draft",
      system_ids: ["s1"],
      purposes: [],
      data_subjects: [],
      data_categories: [],
      recipients: [],
      transfers: [],
      retention: null,
      security_measures: null,
      lawful_basis: null,
      special_category_condition: null,
      next_review_date: null,
      citations: {},
      missing_fields: ["purposes", "lawful_basis"],
      current_version: 1,
      special_categories: [],
      summary: "",
    };
    const complete = {
      ...incomplete,
      purposes: ["Appointment management"],
      lawful_basis: "contract",
      missing_fields: [],
    };
    const mock = api({
      ...base,
      "GET /api/v1/activities": () => ({ body: [mock.state.saved ? complete : incomplete] }),
      "PATCH /api/v1/activities/a1": () => {
        mock.state.saved = true;
        return { body: complete };
      },
      "POST /api/v1/activities/a1/submit": () => ({ body: { ...complete, status: "awaiting_review" } }),
      "GET /api/v1/activities/a1": () => ({ body: { ...complete, status: "awaiting_review" } }),
      "GET /api/v1/activities/a1/versions": () => ({ body: [] }),
    });
    open();
    await goTo(/^7\s?Submit$/);
    expect(await screen.findByRole("heading", { name: "Complete the missing fields" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Submit for approval" })).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Purposes (one per line)"), "Appointment management");
    await userEvent.type(screen.getByLabelText("Lawful basis"), "contract");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Submit for approval" })).toBeEnabled());
    expect(mock.calls.find((c) => c.method === "PATCH" && c.path.endsWith("/a1"))?.body).toMatchObject({
      purposes: ["Appointment management"],
      lawful_basis: "contract",
    });
    await userEvent.click(screen.getByRole("button", { name: "Submit for approval" }));
    await waitFor(() => expect(mock.calls.some((c) => c.method === "POST" && c.path.endsWith("/submit"))).toBe(true));
  });
});

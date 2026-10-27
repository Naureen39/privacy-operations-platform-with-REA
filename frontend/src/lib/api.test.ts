import { api, ApiError, landingPath, submitLead } from "./api";
import { mockFetch } from "@/test/render";

afterEach(() => {
  vi.unstubAllGlobals();
  document.cookie = "pl_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
});

describe("api client", () => {
  it("sends the session cookie and no CSRF header on a read", async () => {
    const fetchMock = mockFetch({ "/api/v1/x": { body: { ok: true } } });
    await expect(api.get("/api/v1/x")).resolves.toEqual({ ok: true });
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(init.credentials).toBe("include");
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBeUndefined();
  });

  it("sends the CSRF token from the cookie on a change", async () => {
    document.cookie = "pl_csrf=abc123";
    const fetchMock = mockFetch({ "/api/v1/x": { body: {} } });
    await api.post("/api/v1/x", { a: 1 });
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBe("abc123");
    expect(init.body).toBe('{"a":1}');
  });

  it("turns the error envelope into an ApiError with the request id", async () => {
    mockFetch({
      "/api/v1/x": { status: 409, body: { detail: "x", error: { message: "Conflict here", request_id: "req-1" } } },
    });
    const error = await api.get("/api/v1/x").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(409);
    expect((error as ApiError).message).toBe("Conflict here");
    expect((error as ApiError).requestId).toBe("req-1");
  });

  it("reports an unreachable service as status 0", async () => {
    mockFetch({});
    const error = (await api.get("/api/v1/x").catch((e: unknown) => e)) as ApiError;
    expect(error.status).toBe(0);
    expect(error.message).toMatch(/cannot be reached/);
  });

  it("posts a lead to the public endpoint", async () => {
    const fetchMock = mockFetch({ "/api/v1/public/leads": { status: 202, body: { status: "accepted" } } });
    await submitLead({ kind: "contact", name: "Alex Example", email: "alex@example.test" });
    expect(JSON.parse((fetchMock.mock.calls[0]?.[1] as RequestInit).body as string)).toEqual({
      kind: "contact",
      name: "Alex Example",
      email: "alex@example.test",
    });
  });
});

describe("landingPath", () => {
  it("sends each role to a console area", () => {
    expect(landingPath("admin")).toBe("/app");
    expect(landingPath("analyst")).toBe("/app/systems");
    expect(landingPath("system_owner")).toBe("/app/systems");
    expect(landingPath("viewer")).toBe("/app/records");
  });
});

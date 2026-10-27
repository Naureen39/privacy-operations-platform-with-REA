/** The API client: JSON over fetch, the session cookie, and the CSRF header for changes. */

export class ApiError extends Error {
  readonly status: number;
  readonly requestId: string | null;

  constructor(message: string, status: number, requestId: string | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.requestId = requestId;
  }
}

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

function csrfToken(): string {
  const match = document.cookie.split("; ").find((c) => c.startsWith("pl_csrf="));
  return match ? decodeURIComponent(match.slice("pl_csrf=".length)) : "";
}

interface ErrorBody {
  detail?: unknown;
  error?: { message?: string; request_id?: string };
}

function messageOf(body: ErrorBody | null, fallback: string): string {
  if (body?.error?.message) return body.error.message;
  if (typeof body?.detail === "string") return body.detail;
  return fallback;
}

export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-CSRF-Token"] = csrfToken();
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      method,
      headers,
      credentials: "include",
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError("The service cannot be reached right now. Please try again shortly.", 0);
  }
  if (!response.ok) {
    let parsed: ErrorBody | null = null;
    try {
      parsed = (await response.json()) as ErrorBody;
    } catch {
      parsed = null;
    }
    throw new ApiError(
      messageOf(parsed, `The request failed (${response.status})`),
      response.status,
      parsed?.error?.request_id ?? response.headers.get("X-Request-ID"),
    );
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
};

export type Role = "admin" | "analyst" | "system_owner" | "viewer";

export interface Session {
  user: { id: string; email: string; full_name: string };
  org_id: string;
  role: Role;
  memberships: { org_id: string; role: Role }[];
}

export interface PublicMetrics {
  as_of: string | null;
  accounts: number;
  systems: number;
  requests: number;
  cache_hits: number;
  failovers: number;
  regulation_passages: number;
  simulated: boolean;
  note: string;
}

export interface LeadInput {
  kind: "contact" | "demo_request";
  name: string;
  email: string;
  company?: string;
  message?: string;
  website?: string;
}

export const login = (email: string, password: string) => api.post<Session>("/api/v1/auth/login", { email, password });

export const submitLead = (lead: LeadInput) => api.post<{ status: string }>("/api/v1/public/leads", lead);

/** Where each role lands after signing in. The console itself is built in the next phase. */
export function landingPath(role: Role): string {
  switch (role) {
    case "admin":
      return "/app";
    case "analyst":
      return "/app/systems";
    case "system_owner":
      return "/app/systems";
    default:
      return "/app/records";
  }
}

import type { Role } from "@/lib/api";

/** What each role may do in the interface. The API enforces the same rules (a test walks every
 *  route for every role); this only decides what to show. */

export type Capability =
  | "write" // create and edit systems, run discovery, edit records, assessments and requests
  | "approve" // approve or reject records and assessments, publish records
  | "upload" // attach evidence
  | "admin" // settings, team, audit log, billing
  | "export";

const table: Record<Capability, readonly Role[]> = {
  write: ["admin", "analyst"],
  approve: ["admin"],
  upload: ["admin", "analyst", "system_owner"],
  admin: ["admin"],
  export: ["admin", "analyst", "viewer"],
};

export function can(role: Role | undefined, capability: Capability): boolean {
  return role !== undefined && table[capability].includes(role);
}

export const ROLE_LABEL: Record<Role, string> = {
  admin: "Administrator",
  analyst: "Analyst",
  system_owner: "System owner",
  viewer: "Viewer",
};

export interface NavItem {
  label: string;
  to: string;
  roles: readonly Role[];
  /** Only for the administrators of the host organization (platform wide figures). */
  host?: boolean;
  group: "Work" | "Compliance" | "Insight" | "Organization";
}

const everyone: readonly Role[] = ["admin", "analyst", "system_owner", "viewer"];
const staff: readonly Role[] = ["admin", "analyst", "viewer"];

export const NAV: NavItem[] = [
  { label: "Overview", to: "/app", roles: everyone, group: "Work" },
  { label: "Systems", to: "/app/systems", roles: everyone, group: "Work" },
  { label: "Findings", to: "/app/findings", roles: everyone, group: "Work" },
  { label: "Records of processing", to: "/app/records", roles: everyone, group: "Compliance" },
  { label: "Impact assessments", to: "/app/assessments", roles: staff, group: "Compliance" },
  { label: "Access requests", to: "/app/requests", roles: staff, group: "Compliance" },
  { label: "Vendors and transfers", to: "/app/vendors", roles: everyone, group: "Compliance" },
  { label: "Regulation library", to: "/app/library", roles: everyone, group: "Compliance" },
  { label: "Analytics", to: "/app/analytics", roles: staff, group: "Insight" },
  { label: "Revenue", to: "/app/revenue", roles: ["admin"], host: true, group: "Insight" },
  { label: "Billing", to: "/app/billing", roles: ["admin"], group: "Organization" },
  { label: "Team", to: "/app/team", roles: ["admin"], group: "Organization" },
  { label: "Audit log", to: "/app/audit", roles: ["admin", "viewer"], group: "Organization" },
  { label: "Settings", to: "/app/settings", roles: ["admin"], group: "Organization" },
];

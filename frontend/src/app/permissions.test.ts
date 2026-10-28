import { can, NAV } from "./permissions";
import type { Role } from "@/lib/api";

const visible = (role: Role, host = false) =>
  NAV.filter((n) => n.roles.includes(role) && (!n.host || host)).map((n) => n.label);

describe("what each role may do", () => {
  it("lets only editors write and only administrators approve", () => {
    expect(["admin", "analyst", "system_owner", "viewer"].map((r) => can(r as Role, "write"))).toEqual([
      true,
      true,
      false,
      false,
    ]);
    expect(["admin", "analyst", "system_owner", "viewer"].map((r) => can(r as Role, "approve"))).toEqual([
      true,
      false,
      false,
      false,
    ]);
    expect(can("system_owner", "upload")).toBe(true);
    expect(can("viewer", "upload")).toBe(false);
    expect(can("viewer", "export")).toBe(true);
    expect(can(undefined, "write")).toBe(false);
  });
});

describe("the menu", () => {
  it("shows an administrator everything except platform revenue outside the host organization", () => {
    const labels = visible("admin");
    expect(labels).toContain("Billing");
    expect(labels).toContain("Team");
    expect(labels).toContain("Settings");
    expect(labels).not.toContain("Revenue");
    expect(visible("admin", true)).toContain("Revenue");
  });

  it("keeps an analyst out of the organization settings", () => {
    const labels = visible("analyst");
    expect(labels).toEqual(
      expect.arrayContaining(["Systems", "Findings", "Impact assessments", "Access requests", "Analytics"]),
    );
    for (const hidden of ["Billing", "Team", "Settings", "Audit log", "Revenue"]) expect(labels).not.toContain(hidden);
  });

  it("gives a viewer read access including the audit log, and nothing administrative", () => {
    const labels = visible("viewer");
    expect(labels).toContain("Audit log");
    expect(labels).toContain("Analytics");
    for (const hidden of ["Billing", "Team", "Settings"]) expect(labels).not.toContain(hidden);
  });

  it("gives a system owner only the systems, findings, records, vendors and library", () => {
    expect(visible("system_owner")).toEqual([
      "Overview",
      "Systems",
      "Findings",
      "Records of processing",
      "Vendors and transfers",
      "Regulation library",
    ]);
  });

  it("points every item at the console", () => {
    expect(NAV.every((n) => n.to.startsWith("/app"))).toBe(true);
  });
});

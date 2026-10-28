import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { api, ApiError, type Role } from "@/lib/api";
import { can, type Capability } from "./permissions";
import type { OrganizationChoice } from "./types";

export interface Me {
  user: { id: string; email: string; full_name: string };
  org_id: string;
  role: Role;
  is_host: boolean;
}

interface SessionValue {
  me: Me;
  organizations: OrganizationChoice[];
  can: (capability: Capability) => boolean;
  signOut: () => Promise<void>;
  switchOrganization: (orgId: string) => Promise<void>;
}

const SessionContext = createContext<SessionValue | null>(null);

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside <RequireSession>");
  return value;
}

/** Loads the signed in person and gates everything below on it. Without a session the visitor is
 *  sent to the sign in page; the page they wanted is remembered. */
export function RequireSession({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const location = useLocation();
  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: () => api.get<Me>("/api/v1/auth/me"),
    retry: false,
    staleTime: 60_000,
  });
  const orgsQuery = useQuery({
    queryKey: ["organizations"],
    queryFn: () => api.get<OrganizationChoice[]>("/api/v1/auth/organizations"),
    enabled: meQuery.isSuccess,
    staleTime: 300_000,
  });

  if (meQuery.isLoading) {
    return (
      <div className="grid min-h-screen place-items-center" role="status" aria-label="Loading your session">
        <div className="size-8 animate-spin rounded-full border-4 border-border border-t-primary" />
      </div>
    );
  }
  if (meQuery.error instanceof ApiError && meQuery.error.status === 401) {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }
  if (!meQuery.data) {
    return (
      <p role="alert" className="p-8">
        The console could not be loaded. Please try again.
      </p>
    );
  }
  const me = meQuery.data;
  const value: SessionValue = {
    me,
    organizations: orgsQuery.data ?? [],
    can: (capability) => can(me.role, capability),
    signOut: async () => {
      await api.post("/api/v1/auth/logout").catch(() => undefined);
      client.clear();
      window.location.assign("/login");
    },
    switchOrganization: async (orgId) => {
      await api.post("/api/v1/auth/switch", { org_id: orgId });
      client.clear();
      window.location.assign("/app");
    },
  };
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

/** A page that only some roles may open. Others see a plain explanation, not an empty screen. */
export function RequireRole({
  roles,
  host = false,
  children,
}: {
  roles: readonly Role[];
  host?: boolean;
  children: ReactNode;
}) {
  const { me } = useSession();
  const allowed = roles.includes(me.role) && (!host || me.is_host);
  if (allowed) return <>{children}</>;
  return (
    <div role="alert" className="mx-auto max-w-lg py-20 text-center">
      <h1 className="text-2xl">You do not have access to this page</h1>
      <p className="mt-2 text-muted-foreground">
        Your role does not include it. Ask an administrator of your organization if you need it.
      </p>
    </div>
  );
}

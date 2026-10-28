import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bell,
  Building2,
  Check,
  ChevronsLeft,
  ChevronsRight,
  LogOut,
  Menu,
  Search,
  UserRound,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Logo, LogoMark } from "@/site/art/Logo";
import { NAV, ROLE_LABEL } from "../permissions";
import { useSession } from "../session";
import { ErrorBoundary, formatDateTime } from "../ui/kit";
import { Breadcrumbs } from "../ui/parts";
import { useToast } from "../ui/toast";
import { CommandPalette } from "./CommandPalette";
import { useNotifications } from "../hooks/data";

function useVisibleNav() {
  const { me } = useSession();
  return NAV.filter((n) => n.roles.includes(me.role) && (!n.host || me.is_host));
}

function SideNav({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  const items = useVisibleNav();
  const groups = ["Work", "Compliance", "Insight", "Organization"] as const;
  return (
    <nav aria-label="Console" className="flex-1 space-y-5 overflow-y-auto px-2 py-4">
      {groups.map((group) => {
        const inGroup = items.filter((i) => i.group === group);
        if (inGroup.length === 0) return null;
        return (
          <div key={group}>
            {!collapsed && (
              <p className="mb-1 px-3 text-xs font-semibold uppercase tracking-wider text-white/60">{group}</p>
            )}
            <ul className="space-y-0.5">
              {inGroup.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    end={item.to === "/app"}
                    onClick={onNavigate}
                    title={collapsed ? item.label : undefined}
                    className={({ isActive }) =>
                      cn(
                        "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-white/85 hover:bg-white/10",
                        isActive && "bg-white/15 text-white",
                        collapsed && "justify-center px-2",
                      )
                    }
                  >
                    <span aria-hidden="true" className="size-1.5 shrink-0 rounded-full bg-accent" />
                    <span className={cn(collapsed && "sr-only")}>{item.label}</span>
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </nav>
  );
}

function NotificationsMenu() {
  const { data } = useNotifications();
  const client = useQueryClient();
  const navigate = useNavigate();
  const unread = (data ?? []).filter((n) => !n.read_at);
  // The visible count and the accessible name must match, so both use the same text.
  const badge = unread.length > 9 ? "9+" : String(unread.length);
  const open = (entityType: string | null | undefined, entityId: string | null | undefined) => {
    const base: Record<string, string> = {
      processing_activity: "/app/records",
      dpia: "/app/assessments",
      access_request: "/app/requests",
      system: "/app/systems",
      finding: "/app/findings",
    };
    const path = entityType ? base[entityType] : undefined;
    navigate(path ? (entityId && entityType !== "finding" ? `${path}/${entityId}` : path) : "/app");
  };
  return (
    <Dropdown.Root>
      <Dropdown.Trigger asChild>
        <Button variant="ghost" size="icon" aria-label={`Notifications, ${badge} unread`} className="relative">
          <Bell aria-hidden="true" className="size-5" />
          {unread.length > 0 && (
            <span className="absolute right-1 top-1 grid size-4 place-items-center rounded-full bg-danger text-[10px] font-bold text-white">
              {badge}
            </span>
          )}
        </Button>
      </Dropdown.Trigger>
      <Dropdown.Portal>
        <Dropdown.Content
          align="end"
          sideOffset={8}
          className="z-50 max-h-[70vh] w-[min(22rem,calc(100vw-2rem))] overflow-y-auto rounded-lg border border-border bg-background p-2 shadow-pop"
        >
          <div className="flex items-center justify-between px-2 py-1.5">
            <p className="text-sm font-semibold text-navy dark:text-foreground">Notifications</p>
            {unread.length > 0 && (
              <button
                type="button"
                className="text-xs font-semibold text-primary hover:underline"
                onClick={async () => {
                  await api.post("/api/v1/notifications/read-all");
                  await client.invalidateQueries({ queryKey: ["notifications"] });
                }}
              >
                Mark all read
              </button>
            )}
          </div>
          {(data ?? []).length === 0 ? (
            <p className="px-2 py-6 text-center text-sm text-muted-foreground">Nothing yet.</p>
          ) : (
            (data ?? []).slice(0, 12).map((n) => (
              <Dropdown.Item
                key={n.id}
                onSelect={async () => {
                  if (!n.read_at) {
                    await api.post(`/api/v1/notifications/${n.id}/read`);
                    await client.invalidateQueries({ queryKey: ["notifications"] });
                  }
                  open(n.entity_type, n.entity_id);
                }}
                className="cursor-pointer rounded-md px-2 py-2 outline-none data-[highlighted]:bg-muted"
              >
                <p className={cn("text-sm", !n.read_at && "font-semibold")}>{n.title}</p>
                <p className="text-xs text-muted-foreground">{formatDateTime(n.created_at)}</p>
              </Dropdown.Item>
            ))
          )}
        </Dropdown.Content>
      </Dropdown.Portal>
    </Dropdown.Root>
  );
}

function OrgSwitcher() {
  const { me, organizations, switchOrganization } = useSession();
  const toast = useToast();
  const current = organizations.find((o) => o.current);
  return (
    <Dropdown.Root>
      <Dropdown.Trigger asChild>
        <Button
          variant="secondary"
          size="sm"
          className="max-w-[14rem]"
          aria-label={`${current?.name ?? "Organization"}, switch organization`}
        >
          <Building2 aria-hidden="true" />
          <span className="truncate">{current?.name ?? "Organization"}</span>
        </Button>
      </Dropdown.Trigger>
      <Dropdown.Portal>
        <Dropdown.Content
          align="start"
          sideOffset={8}
          className="z-50 w-64 rounded-lg border border-border bg-background p-2 shadow-pop"
        >
          <p className="px-2 py-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Your organizations
          </p>
          {organizations.map((o) => (
            <Dropdown.Item
              key={o.org_id}
              disabled={o.current}
              onSelect={() => switchOrganization(o.org_id).catch(() => toast.error("Could not switch organization"))}
              className="flex cursor-pointer items-center justify-between gap-2 rounded-md px-2 py-2 text-sm outline-none data-[disabled]:cursor-default data-[highlighted]:bg-muted"
            >
              <span className="min-w-0">
                <span className="block truncate font-medium">{o.name}</span>
                <span className="block text-xs text-muted-foreground">{ROLE_LABEL[o.role]}</span>
              </span>
              {o.current && <Check aria-label="Current" className="size-4 text-success" />}
            </Dropdown.Item>
          ))}
          {organizations.length <= 1 && (
            <p className="px-2 py-2 text-xs text-muted-foreground">You belong to one organization ({me.role}).</p>
          )}
        </Dropdown.Content>
      </Dropdown.Portal>
    </Dropdown.Root>
  );
}

function UserMenu() {
  const { me, signOut } = useSession();
  return (
    <Dropdown.Root>
      <Dropdown.Trigger asChild>
        <Button variant="ghost" size="icon" aria-label="User menu">
          <UserRound aria-hidden="true" className="size-5" />
        </Button>
      </Dropdown.Trigger>
      <Dropdown.Portal>
        <Dropdown.Content
          align="end"
          sideOffset={8}
          className="z-50 w-64 rounded-lg border border-border bg-background p-2 shadow-pop"
        >
          <div className="px-2 py-2">
            <p className="truncate text-sm font-semibold text-navy dark:text-foreground">{me.user.full_name}</p>
            <p className="truncate text-xs text-muted-foreground">{me.user.email}</p>
            <p className="mt-1 text-xs font-semibold text-primary">{ROLE_LABEL[me.role]}</p>
          </div>
          <Dropdown.Separator className="my-1 h-px bg-border" />
          <Dropdown.Item
            onSelect={() => void signOut()}
            className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-sm outline-none data-[highlighted]:bg-muted"
          >
            <LogOut aria-hidden="true" className="size-4" /> Sign out
          </Dropdown.Item>
        </Dropdown.Content>
      </Dropdown.Portal>
    </Dropdown.Root>
  );
}

function Hint({ icon: Icon, children }: { icon: LucideIcon; children: string }) {
  return (
    <span className="hidden items-center gap-2 text-sm text-muted-foreground md:inline-flex">
      <Icon aria-hidden="true" className="size-4" />
      {children}
    </span>
  );
}

export function ConsoleLayout() {
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("pl_nav_collapsed") === "1");
  const [drawer, setDrawer] = useState(false);
  const [palette, setPalette] = useState(false);
  const { pathname } = useLocation();
  useEffect(() => {
    try {
      localStorage.setItem("pl_nav_collapsed", collapsed ? "1" : "0");
    } catch {
      /* storage can be unavailable; the preference is only a convenience */
    }
  }, [collapsed]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette((p) => !p);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const health = useQuery({
    queryKey: ["health"],
    queryFn: () => api.get<{ status: string }>("/health"),
    retry: 0,
    refetchInterval: 60_000,
  });

  return (
    <div className="flex min-h-screen bg-surface">
      <a
        href="#console-main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[70] focus:rounded-md focus:bg-primary focus:px-4 focus:py-2 focus:text-primary-foreground"
      >
        Skip to content
      </a>
      <aside
        className={cn(
          "sticky top-0 hidden h-screen shrink-0 flex-col bg-navy transition-[width] lg:flex print:hidden",
          collapsed ? "w-16" : "w-64",
        )}
      >
        <div className={cn("flex h-16 items-center border-b border-white/10 px-4", collapsed && "justify-center px-2")}>
          <Link to="/app" aria-label="ProcessLedger console home">
            {collapsed ? <LogoMark /> : <Logo inverse />}
          </Link>
        </div>
        <SideNav collapsed={collapsed} />
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-pressed={collapsed}
          className="flex h-12 items-center justify-center border-t border-white/10 text-white/80 hover:bg-white/10"
        >
          {collapsed ? (
            <ChevronsRight aria-hidden="true" className="size-5" />
          ) : (
            <ChevronsLeft aria-hidden="true" className="size-5" />
          )}
        </button>
      </aside>
      <Sheet open={drawer} onOpenChange={setDrawer}>
        <SheetContent className="left-0 right-auto bg-navy p-0 text-white">
          <SheetTitle className="sr-only">Console menu</SheetTitle>
          <SheetDescription className="sr-only">Navigation</SheetDescription>
          <div className="flex h-16 items-center border-b border-white/10 px-4">
            <Logo inverse />
          </div>
          <SideNav collapsed={false} onNavigate={() => setDrawer(false)} />
        </SheetContent>
      </Sheet>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-16 items-center gap-2 border-b border-border bg-background px-3 md:px-6 print:hidden">
          <Button
            variant="ghost"
            size="icon"
            className="lg:hidden"
            aria-label="Open menu"
            onClick={() => setDrawer(true)}
          >
            <Menu aria-hidden="true" className="size-5" />
          </Button>
          <OrgSwitcher />
          <button
            type="button"
            onClick={() => setPalette(true)}
            className="ml-auto flex h-10 min-w-0 items-center gap-2 rounded-md border border-input px-3 text-sm text-muted-foreground hover:bg-muted md:w-72"
          >
            <Search aria-hidden="true" className="size-4 shrink-0" />
            <span className="hidden truncate md:inline">Search or jump to</span>
            <span className="sr-only md:hidden">Search</span>
            <kbd className="ml-auto hidden rounded border border-border px-1.5 text-xs md:inline">Ctrl K</kbd>
          </button>
          <Hint icon={health.isError ? Bell : Check}>{health.isError ? "API unreachable" : "API online"}</Hint>
          <NotificationsMenu />
          <UserMenu />
        </header>
        <main id="console-main" tabIndex={-1} className="flex-1 px-3 py-6 outline-none md:px-8">
          <Breadcrumbs />
          <ErrorBoundary resetKey={pathname}>
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>
      <CommandPalette open={palette} onOpenChange={setPalette} />
    </div>
  );
}

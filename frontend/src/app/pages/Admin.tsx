import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, api } from "@/lib/api";
import { usePageMeta } from "@/lib/queries";
import { ROLE_LABEL } from "../permissions";
import { useAction, useAudit, useInvoices } from "../hooks/data";
import { useSession } from "../session";
import { DataTable } from "../ui/DataTable";
import { ErrorNote, formatDate, formatDateTime, Money, Skeleton, StatusBadge } from "../ui/kit";
import { ConfirmDialog, PageHeader, Panel, Select, Stat } from "../ui/parts";
import type {
  AuditEntry,
  Invoice,
  InvoiceSummary,
  LlmUsage,
  OrgSettings,
  Plan,
  Subscription,
  TeamMember,
  Usage,
} from "../types";
import type { Role } from "@/lib/api";

// -- Billing --------------------------------------------------------------------------------------

export function Billing() {
  usePageMeta("Billing");
  const subscription = useQuery({
    queryKey: ["subscription"],
    queryFn: () => api.get<Subscription>("/api/v1/billing/subscription"),
    retry: false,
  });
  const usage = useQuery({ queryKey: ["usage"], queryFn: () => api.get<Usage>("/api/v1/billing/usage") });
  const plans = useQuery({ queryKey: ["plans"], queryFn: () => api.get<Plan[]>("/api/v1/billing/plans") });
  const invoices = useInvoices();
  const [open, setOpen] = useState<Invoice | null>(null);
  const change = useAction({
    run: (plan: string) => api.put<Subscription>("/api/v1/billing/subscription", { plan }),
    success: "Plan changed",
    invalidate: [["subscription"], ["usage"]],
  });
  const pay = useAction({
    run: (id: string) => api.post<Invoice>(`/api/v1/billing/invoices/${id}/pay`),
    success: "Marked as paid",
    invalidate: [["invoices"]],
    onDone: setOpen,
  });
  const show = async (id: string) => setOpen(await api.get<Invoice>(`/api/v1/billing/invoices/${id}`));
  const u = usage.data;
  return (
    <>
      <PageHeader
        title="Billing"
        description="Plan, usage this month and invoices. Billing is simulated: no payment is taken."
      />
      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Plan">
          {subscription.isLoading ? (
            <Skeleton className="h-24" />
          ) : subscription.isError ? (
            <p className="text-muted-foreground">No subscription yet. Choose a plan below.</p>
          ) : (
            <p>
              <strong>{subscription.data?.plan_name}</strong> since {formatDate(subscription.data?.started_at)},{" "}
              <Money cents={subscription.data?.base_fee_cents ?? 0} /> a month.
            </p>
          )}
          <ul className="mt-4 space-y-2">
            {(plans.data ?? []).map((p) => (
              <li
                key={p.code}
                className="flex items-center justify-between gap-3 rounded-md border border-border p-3 text-sm"
              >
                <span>
                  <strong>{p.name}</strong>, <Money cents={p.monthly_fee_cents} /> a month, {p.included_systems}{" "}
                  systems, {p.included_requests} requests
                </span>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={subscription.data?.plan === p.code || change.isPending}
                  onClick={() => change.mutate(p.code)}
                >
                  {subscription.data?.plan === p.code ? "Current" : "Choose"}
                </Button>
              </li>
            ))}
          </ul>
        </Panel>
        <Panel title="Usage this month">
          {!u ? (
            <Skeleton className="h-24" />
          ) : (
            <dl className="grid grid-cols-2 gap-3">
              <Stat
                label="Active systems"
                value={u.active_systems}
                hint={u.included_systems ? `${u.included_systems} included` : undefined}
              />
              <Stat
                label="Requests handled"
                value={u.requests}
                hint={u.included_requests ? `${u.included_requests} included` : undefined}
              />
              <Stat label="Assessments drafted" value={u.assessments} />
              <Stat
                label="Projected invoice"
                value={u.projected_cents === null ? "None" : <Money cents={u.projected_cents} />}
              />
            </dl>
          )}
        </Panel>
      </div>
      <Panel title="Invoices" className="mt-6">
        <DataTable<InvoiceSummary>
          data={invoices.data ?? []}
          loading={invoices.isLoading}
          caption="Invoices"
          searchPlaceholder="Search invoices"
          onRowClick={(i) => void show(i.id)}
          empty={{ title: "No invoices yet", text: "The first invoice is created after a full month on a plan." }}
          columns={[
            { accessorKey: "number", header: "Number" },
            {
              accessorKey: "period_start",
              header: "Period",
              cell: ({ row }) => `${formatDate(row.original.period_start)} to ${formatDate(row.original.period_end)}`,
            },
            { accessorKey: "total_cents", header: "Total", cell: (c) => <Money cents={Number(c.getValue())} /> },
            { accessorKey: "status", header: "Status", cell: (c) => <StatusBadge value={String(c.getValue())} /> },
          ]}
        />
        {open && (
          <div className="mt-4 rounded-lg border border-border p-4" aria-label={`Invoice ${open.number}`}>
            <div className="flex items-center justify-between">
              <h3 className="text-base">{open.number}</h3>
              <StatusBadge value={open.status} />
            </div>
            <table className="mt-3 w-full text-sm">
              <caption className="sr-only">Invoice lines</caption>
              <thead>
                <tr className="text-left text-muted-foreground">
                  <th scope="col" className="py-1">
                    Description
                  </th>
                  <th scope="col" className="py-1">
                    Quantity
                  </th>
                  <th scope="col" className="py-1 text-right">
                    Amount
                  </th>
                </tr>
              </thead>
              <tbody>
                {open.lines.map((l, i) => (
                  <tr key={i} className="border-t border-border">
                    <td className="py-1">{l.description}</td>
                    <td className="py-1">{l.quantity}</td>
                    <td className="py-1 text-right">
                      <Money cents={l.amount_cents} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-right font-semibold">
              Total <Money cents={open.total_cents} />
            </p>
            {open.status === "open" || open.status === "overdue" ? (
              <Button className="mt-2" size="sm" onClick={() => pay.mutate(open.id)}>
                Record a payment
              </Button>
            ) : null}
          </div>
        )}
      </Panel>
    </>
  );
}

// -- Team -----------------------------------------------------------------------------------------

const ROLES: Role[] = ["admin", "analyst", "system_owner", "viewer"];

export function Team() {
  usePageMeta("Team");
  const team = useQuery({ queryKey: ["team"], queryFn: () => api.get<TeamMember[]>("/api/v1/team", { limit: 200 }) });
  const change = useAction({
    run: (input: { id: string; role: Role }) => api.patch<TeamMember>(`/api/v1/team/${input.id}`, { role: input.role }),
    success: "Role changed",
    invalidate: [["team"]],
  });
  const remove = useAction({
    run: (id: string) => api.del(`/api/v1/team/${id}`),
    success: "Access removed",
    invalidate: [["team"]],
  });
  return (
    <>
      <PageHeader
        title="Team"
        description="The people with access to this organization. Accounts are created by an administrator; there is no self registration."
      />
      <DataTable<TeamMember>
        data={team.data ?? []}
        loading={team.isLoading}
        caption="Team"
        searchPlaceholder="Search people"
        columns={[
          {
            accessorKey: "full_name",
            header: "Name",
            cell: ({ row }) => (
              <span className="font-semibold">
                {row.original.full_name}
                {row.original.is_you ? " (you)" : ""}
              </span>
            ),
          },
          { accessorKey: "email", header: "Email" },
          {
            accessorKey: "role",
            header: "Role",
            cell: ({ row }) =>
              row.original.is_you ? (
                ROLE_LABEL[row.original.role]
              ) : (
                <select
                  aria-label={`Role of ${row.original.full_name}`}
                  value={row.original.role}
                  onChange={(e) => change.mutate({ id: row.original.user_id, role: e.target.value as Role })}
                  className="h-9 rounded-md border border-input bg-background px-2 text-sm"
                >
                  {ROLES.map((r) => (
                    <option key={r} value={r}>
                      {ROLE_LABEL[r]}
                    </option>
                  ))}
                </select>
              ),
          },
          {
            accessorKey: "last_login_at",
            header: "Last sign in",
            cell: (c) => formatDateTime(c.getValue() as string | null),
          },
          {
            id: "actions",
            header: "Actions",
            enableSorting: false,
            cell: ({ row }) =>
              row.original.is_you ? null : (
                <ConfirmDialog
                  trigger={
                    <Button size="sm" variant="ghost">
                      Remove
                    </Button>
                  }
                  title={`Remove ${row.original.full_name}?`}
                  description="They lose access to this organization at once. Their account is not deleted."
                  confirmLabel="Remove access"
                  tone="danger"
                  onConfirm={() => remove.mutateAsync(row.original.user_id).then(() => undefined)}
                />
              ),
          },
        ]}
      />
    </>
  );
}

// -- Audit log ------------------------------------------------------------------------------------

export function AuditLog() {
  usePageMeta("Audit log");
  const [action, setAction] = useState("");
  const [page, setPage] = useState(0);
  const log = useAudit({ ...(action ? { action } : {}), offset: String(page * 50) });
  const rows = log.data?.items ?? [];
  return (
    <>
      <PageHeader title="Audit log" description="Who did what and when. The log is append only." />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="space-y-1.5">
          <Label htmlFor="audit-action">Action</Label>
          <Input
            id="audit-action"
            placeholder="for example auth.login"
            value={action}
            onChange={(e) => {
              setAction(e.target.value);
              setPage(0);
            }}
          />
        </div>
      </div>
      <DataTable<AuditEntry>
        data={rows}
        loading={log.isLoading}
        caption="Audit log"
        searchPlaceholder="Filter this page"
        pageSize={50}
        empty={{ title: "No entries", text: "Nothing matches this filter." }}
        columns={[
          { accessorKey: "created_at", header: "When", cell: (c) => formatDateTime(String(c.getValue())) },
          {
            accessorKey: "action",
            header: "Action",
            cell: (c) => <code className="text-xs">{String(c.getValue())}</code>,
          },
          { accessorKey: "entity_type", header: "Entity", cell: (c) => c.getValue() ?? "None" },
          {
            accessorKey: "actor_user_id",
            header: "Actor",
            cell: (c) => (c.getValue() ? String(c.getValue()).slice(0, 8) : "System"),
          },
          {
            id: "details",
            header: "Details",
            enableSorting: false,
            accessorFn: (e) => JSON.stringify(e.details ?? {}),
            cell: (c) => (
              <span className="break-all text-xs text-muted-foreground">{String(c.getValue()).slice(0, 120)}</span>
            ),
          },
        ]}
      />
      <div className="mt-3 flex justify-end gap-2">
        <Button variant="secondary" size="sm" disabled={page === 0} onClick={() => setPage(page - 1)}>
          Newer
        </Button>
        <Button variant="secondary" size="sm" disabled={rows.length < 50} onClick={() => setPage(page + 1)}>
          Older
        </Button>
      </div>
    </>
  );
}

// -- Settings -------------------------------------------------------------------------------------

export function Settings() {
  usePageMeta("Settings");
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api.get<OrgSettings>("/api/v1/settings") });
  const usage = useQuery({ queryKey: ["llm-usage"], queryFn: () => api.get<LlmUsage>("/api/v1/llm/usage") });
  const [draft, setForm] = useState<OrgSettings | null>(null);
  const form = draft ?? settings.data ?? null;
  const [ping, setPing] = useState<
    { provider: string; model: string; ok: boolean; latency_ms?: number | null; error?: string | null }[] | null
  >(null);
  const { can } = useSession();
  const save = useAction({
    run: () => api.put<OrgSettings>("/api/v1/settings", form),
    success: "Settings saved",
    invalidate: [["settings"]],
  });
  const test = useAction({
    run: () => api.post<NonNullable<typeof ping>>("/api/v1/llm/test-connection"),
    onDone: setPing,
  });
  if (settings.isError) return <ErrorNote error={settings.error} retry={() => void settings.refetch()} />;
  if (!form) return <Skeleton className="h-64" />;
  const order = form.llm_provider_order ?? [];
  const first = order[0] ?? "groq";
  const second = order.find((p) => p !== first) ?? (first === "groq" ? "gemini" : "groq");
  const num = (
    key: "daily_token_budget_org" | "daily_token_budget_system" | "evidence_retention_days",
    label: string,
    hint: string,
  ) => (
    <div className="space-y-1.5">
      <Label htmlFor={key}>{label}</Label>
      <Input
        id={key}
        type="number"
        value={form[key]}
        onChange={(e) => setForm({ ...form, [key]: Number(e.target.value) })}
      />
      <p className="text-xs text-muted-foreground">{hint}</p>
    </div>
  );
  const error = save.error instanceof ApiError ? save.error.message : null;
  return (
    <>
      <PageHeader title="Settings" description="Language model providers and budgets, and how long evidence is kept." />
      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Organization settings">
          <form
            className="space-y-4"
            aria-label="Organization settings"
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate(undefined);
            }}
          >
            <Select
              id="primary"
              label="Primary provider"
              value={first}
              onChange={(v) =>
                setForm({ ...form, llm_provider_order: [v as "groq" | "gemini", v === "groq" ? "gemini" : "groq"] })
              }
              options={[
                { value: "groq", label: "Groq" },
                { value: "gemini", label: "Gemini" },
              ]}
            />
            <p className="text-sm text-muted-foreground">
              Fallback: {second}. Only synthetic or masked data may be sent to a free tier provider.
            </p>
            {num("daily_token_budget_org", "Daily token budget, organization", "Tokens per day across all systems.")}
            {num("daily_token_budget_system", "Daily token budget, per system", "Tokens per day for one system.")}
            {num(
              "evidence_retention_days",
              "Evidence retention (days)",
              "Evidence older than this is deleted by the retention job.",
            )}
            {error && (
              <p role="alert" className="text-sm text-danger">
                {error}
              </p>
            )}
            {can("admin") && (
              <Button type="submit" disabled={save.isPending}>
                Save settings
              </Button>
            )}
          </form>
        </Panel>
        <Panel
          title="Providers and today's use"
          actions={
            <Button size="sm" variant="secondary" onClick={() => test.mutate(undefined)} disabled={test.isPending}>
              Test connection
            </Button>
          }
        >
          {usage.data && (
            <dl className="mb-4 grid grid-cols-3 gap-3">
              <Stat label="Calls today" value={usage.data.calls} />
              <Stat
                label="Tokens"
                value={usage.data.tokens_used}
                hint={`of ${usage.data.org_daily_budget.toLocaleString("en-US")}`}
              />
              <Stat label="Cache hits" value={usage.data.cache_hits} />
            </dl>
          )}
          <ul className="space-y-2 text-sm">
            {(usage.data?.providers ?? []).map((p) => (
              <li key={p.provider} className="flex items-center justify-between rounded-md border border-border p-3">
                <span>
                  <strong>{p.provider}</strong> ({p.model})
                </span>
                <span className="text-muted-foreground">
                  {p.configured ? `circuit ${p.circuit}` : "not configured"}
                </span>
              </li>
            ))}
          </ul>
          {ping && (
            <ul className="mt-4 space-y-2 text-sm" aria-live="polite">
              {ping.map((p) => (
                <li key={p.provider} className={p.ok ? "text-success" : "text-danger"}>
                  {p.provider}: {p.ok ? `reachable in ${p.latency_ms} ms` : (p.error ?? "failed")}
                </li>
              ))}
              {ping.length === 0 && <li className="text-muted-foreground">No provider is configured.</li>}
            </ul>
          )}
        </Panel>
      </div>
    </>
  );
}

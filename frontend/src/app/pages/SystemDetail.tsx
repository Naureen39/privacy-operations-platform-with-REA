import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import { usePageMeta } from "@/lib/queries";
import { useAction, useActivities, useFindings, useRecipients, useSystem, useTechnologies } from "../hooks/data";
import { useSession } from "../session";
import { DataTable } from "../ui/DataTable";
import { ErrorNote, formatDateTime, SeverityBadge, Skeleton, StatusBadge } from "../ui/kit";
import { ConfirmDialog, PageHeader, Panel } from "../ui/parts";
import type { Job, Recipient, System } from "../types";
import { ElementsTable } from "./shared/ElementsTable";
import { EvidencePanel } from "./shared/EvidencePanel";
import { EvidenceDrawer } from "./shared/EvidenceDrawer";
import NotFound from "../../site/pages/NotFound";

function Overview({ system }: { system: System }) {
  const { can } = useSession();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(system.name);
  const [description, setDescription] = useState(system.description ?? "");
  const activities = useActivities();
  const jobs = useQuery({
    queryKey: ["jobs", system.id],
    queryFn: () => api.get<Job[]>("/api/v1/jobs", { system_id: system.id, limit: 10 }),
  });
  const record = (activities.data ?? []).find((a) => a.system_ids.includes(system.id));
  const save = useAction({
    run: () => api.patch<System>(`/api/v1/systems/${system.id}`, { name, description }),
    success: "System updated",
    invalidate: [["system", system.id], ["systems"]],
    onDone: () => setEditing(false),
  });
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Panel
        title="Details"
        actions={
          can("write") &&
          !editing && (
            <Button size="sm" variant="secondary" onClick={() => setEditing(true)}>
              Edit
            </Button>
          )
        }
      >
        {editing ? (
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate(undefined);
            }}
          >
            <div className="space-y-1.5">
              <Label htmlFor="sys-name">Name</Label>
              <Input id="sys-name" value={name} onChange={(e) => setName(e.target.value)} required />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="sys-desc">Description</Label>
              <Textarea id="sys-desc" value={description} onChange={(e) => setDescription(e.target.value)} />
            </div>
            <div className="flex gap-2">
              <Button type="submit" disabled={save.isPending}>
                Save
              </Button>
              <Button type="button" variant="ghost" onClick={() => setEditing(false)}>
                Cancel
              </Button>
            </div>
          </form>
        ) : (
          <dl className="grid grid-cols-[9rem_1fr] gap-x-3 gap-y-2 text-sm">
            <dt className="text-muted-foreground">Description</dt>
            <dd>{system.description || "None"}</dd>
            <dt className="text-muted-foreground">Stage</dt>
            <dd>
              <StatusBadge value={system.status.toLowerCase()} />
            </dd>
            <dt className="text-muted-foreground">Owner</dt>
            <dd>{system.owner_user_id ? "Assigned" : "Unassigned"}</dd>
            <dt className="text-muted-foreground">Last discovery</dt>
            <dd>{formatDateTime(system.last_discovery_at)}</dd>
            <dt className="text-muted-foreground">Record</dt>
            <dd>
              {record ? (
                <Link className="font-semibold text-primary hover:underline" to={`/app/records/${record.id}`}>
                  {record.name} ({record.status})
                </Link>
              ) : (
                "No record yet"
              )}
            </dd>
          </dl>
        )}
      </Panel>
      <Panel title="Onboarding runs">
        {jobs.isLoading ? (
          <Skeleton className="h-24" />
        ) : (jobs.data ?? []).length === 0 ? (
          <p className="text-muted-foreground">No runs yet. Use the Add system wizard to onboard from evidence.</p>
        ) : (
          <ul className="divide-y divide-border text-sm">
            {(jobs.data ?? []).map((j) => (
              <li key={j.id} className="flex items-center justify-between gap-3 py-2">
                <span>{formatDateTime(j.created_at)}</span>
                <span className="text-muted-foreground">{Object.keys(j.stages ?? {}).join(", ")}</span>
                <StatusBadge value={j.state} />
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}

function Recipients({ systemId }: { systemId: string }) {
  const recipients = useRecipients(systemId);
  const technologies = useTechnologies(systemId);
  const [drawer, setDrawer] = useState<string | null>(null);
  return (
    <div className="space-y-6">
      <DataTable<Recipient>
        data={recipients.data ?? []}
        loading={recipients.isLoading}
        caption="Recipients"
        searchPlaceholder="Search recipients"
        empty={{ title: "No recipients found", text: "Recipients are found in captures, scripts and the notice." }}
        columns={[
          { accessorKey: "vendor", header: "Vendor", cell: (c) => c.getValue() ?? "Unknown" },
          { accessorKey: "domain", header: "Domain" },
          { accessorKey: "role", header: "Role" },
          { accessorKey: "country", header: "Country", cell: (c) => c.getValue() ?? "Unknown" },
          {
            id: "evidence",
            header: "Source",
            enableSorting: false,
            cell: ({ row }) =>
              row.original.evidence_id ? (
                <Button size="sm" variant="ghost" onClick={() => setDrawer(row.original.evidence_id ?? null)}>
                  Evidence
                </Button>
              ) : (
                "Document"
              ),
          },
        ]}
      />
      <Panel title="Technologies">
        {(technologies.data ?? []).length === 0 ? (
          <p className="text-muted-foreground">None detected.</p>
        ) : (
          <ul className="flex flex-wrap gap-2">
            {(technologies.data ?? []).map((t) => (
              <li key={t.id} className="rounded-full bg-muted px-3 py-1 text-sm">
                {t.name}
                {t.version ? ` ${t.version}` : ""} <span className="text-muted-foreground">({t.kind})</span>
              </li>
            ))}
          </ul>
        )}
      </Panel>
      <EvidenceDrawer evidenceId={drawer} onClose={() => setDrawer(null)} />
    </div>
  );
}

function SystemFindings({ systemId }: { systemId: string }) {
  const findings = useFindings({ system_id: systemId });
  return (
    <DataTable
      data={findings.data ?? []}
      loading={findings.isLoading}
      caption="Findings of this system"
      searchPlaceholder="Search findings"
      empty={{ title: "No findings", text: "The sources agree, or the system has not been compared yet." }}
      columns={[
        { accessorKey: "title", header: "Finding" },
        { accessorKey: "severity", header: "Severity", cell: (c) => <SeverityBadge value={String(c.getValue())} /> },
        { accessorKey: "status", header: "Status", cell: (c) => <StatusBadge value={String(c.getValue())} /> },
        { accessorKey: "created_at", header: "Raised", cell: (c) => formatDateTime(String(c.getValue())) },
      ]}
    />
  );
}

function ActivityTab({ systemId }: { systemId: string }) {
  const jobs = useQuery({
    queryKey: ["jobs", systemId],
    queryFn: () => api.get<Job[]>("/api/v1/jobs", { system_id: systemId, limit: 50 }),
  });
  const comments = useQuery({
    queryKey: ["comments", systemId],
    queryFn: () =>
      api.get<{ id: string; body: string; created_at: string }[]>("/api/v1/comments", {
        entity_type: "system",
        entity_id: systemId,
      }),
  });
  const items = [
    ...(jobs.data ?? []).map((j) => ({
      at: j.created_at,
      text: `Onboarding run ${j.state} (${Object.keys(j.stages ?? {}).join(", ")})`,
    })),
    ...(comments.data ?? []).map((c) => ({ at: c.created_at, text: `Comment: ${c.body}` })),
  ].sort((a, b) => b.at.localeCompare(a.at));
  if (jobs.isLoading) return <Skeleton className="h-32" />;
  if (items.length === 0) return <p className="text-muted-foreground">No activity yet.</p>;
  return (
    <ol className="space-y-3">
      {items.map((i) => (
        <li key={i.at + i.text} className="flex gap-4 border-l-2 border-border pl-4 text-sm">
          <time className="w-40 shrink-0 text-muted-foreground">{formatDateTime(i.at)}</time>
          <span>{i.text}</span>
        </li>
      ))}
    </ol>
  );
}

export default function SystemDetail() {
  const { id = "" } = useParams();
  const { can } = useSession();
  const navigate = useNavigate();
  const system = useSystem(id);
  usePageMeta(system.data?.name ?? "System");
  const remove = useAction({
    run: () => api.del(`/api/v1/systems/${id}`),
    success: "System deleted",
    invalidate: [["systems"], ["activities"]],
    onDone: () => navigate("/app/systems"),
  });
  if (system.isLoading) return <Skeleton className="h-64" />;
  if (system.isError) {
    const status = (system.error as { status?: number }).status;
    return status === 404 ? <NotFound /> : <ErrorNote error={system.error} retry={() => void system.refetch()} />;
  }
  const s = system.data;
  if (!s) return null;
  return (
    <>
      <PageHeader
        title={s.name}
        description={s.description ?? undefined}
        actions={
          can("admin") && (
            <ConfirmDialog
              trigger={<Button variant="secondary">Delete</Button>}
              title={`Delete ${s.name}?`}
              description="Its evidence, data elements and findings are removed with it. This cannot be undone."
              confirmLabel="Delete system"
              tone="danger"
              onConfirm={() => remove.mutateAsync(undefined).then(() => undefined)}
            />
          )
        }
      />
      <Tabs defaultValue="overview">
        <TabsList aria-label="System sections" className="mb-5">
          {[
            ["overview", "Overview"],
            ["evidence", "Evidence"],
            ["elements", "Data elements"],
            ["recipients", "Recipients"],
            ["findings", "Findings"],
            ["activity", "Activity"],
          ].map(([v, l]) => (
            <TabsTrigger key={v} value={v as string}>
              {l}
            </TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value="overview">
          <Overview system={s} />
        </TabsContent>
        <TabsContent value="evidence">
          <EvidencePanel systemId={s.id} />
        </TabsContent>
        <TabsContent value="elements">
          <ElementsTable systemId={s.id} />
        </TabsContent>
        <TabsContent value="recipients">
          <Recipients systemId={s.id} />
        </TabsContent>
        <TabsContent value="findings">
          <SystemFindings systemId={s.id} />
        </TabsContent>
        <TabsContent value="activity">
          <ActivityTab systemId={s.id} />
        </TabsContent>
      </Tabs>
    </>
  );
}

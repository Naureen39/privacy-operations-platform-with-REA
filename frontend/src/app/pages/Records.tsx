import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { usePageMeta } from "@/lib/queries";
import NotFound from "../../site/pages/NotFound";
import { useAction, useActivities, useActivity, useVersions } from "../hooks/data";
import { useSession } from "../session";
import { DataTable } from "../ui/DataTable";
import { ErrorNote, formatDate, formatDateTime, Skeleton, StatusBadge } from "../ui/kit";
import { PageHeader, Panel, Select } from "../ui/parts";
import { useToast } from "../ui/toast";
import type { Activity, Diff } from "../types";
import { RecordEdit } from "./shared/RecordEdit";
import { RecordFields } from "./shared/RecordFields";

async function save(path: string, params?: Record<string, string>) {
  const { blob, filename } = await api.blob(path, params);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename ?? path.split("/").pop() ?? "download";
  a.click();
  URL.revokeObjectURL(url);
}

export function RecordsList() {
  usePageMeta("Records of processing");
  const { can } = useSession();
  const toast = useToast();
  const navigate = useNavigate();
  const records = useActivities();
  const exportFile = (kind: "xlsx" | "pdf") =>
    save(`/api/v1/exports/register.${kind}`).catch(() => toast.error("The export failed"));
  return (
    <>
      <PageHeader
        title="Records of processing"
        description="The register under Article 30, with the review state of every record."
        actions={
          can("export") && (
            <>
              <Button variant="secondary" onClick={() => void exportFile("xlsx")}>
                <Download aria-hidden="true" /> Spreadsheet
              </Button>
              <Button variant="secondary" onClick={() => void exportFile("pdf")}>
                <Download aria-hidden="true" /> PDF
              </Button>
            </>
          )
        }
      />
      <DataTable<Activity>
        data={records.data ?? []}
        loading={records.isLoading}
        caption="Records of processing"
        searchPlaceholder="Search records"
        onRowClick={(r) => navigate(`/app/records/${r.id}`)}
        empty={{ title: "No records yet", text: "Records are generated when a system is onboarded from evidence." }}
        columns={[
          {
            accessorKey: "name",
            header: "Record",
            cell: ({ row }) => (
              <Link
                to={`/app/records/${row.original.id}`}
                className="font-semibold text-primary hover:underline"
                onClick={(e) => e.stopPropagation()}
              >
                {row.original.name}
              </Link>
            ),
          },
          { accessorKey: "status", header: "Status", cell: (c) => <StatusBadge value={String(c.getValue())} /> },
          { accessorKey: "lawful_basis", header: "Lawful basis", cell: (c) => c.getValue() ?? "Not recorded" },
          { accessorKey: "current_version", header: "Version", cell: (c) => `v${c.getValue()}` },
          { id: "missing", header: "Missing fields", accessorFn: (r) => r.missing_fields.length },
          {
            accessorKey: "next_review_date",
            header: "Next review",
            cell: (c) => formatDate(c.getValue() as string | null),
          },
        ]}
      />
    </>
  );
}

function History({ record }: { record: Activity }) {
  const versions = useVersions(record.id);
  const list = versions.data ?? [];
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const diff = useQuery({
    queryKey: ["diff", record.id, from, to],
    enabled: Boolean(from && to && from !== to),
    queryFn: () => api.get<Diff>(`/api/v1/activities/${record.id}/diff`, { from, to }),
  });
  const options = list.map((v) => ({ value: String(v.version), label: `v${v.version} (${formatDate(v.created_at)})` }));
  return (
    <div className="space-y-5">
      <ol className="space-y-2">
        {list.map((v) => (
          <li key={v.version} className="flex flex-wrap items-center gap-3 rounded-md border border-border p-3 text-sm">
            <span className="font-semibold">v{v.version}</span>
            <span className="text-muted-foreground">{formatDateTime(v.created_at)}</span>
            <span>{v.change_summary ?? "No summary"}</span>
            {v.approved_by && <StatusBadge value="approved" />}
          </li>
        ))}
      </ol>
      {list.length > 1 && (
        <Panel title="Compare two versions">
          <div className="flex flex-wrap gap-4">
            <Select
              id="diff-from"
              label="From"
              value={from}
              onChange={setFrom}
              options={[{ value: "", label: "Choose" }, ...options]}
            />
            <Select
              id="diff-to"
              label="To"
              value={to}
              onChange={setTo}
              options={[{ value: "", label: "Choose" }, ...options]}
            />
          </div>
          {diff.data && (
            <div className="mt-4 text-sm">
              <p className="font-semibold">{diff.data.summary}</p>
              <ul className="mt-2 space-y-2">
                {diff.data.changes.map((c, i) => (
                  <li key={i} className="rounded-md bg-muted p-3">
                    <p className="font-medium">{String(c.field ?? c.label ?? "Field")}</p>
                    <p className="text-danger line-through">{JSON.stringify(c.before ?? c.old ?? c.from ?? null)}</p>
                    <p className="text-success">{JSON.stringify(c.after ?? c.new ?? c.to ?? null)}</p>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Panel>
      )}
    </div>
  );
}

export function RecordDetail() {
  const { id = "" } = useParams();
  const { can, me } = useSession();
  const record = useActivity(id);
  usePageMeta(record.data?.name ?? "Record");
  const [editing, setEditing] = useState(false);
  const [note, setNote] = useState("");
  const toast = useToast();
  const refresh = [["activity", id], ["activities"], ["versions", id]];
  const submit = useAction({
    run: () => api.post(`/api/v1/activities/${id}/submit`),
    success: "Submitted for approval",
    invalidate: refresh,
  });
  const approve = useAction({
    run: () => api.post(`/api/v1/activities/${id}/approve`, { note: note || null }),
    success: "Approved",
    invalidate: refresh,
  });
  const reject = useAction({
    run: () => api.post(`/api/v1/activities/${id}/reject`, { note: note || "Returned for changes" }),
    success: "Sent back to draft",
    invalidate: refresh,
  });
  const publish = useAction({
    run: () => api.post(`/api/v1/activities/${id}/publish`),
    success: "Published to the register",
    invalidate: refresh,
  });
  const screening = useAction({
    run: () => api.post(`/api/v1/activities/${id}/dpia-screening`, {}),
    success: "Screening finished",
    invalidate: [["dpias"]],
  });

  if (record.isLoading) return <Skeleton className="h-64" />;
  if (record.isError) {
    return (record.error as { status?: number }).status === 404 ? (
      <NotFound />
    ) : (
      <ErrorNote error={record.error} retry={() => void record.refetch()} />
    );
  }
  const r = record.data;
  if (!r) return null;
  const exportPdf = () => save("/api/v1/exports/register.pdf").catch(() => toast.error("The export failed"));
  return (
    <>
      <PageHeader
        title={r.name}
        description={`Version ${r.current_version}. Draft for review by a qualified privacy professional. Not legal advice.`}
        actions={
          <>
            <StatusBadge value={r.status} />
            {can("export") && (
              <Button variant="secondary" onClick={() => void exportPdf()}>
                <Download aria-hidden="true" /> Register PDF
              </Button>
            )}
            {can("write") && r.status === "draft" && (
              <Button onClick={() => submit.mutate(undefined)} disabled={submit.isPending}>
                Submit for approval
              </Button>
            )}
            {can("write") && (
              <Button variant="secondary" onClick={() => screening.mutate(undefined)}>
                Screen for an impact assessment
              </Button>
            )}
          </>
        }
      />
      {can("approve") && r.status === "awaiting_review" && (
        <Panel title="Review" className="mb-6">
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="decision-note">Note (required to send back)</Label>
              <Textarea
                id="decision-note"
                className="min-h-20"
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
            </div>
            <div className="flex gap-2">
              <Button onClick={() => approve.mutate(undefined)} disabled={approve.isPending}>
                Approve
              </Button>
              <Button variant="secondary" onClick={() => reject.mutate(undefined)} disabled={reject.isPending}>
                Send back
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              The person who submitted a record cannot approve it. You are signed in as {me.user.email}.
            </p>
          </div>
        </Panel>
      )}
      {can("approve") && r.status === "approved" && (
        <div className="mb-6">
          <Button onClick={() => publish.mutate(undefined)} disabled={publish.isPending}>
            Publish to the register
          </Button>
        </div>
      )}
      <div className="grid gap-6 xl:grid-cols-[2fr_1fr]">
        <Panel
          title="The record"
          actions={
            can("write") &&
            !editing &&
            (r.status === "draft" || r.status === "approved") && (
              <Button size="sm" variant="secondary" onClick={() => setEditing(true)}>
                Edit
              </Button>
            )
          }
        >
          {editing ? <RecordEdit record={r} onDone={() => setEditing(false)} /> : <RecordFields record={r} />}
        </Panel>
        <Panel title="Version history">
          <History record={r} />
        </Panel>
      </div>
    </>
  );
}

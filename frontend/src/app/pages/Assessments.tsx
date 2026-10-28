import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { usePageMeta } from "@/lib/queries";
import { cn } from "@/lib/utils";
import NotFound from "../../site/pages/NotFound";
import { useAction, useDpia, useDpias } from "../hooks/data";
import { useSession } from "../session";
import { DataTable } from "../ui/DataTable";
import { ErrorNote, Skeleton, StatusBadge } from "../ui/kit";
import { PageHeader, Panel } from "../ui/parts";
import { useToast } from "../ui/toast";
import type { DpiaSummary, Risk, Screening } from "../types";
import { useQuery } from "@tanstack/react-query";

const BAND = (l: number, s: number) => {
  const v = l * s;
  return v <= 4 ? "low" : v <= 9 ? "medium" : v <= 15 ? "high" : "very high";
};
const BAND_CLASS: Record<string, string> = {
  low: "bg-success/20",
  medium: "bg-warning/25",
  high: "bg-danger/25",
  "very high": "bg-danger/50",
};

/** The 5 by 5 matrix: likelihood across, severity up. Each cell shows how many risks fall in it and
 *  carries its band in text, so colour is never the only signal. */
export function RiskMatrix({ cells, label }: { cells: number[][]; label: string }) {
  return (
    <figure>
      <table className="w-full table-fixed border-collapse text-center text-xs">
        <caption className="sr-only">{label}</caption>
        <thead>
          <tr>
            <th scope="col" className="w-16 p-1 text-left font-normal text-muted-foreground">
              Severity
            </th>
            {[1, 2, 3, 4, 5].map((l) => (
              <th key={l} scope="col" className="p-1 font-normal text-muted-foreground">
                L{l}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {cells.map((row, i) => {
            const severity = 5 - i;
            return (
              <tr key={severity}>
                <th scope="row" className="p-1 text-left font-normal text-muted-foreground">
                  S{severity}
                </th>
                {row.map((n, j) => {
                  const band = BAND(j + 1, severity);
                  return (
                    <td
                      key={j}
                      className={cn("border border-background p-2", BAND_CLASS[band])}
                      title={`Likelihood ${j + 1}, severity ${severity}: ${band}`}
                    >
                      <span className="block text-sm font-bold">{n || ""}</span>
                      <span className="block text-[10px] uppercase text-foreground/70">{band}</span>
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
      <figcaption className="mt-1 text-xs text-muted-foreground">{label}. Likelihood across, severity up.</figcaption>
    </figure>
  );
}

export function AssessmentsList() {
  usePageMeta("Impact assessments");
  const navigate = useNavigate();
  const dpias = useDpias();
  const screenings = useQuery({
    queryKey: ["screenings"],
    queryFn: () => api.get<Screening[]>("/api/v1/dpia-screenings", { limit: 200 }),
  });
  return (
    <>
      <PageHeader
        title="Impact assessments"
        description="Screening scores for every record, and the assessments drafted for those that need one."
      />
      <Panel title="Assessments" className="mb-6">
        <DataTable<DpiaSummary>
          data={dpias.data ?? []}
          loading={dpias.isLoading}
          caption="Impact assessments"
          searchPlaceholder="Search assessments"
          onRowClick={(d) => navigate(`/app/assessments/${d.id}`)}
          empty={{
            title: "No assessments yet",
            text: "Screen a record, then start an assessment for the ones that need it.",
          }}
          columns={[
            {
              accessorKey: "activity_name",
              header: "Record",
              cell: ({ row }) => (
                <Link
                  to={`/app/assessments/${row.original.id}`}
                  className="font-semibold text-primary hover:underline"
                  onClick={(e) => e.stopPropagation()}
                >
                  {row.original.activity_name}
                </Link>
              ),
            },
            { accessorKey: "status", header: "Status", cell: (c) => <StatusBadge value={String(c.getValue())} /> },
            { accessorKey: "criteria_met", header: "Criteria met" },
            { accessorKey: "risks", header: "Risks" },
            {
              accessorKey: "residual_risk",
              header: "Residual risk",
              cell: (c) => String(c.getValue() ?? "Not set").replace("_", " "),
            },
          ]}
        />
      </Panel>
      <Panel title="Screening results">
        <DataTable<Screening>
          data={screenings.data ?? []}
          loading={screenings.isLoading}
          caption="Screening results"
          searchPlaceholder="Search screenings"
          empty={{ title: "No screenings yet", text: "Open a record and choose Screen for an impact assessment." }}
          columns={[
            { accessorKey: "activity_name", header: "Record" },
            { accessorKey: "criteria_met", header: "Criteria met" },
            { accessorKey: "threshold", header: "Threshold" },
            {
              accessorKey: "required",
              header: "Assessment needed",
              cell: (c) => (c.getValue() ? <StatusBadge value="in_review" /> : "No"),
            },
          ]}
        />
      </Panel>
    </>
  );
}

function RiskRow({ dpiaId, risk, editable }: { dpiaId: string; risk: Risk; editable: boolean }) {
  const [editing, setEditing] = useState(false);
  const [state, setState] = useState({
    likelihood: risk.likelihood,
    severity: risk.severity,
    mitigation: risk.mitigation ?? "",
    residual_likelihood: risk.residual_likelihood ?? 0,
    residual_severity: risk.residual_severity ?? 0,
  });
  const save = useAction({
    run: () =>
      api.patch(`/api/v1/dpias/${dpiaId}/risks/${risk.id}`, {
        likelihood: state.likelihood,
        severity: state.severity,
        mitigation: state.mitigation || null,
        residual_likelihood: state.residual_likelihood || null,
        residual_severity: state.residual_severity || null,
      }),
    success: "Risk updated",
    invalidate: [["dpia", dpiaId], ["dpias"]],
    onDone: () => setEditing(false),
  });
  const remove = useAction({
    run: () => api.del(`/api/v1/dpias/${dpiaId}/risks/${risk.id}`),
    success: "Risk removed",
    invalidate: [["dpia", dpiaId], ["dpias"]],
  });
  const num = (key: keyof typeof state, label: string) => (
    <div className="space-y-1">
      <Label htmlFor={`${risk.id}-${key}`}>{label}</Label>
      <Input
        id={`${risk.id}-${key}`}
        type="number"
        min={key.startsWith("residual") ? 0 : 1}
        max={5}
        value={state[key] as number}
        onChange={(e) => setState({ ...state, [key]: Number(e.target.value) })}
      />
    </div>
  );
  return (
    <li className="rounded-lg border border-border p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h4 className="text-base font-semibold">{risk.title}</h4>
          {risk.description && <p className="text-sm text-muted-foreground">{risk.description}</p>}
          <p className="mt-1 text-xs text-muted-foreground">
            Source: {risk.citation ?? <span className="text-warning">no citation</span>}
          </p>
        </div>
        <div className="text-right text-sm">
          <p>
            Inherent: <strong>{risk.inherent_level.replace("_", " ")}</strong> ({risk.likelihood} x {risk.severity})
          </p>
          <p>
            Residual: <strong>{risk.residual_level ? risk.residual_level.replace("_", " ") : "not set"}</strong>
          </p>
        </div>
      </div>
      {editing ? (
        <div className="mt-4 space-y-3">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {num("likelihood", "Likelihood (1-5)")}
            {num("severity", "Severity (1-5)")}
            {num("residual_likelihood", "Residual likelihood")}
            {num("residual_severity", "Residual severity")}
          </div>
          <div className="space-y-1">
            <Label htmlFor={`${risk.id}-mit`}>Mitigation</Label>
            <Textarea
              id={`${risk.id}-mit`}
              className="min-h-20"
              value={state.mitigation}
              onChange={(e) => setState({ ...state, mitigation: e.target.value })}
            />
          </div>
          <div className="flex gap-2">
            <Button size="sm" onClick={() => save.mutate(undefined)} disabled={save.isPending}>
              Save
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <>
          <p className="mt-3 text-sm">
            <span className="font-medium">Mitigation: </span>
            {risk.mitigation ?? <span className="text-muted-foreground">None recorded</span>}
          </p>
          {editable && (
            <div className="mt-3 flex gap-2">
              <Button size="sm" variant="secondary" onClick={() => setEditing(true)}>
                Edit
              </Button>
              <Button size="sm" variant="ghost" onClick={() => remove.mutate(undefined)}>
                Remove
              </Button>
            </div>
          )}
        </>
      )}
    </li>
  );
}

export function AssessmentEditor() {
  const { id = "" } = useParams();
  const { can } = useSession();
  const toast = useToast();
  const dpia = useDpia(id);
  usePageMeta(dpia.data?.activity_name ? `Assessment: ${dpia.data.activity_name}` : "Assessment");
  const [draft, setDraft] = useState<{ description: string; necessity: string; opinion: string } | null>(null);
  const [note, setNote] = useState("");
  const [risk, setRisk] = useState({ title: "", likelihood: 3, severity: 3 });
  const refresh = [["dpia", id], ["dpias"]];
  const patch = useAction({
    run: () =>
      api.patch(`/api/v1/dpias/${id}`, {
        description: draft?.description,
        necessity_proportionality: draft?.necessity,
        officer_opinion: draft?.opinion,
      }),
    success: "Saved",
    invalidate: refresh,
    onDone: () => setDraft(null),
  });
  const submit = useAction({
    run: () => api.post(`/api/v1/dpias/${id}/submit`),
    success: "Submitted for review",
    invalidate: refresh,
  });
  const approve = useAction({
    run: () => api.post(`/api/v1/dpias/${id}/approve`, { note: note || null }),
    success: "Approved",
    invalidate: refresh,
  });
  const reject = useAction({
    run: () => api.post(`/api/v1/dpias/${id}/reject`, { reason: note || "Returned for changes" }),
    success: "Rejected",
    invalidate: refresh,
  });
  const addRisk = useAction({
    run: () =>
      api.post(`/api/v1/dpias/${id}/risks`, {
        title: risk.title,
        likelihood: risk.likelihood,
        severity: risk.severity,
      }),
    success: "Risk added",
    invalidate: refresh,
    onDone: () => setRisk({ title: "", likelihood: 3, severity: 3 }),
  });

  if (dpia.isLoading) return <Skeleton className="h-64" />;
  if (dpia.isError) {
    return (dpia.error as { status?: number }).status === 404 ? (
      <NotFound />
    ) : (
      <ErrorNote error={dpia.error} retry={() => void dpia.refetch()} />
    );
  }
  const d = dpia.data;
  if (!d) return null;
  const editable = can("write") && (d.status === "draft" || d.status === "rejected");
  const exportPdf = async () => {
    try {
      const { blob } = await api.blob(`/api/v1/dpias/${id}/export.pdf`);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "impact-assessment.pdf";
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      toast.error("The export failed");
    }
  };
  return (
    <>
      <PageHeader
        title={`Impact assessment: ${d.activity_name}`}
        description="Draft for review by a qualified privacy professional. Not legal advice."
        actions={
          <>
            <StatusBadge value={d.status} />
            <Button variant="secondary" onClick={() => void exportPdf()}>
              Export PDF
            </Button>
            {editable && (
              <Button onClick={() => submit.mutate(undefined)} disabled={submit.isPending}>
                Submit for review
              </Button>
            )}
          </>
        }
      />
      {d.missing_fields.length > 0 && (
        <p role="status" className="mb-4 rounded-md border border-warning/40 bg-warning/10 p-3 text-sm">
          Still to complete before it can be submitted: {d.missing_fields.join(", ").replaceAll("_", " ")}.
        </p>
      )}
      {can("approve") && d.status === "in_review" && (
        <Panel title="Review" className="mb-6">
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="dpia-note">Note</Label>
              <Textarea id="dpia-note" className="min-h-20" value={note} onChange={(e) => setNote(e.target.value)} />
            </div>
            <div className="flex gap-2">
              <Button onClick={() => approve.mutate(undefined)}>Approve</Button>
              <Button variant="secondary" onClick={() => reject.mutate(undefined)}>
                Send back
              </Button>
            </div>
          </div>
        </Panel>
      )}
      <div className="grid gap-6 xl:grid-cols-[2fr_1fr]">
        <div className="space-y-6">
          <Panel
            title="Description and necessity"
            actions={
              editable &&
              !draft && (
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() =>
                    setDraft({
                      description: d.description ?? "",
                      necessity: d.necessity_proportionality ?? "",
                      opinion: d.officer_opinion ?? "",
                    })
                  }
                >
                  Edit
                </Button>
              )
            }
          >
            {draft ? (
              <form
                className="space-y-3"
                onSubmit={(e) => {
                  e.preventDefault();
                  patch.mutate(undefined);
                }}
              >
                <div className="space-y-1.5">
                  <Label htmlFor="dpia-desc">Description of the processing</Label>
                  <Textarea
                    id="dpia-desc"
                    value={draft.description}
                    onChange={(e) => setDraft({ ...draft, description: e.target.value })}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="dpia-nec">Necessity and proportionality</Label>
                  <Textarea
                    id="dpia-nec"
                    value={draft.necessity}
                    onChange={(e) => setDraft({ ...draft, necessity: e.target.value })}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="dpia-op">Officer opinion</Label>
                  <Textarea
                    id="dpia-op"
                    className="min-h-20"
                    value={draft.opinion}
                    onChange={(e) => setDraft({ ...draft, opinion: e.target.value })}
                  />
                </div>
                <div className="flex gap-2">
                  <Button type="submit" disabled={patch.isPending}>
                    Save
                  </Button>
                  <Button type="button" variant="ghost" onClick={() => setDraft(null)}>
                    Cancel
                  </Button>
                </div>
              </form>
            ) : (
              <dl className="space-y-4 text-sm">
                <div>
                  <dt className="font-semibold">Description</dt>
                  <dd className="mt-1 whitespace-pre-wrap text-muted-foreground">
                    {d.description || "Not written yet"}
                  </dd>
                </div>
                <div>
                  <dt className="font-semibold">Necessity and proportionality</dt>
                  <dd className="mt-1 whitespace-pre-wrap text-muted-foreground">
                    {d.necessity_proportionality || "Not written yet"}
                  </dd>
                </div>
                <div>
                  <dt className="font-semibold">Officer opinion</dt>
                  <dd className="mt-1 whitespace-pre-wrap text-muted-foreground">
                    {d.officer_opinion || "Not recorded"}
                  </dd>
                </div>
              </dl>
            )}
          </Panel>
          <Panel title={`Risk register (${d.risks.length})`}>
            <ul className="space-y-3">
              {d.risks.map((r) => (
                <RiskRow key={r.id} dpiaId={id} risk={r} editable={editable} />
              ))}
            </ul>
            {d.risks.length === 0 && <p className="text-muted-foreground">No risks yet.</p>}
            {editable && (
              <form
                className="mt-4 flex flex-wrap items-end gap-3 border-t border-border pt-4"
                aria-label="Add a risk"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (risk.title.trim().length >= 3) addRisk.mutate(undefined);
                }}
              >
                <div className="min-w-48 flex-1 space-y-1">
                  <Label htmlFor="new-risk">New risk</Label>
                  <Input
                    id="new-risk"
                    value={risk.title}
                    onChange={(e) => setRisk({ ...risk, title: e.target.value })}
                  />
                </div>
                <div className="w-24 space-y-1">
                  <Label htmlFor="new-l">Likelihood</Label>
                  <Input
                    id="new-l"
                    type="number"
                    min={1}
                    max={5}
                    value={risk.likelihood}
                    onChange={(e) => setRisk({ ...risk, likelihood: Number(e.target.value) })}
                  />
                </div>
                <div className="w-24 space-y-1">
                  <Label htmlFor="new-s">Severity</Label>
                  <Input
                    id="new-s"
                    type="number"
                    min={1}
                    max={5}
                    value={risk.severity}
                    onChange={(e) => setRisk({ ...risk, severity: Number(e.target.value) })}
                  />
                </div>
                <Button type="submit" disabled={risk.title.trim().length < 3}>
                  Add risk
                </Button>
              </form>
            )}
          </Panel>
        </div>
        <div className="space-y-6">
          <Panel title="Risk matrix">
            <div className="space-y-5">
              <RiskMatrix cells={(d.matrix as Record<string, number[][]>).inherent ?? []} label="Inherent risk" />
              <RiskMatrix
                cells={(d.matrix as Record<string, number[][]>).residual ?? []}
                label="Residual risk after mitigation"
              />
              <p className="text-sm">
                Overall residual risk:{" "}
                <strong>{d.residual_risk ? d.residual_risk.replace("_", " ") : "not set"}</strong>
              </p>
            </div>
          </Panel>
        </div>
      </div>
    </>
  );
}

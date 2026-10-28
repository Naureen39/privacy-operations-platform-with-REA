import { useState } from "react";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { usePageMeta } from "@/lib/queries";
import { useAction, useFindings, useSystems } from "../hooks/data";
import { useSession } from "../session";
import { DataTable } from "../ui/DataTable";
import { formatDateTime, SeverityBadge, StatusBadge } from "../ui/kit";
import { PageHeader, Panel, Select } from "../ui/parts";
import type { Finding } from "../types";

const SEVERITIES = ["", "critical", "high", "medium", "low"];
const STATUSES = ["", "open", "acknowledged", "resolved", "dismissed"];

export default function Findings() {
  usePageMeta("Findings");
  const { can } = useSession();
  const [severity, setSeverity] = useState("");
  const [status, setStatus] = useState("open");
  const [system, setSystem] = useState("");
  const [type, setType] = useState("");
  const [selected, setSelected] = useState<Finding | null>(null);
  const params: Record<string, string> = {};
  if (severity) params.severity = severity;
  if (status) params.status = status;
  if (system) params.system_id = system;
  if (type) params.type = type;
  const findings = useFindings(params);
  const all = useFindings({});
  const systems = useSystems();
  const types = [...new Set((all.data ?? []).map((f) => f.type))].sort();
  const nameOf = (id: string | null | undefined) =>
    (systems.data ?? []).find((s) => s.id === id)?.name ?? "Organization wide";

  const update = useAction({
    run: (input: { id: string; status: string }) =>
      api.patch<Finding>(`/api/v1/findings/${input.id}`, { status: input.status }),
    success: "Finding updated",
    invalidate: [["findings"]],
    onDone: (f) => setSelected(f),
  });
  const task = useAction({
    run: (id: string) => api.post(`/api/v1/findings/${id}/task`, {}),
    success: "Task created",
    invalidate: [["tasks"]],
  });

  return (
    <>
      <PageHeader
        title="Findings"
        description="Where the sources disagree or a required fact is missing, with the evidence and a suggested fix."
      />
      <div className="mb-4 flex flex-wrap gap-4">
        <Select
          id="f-sev"
          label="Severity"
          value={severity}
          onChange={setSeverity}
          options={SEVERITIES.map((v) => ({ value: v, label: v || "All" }))}
        />
        <Select
          id="f-status"
          label="Status"
          value={status}
          onChange={setStatus}
          options={STATUSES.map((v) => ({ value: v, label: v || "All" }))}
        />
        <Select
          id="f-type"
          label="Type"
          value={type}
          onChange={setType}
          options={[{ value: "", label: "All" }, ...types.map((t) => ({ value: t, label: t.replaceAll("_", " ") }))]}
        />
        <Select
          id="f-system"
          label="System"
          value={system}
          onChange={setSystem}
          options={[{ value: "", label: "All" }, ...(systems.data ?? []).map((s) => ({ value: s.id, label: s.name }))]}
        />
      </div>
      <div className="grid gap-6 xl:grid-cols-[1.6fr_1fr]">
        <DataTable<Finding>
          data={findings.data ?? []}
          loading={findings.isLoading}
          caption="Findings"
          searchPlaceholder="Search findings"
          onRowClick={setSelected}
          empty={{ title: "No findings match", text: "Change the filters, or onboard more systems." }}
          columns={[
            { accessorKey: "title", header: "Finding" },
            {
              accessorKey: "severity",
              header: "Severity",
              cell: (c) => <SeverityBadge value={String(c.getValue())} />,
            },
            { accessorKey: "type", header: "Type", cell: (c) => String(c.getValue()).replaceAll("_", " ") },
            { id: "system", header: "System", accessorFn: (f) => nameOf(f.system_id) },
            { accessorKey: "status", header: "Status", cell: (c) => <StatusBadge value={String(c.getValue())} /> },
          ]}
        />
        <Panel title={selected ? selected.title : "Details"}>
          {!selected ? (
            <p className="text-muted-foreground">Select a finding to see its evidence and the suggested fix.</p>
          ) : (
            <div className="space-y-4 text-sm">
              <div className="flex flex-wrap gap-2">
                <SeverityBadge value={selected.severity} />
                <StatusBadge value={selected.status} />
              </div>
              <p>{selected.description}</p>
              <div>
                <h3 className="text-base">Suggested fix</h3>
                <p className="text-muted-foreground">{selected.suggested_fix ?? "None suggested"}</p>
              </div>
              <div>
                <h3 className="text-base">Evidence</h3>
                {selected.evidence_refs.length === 0 ? (
                  <p className="text-muted-foreground">No evidence references.</p>
                ) : (
                  <ul className="mt-1 list-disc space-y-1 pl-5 text-muted-foreground">
                    {selected.evidence_refs.map((r, i) => (
                      <li key={i} className="break-words">
                        {typeof r === "string" ? r : JSON.stringify(r)}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <p className="text-xs text-muted-foreground">
                Raised {formatDateTime(selected.created_at)}. System: {nameOf(selected.system_id)}.
              </p>
              {can("write") && (
                <div className="flex flex-wrap gap-2 border-t border-border pt-3">
                  {selected.status === "open" && (
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => update.mutate({ id: selected.id, status: "acknowledged" })}
                    >
                      Acknowledge
                    </Button>
                  )}
                  {selected.status !== "resolved" && (
                    <Button size="sm" onClick={() => update.mutate({ id: selected.id, status: "resolved" })}>
                      Mark resolved
                    </Button>
                  )}
                  {selected.status !== "dismissed" && (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => update.mutate({ id: selected.id, status: "dismissed" })}
                    >
                      Dismiss
                    </Button>
                  )}
                  <Button size="sm" variant="secondary" onClick={() => task.mutate(selected.id)}>
                    Create task
                  </Button>
                </div>
              )}
            </div>
          )}
        </Panel>
      </div>
    </>
  );
}

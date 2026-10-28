import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input, Textarea } from "@/components/ui/input";
import { api } from "@/lib/api";
import { usePageMeta } from "@/lib/queries";
import { cn } from "@/lib/utils";
import { useAction, useActivities, useEvidence, useFindings, useSystem } from "../hooks/data";
import { useSession } from "../session";
import { SeverityBadge, Skeleton, StatusBadge } from "../ui/kit";
import { PageHeader, Panel, Select } from "../ui/parts";
import type { Activity, Job, System, TeamMember } from "../types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ElementsTable } from "./shared/ElementsTable";
import { EvidencePanel } from "./shared/EvidencePanel";
import { JobProgress } from "./shared/JobProgress";
import { RecordEdit } from "./shared/RecordEdit";
import { RecordFields } from "./shared/RecordFields";

const STEPS = ["Register", "Evidence", "Discovery", "Data elements", "Comparison", "Record draft", "Submit"] as const;

/** A step that runs a background job and reports on it. */
function RunStep({
  systemId,
  stages,
  label,
  description,
  onDone,
  doneLabel,
  refresh = [],
}: {
  systemId: string;
  stages: string[];
  label: string;
  description: string;
  onDone: () => void;
  doneLabel: string;
  refresh?: string[];
}) {
  const [jobId, setJobId] = useState<string | null>(null);
  const [state, setState] = useState<string | null>(null);
  const client = useQueryClient();
  const start = useAction({
    run: () => api.post<Job>(`/api/v1/systems/${systemId}/onboard`, { stages }),
    invalidate: [],
    onDone: (job) => {
      setState(null);
      setJobId(job.id);
    },
  });
  return (
    <div className="space-y-4">
      <p className="text-muted-foreground">{description}</p>
      {!jobId && (
        <Button onClick={() => start.mutate(undefined)} disabled={start.isPending}>
          {start.isPending ? "Starting..." : label}
        </Button>
      )}
      <JobProgress
        jobId={jobId}
        onFinished={(finished) => {
          setState(finished);
          // what the job produced should appear without another click
          for (const key of refresh) void client.invalidateQueries({ queryKey: [key] });
        }}
      />
      {state === "failed" && (
        <Button variant="secondary" onClick={() => setJobId(null)}>
          Run again
        </Button>
      )}
      {state === "succeeded" && <Button onClick={onDone}>{doneLabel}</Button>}
    </div>
  );
}

function Register({ onCreated }: { onCreated: (system: System) => void }) {
  const { me } = useSession();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [owner, setOwner] = useState("");
  const team = useQuery({
    queryKey: ["team"],
    enabled: me.role === "admin",
    queryFn: () => api.get<TeamMember[]>("/api/v1/team", { limit: 200 }),
  });
  const create = useAction({
    run: () =>
      api.post<System>("/api/v1/systems", {
        name: name.trim(),
        description: description.trim() || undefined,
        owner_user_id: owner || undefined,
      }),
    success: (s) => `Registered ${s.name}`,
    invalidate: [["systems"]],
    onDone: onCreated,
  });
  return (
    <form
      className="max-w-xl space-y-4"
      aria-label="Register a system"
      onSubmit={(e) => {
        e.preventDefault();
        if (name.trim()) create.mutate(undefined);
      }}
    >
      <Field id="sys-name" label="System name">
        {(p) => <Input {...p} value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} />}
      </Field>
      <Field id="sys-description" label="What does it do? (optional)">
        {(p) => (
          <Textarea {...p} value={description} onChange={(e) => setDescription(e.target.value)} maxLength={2000} />
        )}
      </Field>
      {me.role === "admin" && (
        <Select
          id="sys-owner"
          label="Owner"
          value={owner}
          onChange={setOwner}
          options={[
            { value: "", label: "Unassigned" },
            ...(team.data ?? [])
              .filter((m) => m.role === "system_owner" || m.role === "analyst" || m.role === "admin")
              .map((m) => ({ value: m.user_id, label: `${m.full_name} (${m.role.replace("_", " ")})` })),
          ]}
        />
      )}
      <Button type="submit" disabled={create.isPending || !name.trim()}>
        {create.isPending ? "Registering..." : "Register and continue"}
      </Button>
    </form>
  );
}

function RecordStep({ systemId, onDone }: { systemId: string; onDone: () => void }) {
  const activities = useActivities();
  const record = (activities.data ?? []).find((a) => a.system_ids.includes(systemId));
  return (
    <div className="space-y-5">
      <RunStep
        systemId={systemId}
        stages={["record"]}
        label="Generate the record"
        description="The record is built from the extracted facts with a template. A language model suggests a purpose and a lawful basis for you to confirm; without a provider those two fields stay empty and are marked as missing."
        doneLabel="Refresh the draft"
        refresh={["activities"]}
        onDone={() => void activities.refetch()}
      />
      {record && (
        <Panel title={record.name} actions={<StatusBadge value={record.status} />}>
          <RecordFields record={record} />
          <div className="mt-4">
            <Button onClick={onDone}>Continue to submit</Button>
          </div>
        </Panel>
      )}
    </div>
  );
}

function SubmitStep({ systemId }: { systemId: string }) {
  const activities = useActivities();
  const navigate = useNavigate();
  const record: Activity | undefined = (activities.data ?? []).find((a) => a.system_ids.includes(systemId));
  const submit = useAction({
    run: () => api.post<Activity>(`/api/v1/activities/${record?.id}/submit`),
    success: "Submitted for approval",
    invalidate: [["activities"], ["activity", record?.id ?? ""]],
    onDone: () => navigate(`/app/records/${record?.id}`),
  });
  if (!record) return <p className="text-muted-foreground">There is no record yet. Go back and generate it.</p>;
  const incomplete = record.missing_fields.length > 0;
  return (
    <div className="space-y-4">
      {incomplete && (
        <Panel title="Complete the missing fields">
          <p className="mb-3 text-sm text-muted-foreground">
            A record cannot be submitted while required fields are empty:{" "}
            {record.missing_fields.join(", ").replaceAll("_", " ")}.
          </p>
          <RecordEdit record={record} onDone={() => void activities.refetch()} />
        </Panel>
      )}
      <p className="text-muted-foreground">
        Submitting sends <strong>{record.name}</strong> to an administrator, who cannot be the person who submitted it.
        {record.missing_fields.length > 0 &&
          ` ${record.missing_fields.length} fields are still missing and will be flagged to the reviewer.`}
      </p>
      <Button
        onClick={() => submit.mutate(undefined)}
        disabled={submit.isPending || record.status !== "draft" || incomplete}
      >
        {record.status === "draft" ? "Submit for approval" : `Already ${record.status.replaceAll("_", " ")}`}
      </Button>
    </div>
  );
}

function ComparisonResults({ systemId }: { systemId: string }) {
  const findings = useFindings({ system_id: systemId });
  const list = findings.data ?? [];
  return (
    <Panel title={`Findings (${list.length})`}>
      {findings.isLoading ? (
        <Skeleton className="h-20" />
      ) : list.length === 0 ? (
        <p className="text-muted-foreground">No conflicts were found.</p>
      ) : (
        <ul className="divide-y divide-border">
          {list.map((f) => (
            <li key={f.id} className="flex flex-wrap items-start justify-between gap-3 py-3">
              <div className="min-w-0">
                <p className="font-medium">{f.title}</p>
                {f.suggested_fix && <p className="text-sm text-muted-foreground">Suggested fix: {f.suggested_fix}</p>}
              </div>
              <SeverityBadge value={f.severity} />
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

export default function AddSystem() {
  usePageMeta("Add a system");
  const [params, setParams] = useSearchParams();
  const resume = params.get("system");
  const [step, setStep] = useState(resume ? 2 : 1);
  const [systemId, setSystemId] = useState<string | null>(resume);
  const system = useSystem(systemId ?? "");
  const evidence = useEvidence(systemId ?? "");

  useEffect(() => {
    if (systemId) setParams({ system: systemId }, { replace: true });
  }, [systemId, setParams]);

  const evidenceCount = (evidence.data ?? []).filter((e) => e.kind !== "privacy_policy").length;
  return (
    <>
      <PageHeader
        title="Add a system"
        description="Seven steps from registration to a record submitted for approval."
      />
      <ol className="mb-6 flex flex-wrap gap-2" aria-label="Steps">
        {STEPS.map((label, i) => {
          const n = i + 1;
          return (
            <li key={label}>
              <button
                type="button"
                disabled={n > 1 && !systemId}
                aria-current={n === step ? "step" : undefined}
                onClick={() => setStep(n)}
                className={cn(
                  "flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm font-medium disabled:opacity-50",
                  n === step ? "border-primary bg-primary text-primary-foreground" : "border-border hover:bg-muted",
                )}
              >
                <span className="grid size-5 place-items-center rounded-full bg-white/20 text-xs font-bold">{n}</span>
                {label}
              </button>
            </li>
          );
        })}
      </ol>
      {systemId && system.data && (
        <p className="mb-4 text-sm text-muted-foreground">
          Working on{" "}
          <Link to={`/app/systems/${systemId}`} className="font-semibold text-primary hover:underline">
            {system.data.name}
          </Link>
        </p>
      )}
      <Panel title={`${step}. ${STEPS[step - 1]}`}>
        {step === 1 && (
          <Register
            onCreated={(s) => {
              setSystemId(s.id);
              setStep(2);
            }}
          />
        )}
        {step === 2 && systemId && (
          <div className="space-y-4">
            <p className="text-muted-foreground">
              Attach what you have: a privacy notice, a questionnaire, a network capture (HAR), a database snapshot
              (SQLite) or a web address on the allowlist. Technical evidence is needed for discovery.
            </p>
            <EvidencePanel systemId={systemId} />
            <Button onClick={() => setStep(3)} disabled={evidenceCount === 0}>
              {evidenceCount === 0 ? "Attach technical evidence to continue" : "Continue to discovery"}
            </Button>
          </div>
        )}
        {step === 3 && systemId && (
          <RunStep
            systemId={systemId}
            stages={["discover", "classify"]}
            label="Run discovery and classification"
            description="Evidence is read as data and never executed. Elements, recipients and trackers are extracted, then each element is classified with rules and embeddings."
            doneLabel="Review the data elements"
            onDone={() => setStep(4)}
          />
        )}
        {step === 4 && systemId && (
          <div className="space-y-4">
            <p className="text-muted-foreground">
              Accept what is right and override what is not. Open an element&apos;s evidence to check the extractor
              output behind it.
            </p>
            <ElementsTable systemId={systemId} />
            <Button onClick={() => setStep(5)}>Continue to the comparison</Button>
          </div>
        )}
        {step === 5 && systemId && (
          <div className="space-y-5">
            <RunStep
              systemId={systemId}
              stages={["fuse"]}
              label="Compare the sources"
              description="The notice, the questionnaire and the technical evidence are compared. Each disagreement becomes a finding with its evidence."
              doneLabel="Show the results"
              refresh={["findings"]}
              onDone={() => void 0}
            />
            <ComparisonResults systemId={systemId} />
            <Button variant="secondary" onClick={() => setStep(6)}>
              Continue to the record
            </Button>
          </div>
        )}
        {step === 6 && systemId && <RecordStep systemId={systemId} onDone={() => setStep(7)} />}
        {step === 7 && systemId && <SubmitStep systemId={systemId} />}
      </Panel>
    </>
  );
}

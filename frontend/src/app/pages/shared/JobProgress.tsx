import { CheckCircle2, Circle, Loader2, XCircle } from "lucide-react";
import { useEffect } from "react";

import { useJob } from "../../hooks/data";
import { formatDateTime } from "../../ui/kit";

const STAGE_LABEL: Record<string, string> = {
  discover: "Discovery",
  classify: "Classification",
  fuse: "Comparison of sources",
  record: "Record draft",
  screen: "Assessment screening",
};

/** Follows a background job: each stage with its state, refreshed while the job runs. */
export function JobProgress({ jobId, onFinished }: { jobId: string | null; onFinished?: (state: string) => void }) {
  const query = useJob(jobId);
  const job = query.data;
  const finished = job?.state === "succeeded" || job?.state === "failed" || job?.state === "cancelled";
  const state = job?.state;
  useEffect(() => {
    if (finished && state) onFinished?.(state);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [finished, state]);
  if (!jobId) return null;
  if (!job)
    return (
      <p aria-busy="true" className="text-sm text-muted-foreground">
        Starting...
      </p>
    );
  const stages = Object.entries(job.stages ?? {});
  return (
    <div className="rounded-lg border border-border bg-card p-4" aria-live="polite">
      <div className="mb-3 flex items-center justify-between text-sm">
        <span className="font-semibold text-navy dark:text-foreground">
          {job.state === "succeeded" ? "Finished" : job.state === "failed" ? "Failed" : "Working"}
        </span>
        <span className="text-muted-foreground">
          {job.progress?.done ?? 0} of {job.progress?.total ?? 0} steps
          {job.finished_at ? `, ${formatDateTime(job.finished_at)}` : ""}
        </span>
      </div>
      <div
        className="mb-4 h-2 overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={job.progress?.total ?? 0}
        aria-valuenow={job.progress?.done ?? 0}
        aria-label="Progress"
      >
        <div
          className="h-2 rounded-full bg-accent transition-all"
          style={{
            width: `${(job.progress?.total ?? 0) ? ((job.progress?.done ?? 0) / (job.progress?.total ?? 0)) * 100 : 0}%`,
          }}
        />
      </div>
      <ul className="space-y-2">
        {stages.map(([name, stage]) => {
          const state = String((stage as { state?: string }).state ?? "pending");
          return (
            <li key={name} className="flex items-center gap-2 text-sm">
              {state === "succeeded" ? (
                <CheckCircle2 aria-hidden="true" className="size-4 text-success" />
              ) : state === "failed" ? (
                <XCircle aria-hidden="true" className="size-4 text-danger" />
              ) : state === "running" ? (
                <Loader2 aria-hidden="true" className="size-4 animate-spin text-primary" />
              ) : (
                <Circle aria-hidden="true" className="size-4 text-muted-foreground" />
              )}
              <span>{STAGE_LABEL[name] ?? name}</span>
              <span className="text-muted-foreground">({state})</span>
            </li>
          );
        })}
      </ul>
      {job.error && (
        <p role="alert" className="mt-3 rounded-md bg-danger/10 p-3 text-sm text-danger">
          {job.error}
        </p>
      )}
    </div>
  );
}

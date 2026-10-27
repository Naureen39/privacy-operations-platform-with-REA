import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, XCircle } from "lucide-react";

import { api } from "@/lib/api";
import { usePageMeta } from "@/lib/queries";
import { PageHero } from "../sections/Common";

function Check({ label, path }: { label: string; path: string }) {
  const { data, isError, isLoading } = useQuery({
    queryKey: ["status", path],
    queryFn: () => api.get<{ status: string }>(path),
    retry: 0,
    refetchInterval: 30_000,
  });
  return (
    <li className="flex items-center justify-between rounded-lg border border-border bg-card p-5 shadow-card">
      <span className="text-lg font-semibold text-navy">{label}</span>
      {isLoading ? (
        <span className="text-muted-foreground">Checking...</span>
      ) : isError ? (
        <span className="inline-flex items-center gap-2 font-semibold text-danger">
          <XCircle aria-hidden="true" className="size-5" /> Unavailable
        </span>
      ) : (
        <span className="inline-flex items-center gap-2 font-semibold text-success">
          <CheckCircle2 aria-hidden="true" className="size-5" />{" "}
          {data?.status === "ok" || data?.status === "ready" ? "Operational" : data?.status}
        </span>
      )}
    </li>
  );
}

export default function Status() {
  usePageMeta("Status", "Live status of the ProcessLedger API and database.");
  return (
    <>
      <PageHero eyebrow="Status" title="System status" lead="Checked from your browser every 30 seconds." />
      <section className="section">
        <div className="container max-w-2xl">
          <ul className="space-y-4">
            <Check label="API" path="/health" />
            <Check label="Database" path="/ready" />
          </ul>
        </div>
      </section>
    </>
  );
}

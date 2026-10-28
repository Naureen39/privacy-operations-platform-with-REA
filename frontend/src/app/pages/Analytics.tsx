import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { usePageMeta } from "@/lib/queries";
import { ChartCard, Sparkline } from "../charts/ChartCard";
import * as C from "../charts/complianceCharts";
import { colorOf } from "../charts/theme";
import { useActivities, useSystems } from "../hooks/data";
import { useRange } from "../hooks/range";
import { ErrorNote } from "../ui/kit";
import { PageHeader } from "../ui/parts";

interface ComplianceSeries {
  series: {
    period: string;
    approved_records: number | null;
    stale_records: number | null;
    requests_open: number | null;
    requests_overdue: number | null;
    discovery_confidence_avg: number | null;
    rea_run_duration_ms_avg: number | null;
    open_findings: { total?: number } | null;
  }[];
  totals: Record<string, number | null>;
  change: Record<string, { absolute: number | null; percent: number | null }> | null;
  simulated: boolean;
}

export function Kpi({
  label,
  value,
  values,
  delta,
  better = "down",
  hint,
}: {
  label: string;
  value: string;
  values: (number | null)[];
  delta?: number | null;
  better?: "up" | "down";
  hint?: string;
}) {
  const tone =
    delta === null || delta === undefined || delta === 0
      ? "text-muted-foreground"
      : delta > 0 === (better === "up")
        ? "text-success"
        : "text-danger";
  return (
    <div className="rounded-lg border border-border bg-card p-4 shadow-card print:break-inside-avoid">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="mt-1">
        <span className="block text-2xl font-bold text-navy dark:text-foreground">{value}</span>
        <Sparkline values={values} label={`${label} over the period`} />
        <span className={`block text-xs font-medium ${tone}`}>
          {delta === null || delta === undefined
            ? (hint ?? "No change data")
            : `${delta > 0 ? "+" : ""}${Number.isInteger(delta) ? delta : delta.toFixed(1)} ${hint ?? "since the start"}`}
        </span>
      </dd>
    </div>
  );
}

export default function Analytics() {
  usePageMeta("Analytics");
  const { range, granularity, compare, controls } = useRange("/api/v1/analytics/compliance");
  const systems = useSystems();
  const activities = useActivities();
  const series = useQuery({
    queryKey: ["analytics", "compliance", range, granularity, compare],
    queryFn: () => api.get<ComplianceSeries>("/api/v1/analytics/compliance", { ...range, granularity, compare }),
  });
  const breakdown = useQuery({
    queryKey: ["analytics", "breakdown", range, granularity],
    queryFn: () => api.get<C.Breakdown>("/api/v1/analytics/compliance/breakdown", { ...range, granularity }),
  });
  const s = series.data?.series ?? [];
  const first = s[0];
  const last = s[s.length - 1];
  const b = breakdown.data;
  const sysCount = (systems.data ?? []).length;
  const covered = new Set(
    (activities.data ?? [])
      .filter((r) => r.status === "approved" || r.status === "published")
      .flatMap((r) => r.system_ids),
  );
  const coverage = sysCount
    ? Math.round(((systems.data ?? []).filter((x) => covered.has(x.id)).length * 100) / sysCount)
    : null;
  const diff = (get: (p: (typeof s)[number]) => number | null | undefined) => {
    const a = first ? get(first) : null;
    const z = last ? get(last) : null;
    return a == null || z == null ? null : z - a;
  };
  const loading = breakdown.isLoading;
  const g = granularity;

  const flow = b ? C.findingsFlow(b.findings, g) : null;
  const sev = b ? C.horizontalBars("Open findings by severity", "Findings", b.findings.open_by_severity) : null;
  const typ = b
    ? C.horizontalBars("Open findings by type", "Findings", b.findings.open_by_type, (k) => colorOf(k))
    : null;
  const law = b ? C.donut("Lawful basis", b.lawful_bases) : null;
  const heat = b ? C.categoryHeatmap(b.category_heatmap) : null;
  const sankey = b ? C.dataFlowSankey(b.data_flow) : null;
  const req = b ? C.requestVolume(b.requests, g) : null;
  const dpia = b ? C.assessmentPipeline(b.assessments) : null;
  const fresh = b ? C.histogram("Days until review", "Records", b.freshness, "#0F62FE") : null;
  const conf = b ? C.histogram("Classification confidence", "Elements", b.confidence, "#007D79") : null;
  const tokens = b ? C.tokensBySystem(b.operations) : null;
  const rea = b ? C.histogram("Evidence type", "Average milliseconds", b.operations.rea_ms_by_kind, "#8A3FFC") : null;
  const mix = b ? C.donut("Extractor mix", b.operations.extractor_mix) : null;

  const card = (
    title: string,
    built: C.Built | null,
    extra: { description?: string; height?: number; className?: string } = {},
  ) => (
    <ChartCard
      title={title}
      option={built?.option ?? null}
      summary={built?.summary ?? ""}
      empty={built?.empty ?? false}
      loading={loading}
      {...extra}
    />
  );

  return (
    <>
      <PageHeader
        title="Analytics"
        description={`Compliance posture from ${range.start} to ${range.end}. Daily snapshots are written overnight; charts below are computed from live data.`}
      />
      {controls}
      {series.isError && <ErrorNote error={series.error} retry={() => void series.refetch()} />}
      {series.data?.simulated && (
        <p className="mb-4 text-xs text-muted-foreground">
          This organization includes simulated history for demonstration.
        </p>
      )}

      <dl className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-5" aria-label="Key figures">
        <Kpi
          label="Record coverage"
          value={coverage === null ? "No data" : `${coverage}%`}
          values={s.map((p) => p.approved_records)}
          delta={diff((p) => p.approved_records)}
          better="up"
          hint="approved records since the start (coverage: systems with an approved record)"
        />
        <Kpi
          label="Stale records"
          value={last?.stale_records != null ? String(last.stale_records) : "No data"}
          values={s.map((p) => p.stale_records)}
          delta={diff((p) => p.stale_records)}
          hint="since the start"
        />
        <Kpi
          label="Open findings"
          value={last?.open_findings?.total != null ? String(last.open_findings.total) : "No data"}
          values={s.map((p) => p.open_findings?.total ?? null)}
          delta={diff((p) => p.open_findings?.total)}
          hint="since the start"
        />
        <Kpi
          label="Discovery confidence"
          value={
            last?.discovery_confidence_avg != null
              ? `${Math.round(Number(last.discovery_confidence_avg) * 100)}%`
              : "No data"
          }
          values={s.map((p) => (p.discovery_confidence_avg == null ? null : Number(p.discovery_confidence_avg)))}
          delta={null}
          hint="average of classified elements"
        />
        <Kpi
          label="Requests on time"
          value={b?.requests.on_time_rate != null ? `${b.requests.on_time_rate}%` : "No data"}
          values={b?.requests.median_days ?? []}
          delta={null}
          hint={b ? `${b.requests.answered} answered` : undefined}
        />
      </dl>
      {series.data?.change && (
        <p className="mb-6 text-sm text-muted-foreground" role="status">
          Compared with the previous period:{" "}
          {["approved_records", "stale_records"]
            .map((k) => {
              const c = series.data?.change?.[k];
              return `${k.replaceAll("_", " ")} ${c?.percent == null ? "no comparison" : `${c.percent > 0 ? "+" : ""}${c.percent}%`}`;
            })
            .join(", ")}
          .
        </p>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        {card("Findings opened and closed", flow, {
          description: "Closed findings are drawn below the axis; the line is the net change.",
          className: "lg:col-span-2",
        })}
        {card("Open findings by severity", sev, { height: 240 })}
        {card("Open findings by type", typ, { height: 240 })}
        {card("Lawful basis of processing activities", law)}
        {card("Data categories by system", heat, { height: 360 })}
        {card("Data flow: systems, vendors and countries", sankey, {
          description: "Vendors in red receive data in a third country without a recorded safeguard.",
          height: 380,
          className: "lg:col-span-2",
        })}
        {card("Request volume and response time", req, { className: "lg:col-span-2" })}
        {card("Assessment pipeline", dpia, { height: 260 })}
        {card("Record freshness", fresh, { height: 260 })}
        {card("Discovery confidence distribution", conf, { height: 260 })}
      </div>

      <section aria-labelledby="ops" className="mt-8">
        <h2 id="ops" className="mb-4 text-xl">
          Operations
        </h2>
        <div className="mb-4 grid gap-4 sm:grid-cols-3">
          <div className="rounded-lg border border-border bg-card p-4">
            <p className="text-sm text-muted-foreground">Model calls</p>
            <p className="text-2xl font-bold">{b?.operations.calls ?? 0}</p>
          </div>
          <div className="rounded-lg border border-border bg-card p-4">
            <p className="text-sm text-muted-foreground">Cache hit rate</p>
            <p className="text-2xl font-bold">
              {b?.operations.cache_hit_rate == null ? "No data" : `${b.operations.cache_hit_rate}%`}
            </p>
          </div>
          <div className="rounded-lg border border-border bg-card p-4">
            <p className="text-sm text-muted-foreground">Failovers and failed calls</p>
            <p className="text-2xl font-bold">{b?.operations.failovers ?? 0}</p>
          </div>
        </div>
        <div className="grid gap-6 lg:grid-cols-2">
          {card("Tokens per system by provider", tokens, { className: "lg:col-span-2" })}
          {card("REA run duration by evidence type", rea, { height: 260 })}
          {card("Extractor mix: REA or fallback parsers", mix, { height: 260 })}
        </div>
      </section>
    </>
  );
}

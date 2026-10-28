import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { usePageMeta } from "@/lib/queries";
import { ChartCard, Sparkline } from "../charts/ChartCard";
import * as R from "../charts/revenueCharts";
import { exactMoney } from "../charts/theme";
import { useRange } from "../hooks/range";
import { DataTable } from "../ui/DataTable";
import { ErrorNote, Money, StatusBadge } from "../ui/kit";
import { PageHeader, Panel } from "../ui/parts";

function Delta({
  change,
  invert = false,
}: {
  change?: { absolute: number | null; percent: number | null };
  invert?: boolean;
}) {
  if (!change || change.percent === null) return <p className="text-xs text-muted-foreground">No comparison</p>;
  const up = change.percent > 0;
  const good = invert ? !up : up;
  return (
    <p
      className={`text-xs font-medium ${change.percent === 0 ? "text-muted-foreground" : good ? "text-success" : "text-danger"}`}
    >
      {up ? "+" : ""}
      {change.percent}% vs previous period
    </p>
  );
}

function Tile({
  label,
  value,
  values,
  change,
  invert,
}: {
  label: string;
  value: string;
  values: (number | null)[];
  change?: { absolute: number | null; percent: number | null };
  invert?: boolean;
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-4 shadow-card print:break-inside-avoid">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="mt-1">
        <span className="block text-2xl font-bold text-navy dark:text-foreground">{value}</span>
        <Sparkline values={values} label={`${label} over the period`} />
        <Delta change={change} invert={invert} />
      </dd>
    </div>
  );
}

export default function Revenue() {
  usePageMeta("Revenue");
  const { range, granularity, compare, controls } = useRange("/api/v1/analytics/revenue", "12m", "month");
  const [waterfall, setWaterfall] = useState(false);
  const series = useQuery({
    queryKey: ["analytics", "revenue", range, granularity, compare],
    queryFn: () => api.get<R.RevenueSeries>("/api/v1/analytics/revenue", { ...range, granularity, compare }),
  });
  const breakdown = useQuery({
    queryKey: ["analytics", "revenue-breakdown"],
    queryFn: () => api.get<R.RevenueBreakdown>("/api/v1/analytics/revenue/breakdown"),
    retry: false,
  });
  const points = series.data?.series ?? [];
  const totals = series.data?.totals ?? {};
  const change = series.data?.change ?? undefined;
  const last = points[points.length - 1];
  const b = breakdown.data;
  const mrr = last?.mrr_cents ?? 0;
  const net =
    (totals.new_mrr_cents ?? 0) +
    (totals.expansion_mrr_cents ?? 0) -
    (totals.contraction_mrr_cents ?? 0) -
    (totals.churned_mrr_cents ?? 0);
  const pct = (bp: number | null | undefined) => (bp == null ? "No data" : `${(bp / 100).toFixed(1)}%`);
  const loading = series.isLoading;
  const refreshing = breakdown.isLoading;

  const built = {
    area: R.mrrArea(points, granularity),
    moves: R.movements(points, granularity, waterfall),
    plan: b ? R.byPlan(b) : null,
    industry: b ? R.byIndustry(b) : null,
    region: b ? R.byRegion(b) : null,
    split: b ? R.subscriptionVsUsage(b) : null,
    cohort: b ? R.cohortHeatmap(b) : null,
    growth: b ? R.growth(b) : null,
    unit: b ? R.unitEconomics(b) : null,
  };
  const card = (
    title: string,
    x: R.EChartsOption | null,
    summary: string,
    empty: boolean,
    load: boolean,
    extra: { description?: string; height?: number; className?: string; actions?: React.ReactNode } = {},
  ) => <ChartCard title={title} option={x} summary={summary} empty={empty} loading={load} {...extra} />;
  const c = (
    title: string,
    bt: { option: R.EChartsOption | null; summary: string; empty: boolean } | null,
    load: boolean,
    extra: { description?: string; height?: number; className?: string; actions?: React.ReactNode } = {},
  ) => card(title, bt?.option ?? null, bt?.summary ?? "", bt?.empty ?? false, load, extra);

  return (
    <>
      <PageHeader
        title="Revenue"
        description="Platform wide recurring revenue, its movements and where it comes from. Visible to administrators of the host organization only."
      />
      {controls}
      {series.isError && <ErrorNote error={series.error} retry={() => void series.refetch()} />}
      {breakdown.isError && <ErrorNote error={breakdown.error} />}
      <dl className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-label="Key figures">
        <Tile
          label="MRR"
          value={loading ? "..." : exactMoney(mrr)}
          values={points.map((p) => p.mrr_cents)}
          {...(change?.mrr_cents ? { change: change.mrr_cents } : {})}
        />
        <Tile
          label="ARR"
          value={loading ? "..." : exactMoney(mrr * 12)}
          values={points.map((p) => p.mrr_cents * 12)}
          {...(change?.mrr_cents ? { change: change.mrr_cents } : {})}
        />
        <Tile
          label="Net new MRR"
          value={loading ? "..." : exactMoney(net)}
          values={points.map(
            (p) => p.new_mrr_cents + p.expansion_mrr_cents - p.contraction_mrr_cents - p.churned_mrr_cents,
          )}
        />
        <Tile
          label="Net revenue retention"
          value={pct(last?.nrr_bp)}
          values={points.map((p) => p.nrr_bp)}
          {...(change?.nrr_bp ? { change: change.nrr_bp } : {})}
        />
        <Tile
          label="Gross churn"
          value={pct(last?.gross_churn_bp)}
          values={points.map((p) => p.gross_churn_bp)}
          invert
          {...(change?.gross_churn_bp ? { change: change.gross_churn_bp } : {})}
        />
        <Tile
          label="ARPA"
          value={loading ? "..." : exactMoney(last?.arpa_cents ?? 0)}
          values={points.map((p) => p.arpa_cents)}
          {...(change?.arpa_cents ? { change: change.arpa_cents } : {})}
        />
        <Tile
          label="Paying accounts"
          value={loading ? "..." : String(last?.paying_accounts ?? 0)}
          values={points.map((p) => p.paying_accounts)}
          {...(change?.paying_accounts ? { change: change.paying_accounts } : {})}
        />
        <Tile
          label="Usage revenue"
          value={loading ? "..." : exactMoney(totals.usage_revenue_cents ?? 0)}
          values={points.map((p) => p.usage_revenue_cents)}
          {...(change?.usage_revenue_cents ? { change: change.usage_revenue_cents } : {})}
        />
      </dl>

      <div className="grid gap-6 lg:grid-cols-2">
        {c("MRR over time", built.area, loading, {
          description: "Solid: measured. Dashed: a straight line projection, not a forecast.",
          className: "lg:col-span-2",
        })}
        {c("MRR movement", built.moves, loading, {
          className: "lg:col-span-2",
          actions: (
            <Button size="sm" variant="secondary" aria-pressed={waterfall} onClick={() => setWaterfall(!waterfall)}>
              {waterfall ? "Show stacked bars" : "Show as waterfall"}
            </Button>
          ),
        })}
        {c("MRR by plan", built.plan, refreshing)}
        {c("MRR by industry", built.industry, refreshing)}
        {c("MRR by region", built.region, refreshing, { height: 260 })}
        {c("Subscription and usage revenue", built.split, refreshing, { height: 260 })}
        {c("Cohort retention", built.cohort, refreshing, {
          description: "Share of each signup cohort that is still paying.",
          height: 340,
          className: "lg:col-span-2",
        })}
        {c("Customer growth and ARPA", built.growth, refreshing)}
        {c("Unit economics", built.unit, refreshing)}
      </div>

      <div className="mt-6 grid gap-6">
        <Panel title="Top 10 customers by MRR">
          <DataTable
            data={b?.top_customers ?? []}
            loading={refreshing}
            caption="Top customers"
            searchPlaceholder="Search customers"
            empty={{ title: "No customers yet" }}
            columns={[
              {
                accessorKey: "name",
                header: "Customer",
                cell: (x) => <span className="font-semibold">{String(x.getValue())}</span>,
              },
              { accessorKey: "industry", header: "Industry" },
              { accessorKey: "region", header: "Region" },
              { accessorKey: "plan", header: "Plan", cell: (x) => <Badge tone="blue">{String(x.getValue())}</Badge> },
              { accessorKey: "mrr_cents", header: "MRR", cell: (x) => <Money cents={Number(x.getValue())} /> },
              {
                id: "trend",
                header: "Last 12 months",
                enableSorting: false,
                cell: ({ row }) => (
                  <div className="w-32">
                    <Sparkline values={row.original.series} label={`${row.original.name} MRR`} />
                  </div>
                ),
              },
            ]}
          />
        </Panel>
        <Panel title="Invoices">
          <DataTable
            data={b?.recent_invoices ?? []}
            loading={refreshing}
            caption="Invoices"
            searchPlaceholder="Search invoices"
            pageSize={10}
            empty={{ title: "No invoices yet" }}
            columns={[
              { accessorKey: "number", header: "Number" },
              { accessorKey: "organization", header: "Customer" },
              { accessorKey: "period_end", header: "Period end" },
              { accessorKey: "total_cents", header: "Total", cell: (x) => <Money cents={Number(x.getValue())} /> },
              { accessorKey: "status", header: "Status", cell: (x) => <StatusBadge value={String(x.getValue())} /> },
            ]}
          />
        </Panel>
      </div>
      <p className="mt-6 text-xs text-muted-foreground" role="note">
        {b?.note ??
          series.data?.note ??
          "Revenue figures are simulated for the demonstration: there are no real customers."}
      </p>
    </>
  );
}

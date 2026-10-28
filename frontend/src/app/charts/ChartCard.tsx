import type { EChartsOption } from "echarts";
import { lazy, Suspense, type ReactNode } from "react";

import { Skeleton } from "../ui/kit";

const Chart = lazy(() => import("./Chart"));

/** A titled chart with the states every chart needs: loading, empty, and a text summary for people
 *  who cannot see it. The summary is a sentence written from the same data as the chart. */
export function ChartCard({
  title,
  description,
  option,
  summary,
  loading = false,
  empty = false,
  emptyText = "There is nothing to show for this period.",
  height = 300,
  actions,
  className,
}: {
  title: string;
  description?: string;
  option: EChartsOption | null;
  summary: string;
  loading?: boolean;
  empty?: boolean;
  emptyText?: string;
  height?: number;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <figure
      className={`m-0 rounded-lg border border-border bg-card p-4 shadow-card print:break-inside-avoid ${className ?? ""}`}
    >
      <div className="mb-2 flex flex-wrap items-start justify-between gap-2">
        <div>
          <figcaption className="text-base font-semibold text-navy dark:text-foreground">{title}</figcaption>
          {description && <p className="text-xs text-muted-foreground">{description}</p>}
        </div>
        {actions}
      </div>
      {loading ? (
        <Skeleton className="w-full" />
      ) : empty || !option ? (
        <div
          className="grid place-items-center rounded-md border border-dashed border-border text-sm text-muted-foreground"
          style={{ height }}
        >
          {emptyText}
        </div>
      ) : (
        <div role="img" aria-label={`${title}. ${summary}`}>
          <Suspense fallback={<div style={{ height }} aria-busy="true" />}>
            <Chart option={option} height={height} />
          </Suspense>
        </div>
      )}
      <p className="mt-2 text-xs text-muted-foreground">{summary}</p>
    </figure>
  );
}

export function Sparkline({
  values,
  label,
  color = "#0F62FE",
}: {
  values: (number | null)[];
  label: string;
  color?: string;
}) {
  const nums = values.filter((v): v is number => v !== null);
  if (nums.length < 2) return <span className="block h-8" aria-hidden="true" />;
  const min = Math.min(...nums);
  const max = Math.max(...nums);
  const span = max - min || 1;
  const points = nums.map((v, i) => `${(i / (nums.length - 1)) * 100},${28 - ((v - min) / span) * 24}`).join(" ");
  return (
    <svg viewBox="0 0 100 32" preserveAspectRatio="none" className="h-8 w-full" role="img" aria-label={label}>
      <polyline points={points} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

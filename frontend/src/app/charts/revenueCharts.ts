import type { EChartsOption } from "echarts";

import type { Built } from "./complianceCharts";
import { AXIS, BASE, colorOf, compactMoney, compactNumber, exactMoney, PALETTE } from "./theme";

/** `GET /analytics/revenue`: one point per day, week or month. */
export interface RevenuePoint {
  period: string;
  last_day: string;
  days: number;
  mrr_cents: number;
  new_mrr_cents: number;
  expansion_mrr_cents: number;
  contraction_mrr_cents: number;
  churned_mrr_cents: number;
  usage_revenue_cents: number;
  accounts: number;
  paying_accounts: number;
  arpa_cents: number;
  nrr_bp: number | null;
  gross_churn_bp: number | null;
}
export interface RevenueSeries {
  start: string;
  end: string;
  granularity: string;
  simulated: boolean;
  series: RevenuePoint[];
  totals: Record<string, number | null>;
  previous: Record<string, number | null> | null;
  change: Record<string, { absolute: number | null; percent: number | null }> | null;
  note: string;
}

/** `GET /analytics/revenue/breakdown`. */
export interface RevenueBreakdown {
  as_of: string;
  months: string[];
  mrr_by_plan: Record<string, number[]>;
  mrr_by_industry: Record<string, number[]>;
  mrr_by_region: Record<string, number[]>;
  subscription_revenue_cents: number[];
  usage_revenue_cents: number[];
  accounts: number[];
  arpa_cents: number[];
  revenue_per_system_cents: number[];
  tokens_per_system: number[];
  cohorts: { labels: string[]; sizes: number[]; retention: (number | null)[][] };
  top_customers: {
    name: string;
    industry: string;
    region: string;
    plan: string;
    mrr_cents: number;
    series: number[];
  }[];
  recent_invoices: { number: string; organization: string; period_end: string; status: string; total_cents: number }[];
  simulated: boolean;
  note: string;
}

const empty = (summary: string): Built => ({ option: null, summary, empty: true });
const monthLabel = (iso: string, granularity: string) => {
  const d = new Date(iso + "T00:00:00");
  return granularity === "month" || granularity === "week" || granularity === "day"
    ? d.toLocaleDateString(
        "en-US",
        granularity === "month" ? { month: "short", year: "2-digit" } : { month: "short", day: "numeric" },
      )
    : iso;
};
const ym = (label: string) => {
  const [y, m] = label.split("-");
  return new Date(Number(y), Number(m) - 1, 1).toLocaleDateString("en-US", { month: "short", year: "2-digit" });
};
const money = (v: unknown) => exactMoney(Number(v));

/** Least squares line through the points, extended `ahead` steps. Returns the future values only. */
export function project(values: number[], ahead = 6): number[] {
  const n = values.length;
  if (n < 3) return [];
  const xs = values.map((_, i) => i);
  const mx = xs.reduce((a, b) => a + b, 0) / n;
  const my = values.reduce((a, b) => a + b, 0) / n;
  const slope =
    xs.reduce((acc, x, i) => acc + (x - mx) * ((values[i] ?? 0) - my), 0) /
    xs.reduce((acc, x) => acc + (x - mx) ** 2, 0);
  const intercept = my - slope * mx;
  return Array.from({ length: ahead }, (_, k) => Math.max(0, Math.round(intercept + slope * (n + k))));
}

function nextMonths(lastIso: string, count: number, granularity: string): string[] {
  const out: string[] = [];
  const d = new Date(lastIso + "T00:00:00");
  for (let i = 0; i < count; i++) {
    if (granularity === "month") d.setMonth(d.getMonth() + 1);
    else if (granularity === "week") d.setDate(d.getDate() + 7);
    else d.setDate(d.getDate() + 1);
    out.push(d.toISOString().slice(0, 10));
  }
  return out;
}

export function mrrArea(points: RevenuePoint[], granularity: string): Built {
  if (points.length === 0) return empty("There are no revenue figures for this period.");
  const x = points.map((p) => monthLabel(p.period, granularity));
  const values = points.map((p) => p.mrr_cents);
  const ahead = project(values, granularity === "month" ? 6 : 6);
  const future = nextMonths(points[points.length - 1]?.period ?? "", ahead.length, granularity).map((p) =>
    monthLabel(p, granularity),
  );
  const last = values[values.length - 1] ?? 0;
  return {
    empty: false,
    summary: `MRR is ${exactMoney(last)} at the end of the period${ahead.length ? `. The dashed line is a projection to ${exactMoney(ahead[ahead.length - 1] ?? 0)} after ${ahead.length} more periods, extending the trend with a straight line` : ""}.`,
    option: {
      ...BASE,
      xAxis: {
        type: "category",
        data: [...x, ...future],
        name: "Period",
        nameLocation: "middle",
        nameGap: 32,
        ...AXIS,
      },
      yAxis: {
        ...AXIS,
        type: "value",
        name: "MRR (US dollars)",
        axisLabel: { formatter: (v: number) => compactMoney(v), color: "#3D4757" },
      },
      tooltip: { ...BASE.tooltip, valueFormatter: money },
      series: [
        {
          name: "MRR",
          type: "line",
          areaStyle: { color: "rgba(15,98,254,0.18)" },
          data: values,
          showSymbol: false,
          lineStyle: { color: PALETTE.blue, width: 2 },
          itemStyle: { color: PALETTE.blue },
        },
        {
          name: "Projection",
          type: "line",
          data: [...values.map(() => null), ...ahead].map((v, i) => (i === values.length - 1 ? last : v)),
          showSymbol: false,
          lineStyle: { color: PALETTE.blue, width: 2, type: "dashed" },
          itemStyle: { color: PALETTE.blue },
        },
      ],
    },
  };
}

export function movements(points: RevenuePoint[], granularity: string, waterfall: boolean): Built {
  if (points.length === 0) return empty("There are no revenue figures for this period.");
  const x = points.map((p) => monthLabel(p.period, granularity));
  const net = points.map(
    (p) => p.new_mrr_cents + p.expansion_mrr_cents - p.contraction_mrr_cents - p.churned_mrr_cents,
  );
  const total = net.reduce((a, b) => a + b, 0);
  const summary = `Net new MRR over the period is ${exactMoney(total)}: new ${exactMoney(points.reduce((a, p) => a + p.new_mrr_cents, 0))}, expansion ${exactMoney(points.reduce((a, p) => a + p.expansion_mrr_cents, 0))}, contraction ${exactMoney(points.reduce((a, p) => a + p.contraction_mrr_cents, 0))}, churn ${exactMoney(points.reduce((a, p) => a + p.churned_mrr_cents, 0))}.`;
  if (waterfall) {
    let running = 0;
    const base: number[] = [];
    const up: (number | string)[] = [];
    const down: (number | string)[] = [];
    for (const v of net) {
      const start = running;
      running += v;
      base.push(Math.min(start, running));
      up.push(v >= 0 ? v : "-");
      down.push(v < 0 ? -v : "-");
    }
    return {
      empty: false,
      summary: `${summary} Shown as a waterfall of the net change in each period.`,
      option: {
        ...BASE,
        xAxis: { type: "category", data: x, name: "Period", nameLocation: "middle", nameGap: 32, ...AXIS },
        yAxis: {
          ...AXIS,
          type: "value",
          name: "Cumulative net new MRR",
          axisLabel: { formatter: (v: number) => compactMoney(v), color: "#3D4757" },
        },
        tooltip: { ...BASE.tooltip, valueFormatter: (v) => (v === "-" ? "" : money(v)) },
        series: [
          {
            name: "Base",
            type: "bar",
            stack: "w",
            itemStyle: { color: "transparent" },
            emphasis: { disabled: true },
            data: base,
            tooltip: { show: false },
          },
          { name: "Increase", type: "bar", stack: "w", itemStyle: { color: colorOf("new") }, data: up },
          { name: "Decrease", type: "bar", stack: "w", itemStyle: { color: colorOf("churn") }, data: down },
        ],
      },
    };
  }
  return {
    empty: false,
    summary,
    option: {
      ...BASE,
      xAxis: { type: "category", data: x, name: "Period", nameLocation: "middle", nameGap: 32, ...AXIS },
      yAxis: {
        ...AXIS,
        type: "value",
        name: "MRR movement (US dollars)",
        axisLabel: { formatter: (v: number) => compactMoney(v), color: "#3D4757" },
      },
      tooltip: { ...BASE.tooltip, valueFormatter: (v) => money(Math.abs(Number(v))) },
      series: [
        {
          name: "New",
          type: "bar",
          stack: "m",
          itemStyle: { color: colorOf("new") },
          data: points.map((p) => p.new_mrr_cents),
        },
        {
          name: "Expansion",
          type: "bar",
          stack: "m",
          itemStyle: { color: colorOf("expansion") },
          data: points.map((p) => p.expansion_mrr_cents),
        },
        {
          name: "Contraction",
          type: "bar",
          stack: "m",
          itemStyle: { color: colorOf("contraction") },
          data: points.map((p) => 0 - p.contraction_mrr_cents),
        },
        {
          name: "Churn",
          type: "bar",
          stack: "m",
          itemStyle: { color: colorOf("churn") },
          data: points.map((p) => 0 - p.churned_mrr_cents),
        },
        {
          name: "Net new",
          type: "line",
          data: net,
          symbol: "circle",
          lineStyle: { color: PALETTE.navy, width: 2 },
          itemStyle: { color: PALETTE.navy },
        },
      ],
    },
  };
}

export function byPlan(b: RevenueBreakdown): Built {
  const plans = Object.keys(b.mrr_by_plan);
  if (plans.length === 0) return empty("No subscriptions yet.");
  const lastTotals = plans.map((p) => `${p} ${exactMoney(b.mrr_by_plan[p]?.[b.months.length - 1] ?? 0)}`);
  return {
    empty: false,
    summary: `MRR by plan at the end of the period: ${lastTotals.join(", ")}.`,
    option: {
      ...BASE,
      xAxis: {
        type: "category",
        data: b.months.map(ym),
        name: "Month",
        nameLocation: "middle",
        nameGap: 32,
        boundaryGap: false,
        ...AXIS,
      },
      yAxis: {
        ...AXIS,
        type: "value",
        name: "MRR (US dollars)",
        axisLabel: { formatter: (v: number) => compactMoney(v), color: "#3D4757" },
      },
      tooltip: { ...BASE.tooltip, valueFormatter: money },
      series: plans.map((p) => ({
        name: p,
        type: "line",
        stack: "plan",
        areaStyle: {},
        showSymbol: false,
        data: b.mrr_by_plan[p],
        lineStyle: { width: 1, color: colorOf(p) },
        itemStyle: { color: colorOf(p) },
      })),
    },
  };
}

export function byIndustry(b: RevenueBreakdown): Built {
  const rows = Object.entries(b.mrr_by_industry)
    .map(([name, series]) => ({ name, value: series[series.length - 1] ?? 0 }))
    .filter((r) => r.value > 0);
  if (rows.length === 0) return empty("No subscriptions yet.");
  const total = rows.reduce((a, r) => a + r.value, 0);
  return {
    empty: false,
    summary: `MRR by industry: ${[...rows]
      .sort((a, c) => c.value - a.value)
      .map((r) => `${r.name} ${exactMoney(r.value)} (${Math.round((r.value * 100) / total)}%)`)
      .join(", ")}.`,
    option: {
      ...BASE,
      tooltip: { trigger: "item", confine: true, valueFormatter: money },
      series: [
        {
          type: "treemap",
          roam: false,
          nodeClick: false,
          breadcrumb: { show: false },
          label: {
            color: "#fff",
            formatter: (p: unknown) =>
              `${(p as { name: string }).name}\n${compactMoney((p as { value: number }).value)}`,
          },
          data: rows.map((r, i) => ({
            ...r,
            itemStyle: { color: [PALETTE.blue, PALETTE.teal, PALETTE.purple, PALETTE.magenta, PALETTE.navy][i % 5] },
          })),
        },
      ],
    },
  };
}

export function byRegion(b: RevenueBreakdown): Built {
  const rows = Object.entries(b.mrr_by_region)
    .map(([name, s]) => [name, s[s.length - 1] ?? 0] as const)
    .filter(([, v]) => v > 0)
    .sort((a, c) => a[1] - c[1]);
  if (rows.length === 0) return empty("No subscriptions yet.");
  return {
    empty: false,
    summary: `MRR by region: ${[...rows]
      .reverse()
      .map(([n, v]) => `${n} ${exactMoney(v)}`)
      .join(", ")}.`,
    option: {
      ...BASE,
      grid: { left: 16, right: 56, top: 16, bottom: 40, containLabel: true },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, confine: true, valueFormatter: money },
      xAxis: {
        ...AXIS,
        type: "value",
        name: "MRR (US dollars)",
        nameLocation: "middle",
        nameGap: 28,
        axisLabel: { formatter: (v: number) => compactMoney(v), color: "#3D4757" },
      },
      yAxis: { type: "category", data: rows.map(([n]) => n), ...AXIS },
      series: [
        {
          type: "bar",
          data: rows.map(([, v]) => v),
          itemStyle: { color: PALETTE.teal },
          label: {
            show: true,
            position: "right",
            formatter: (p: unknown) => compactMoney((p as { value: number }).value),
            color: "#161E2D",
          },
        },
      ],
    },
  };
}

export function subscriptionVsUsage(b: RevenueBreakdown): Built {
  if (b.months.length === 0) return empty("No revenue yet.");
  const sub = b.subscription_revenue_cents.reduce((a, v) => a + v, 0);
  const use = b.usage_revenue_cents.reduce((a, v) => a + v, 0);
  return {
    empty: false,
    summary: `Over ${b.months.length} months, subscription MRR adds up to ${exactMoney(sub)} and usage revenue to ${exactMoney(use)}.`,
    option: {
      ...BASE,
      xAxis: { type: "category", data: b.months.map(ym), name: "Month", nameLocation: "middle", nameGap: 32, ...AXIS },
      yAxis: {
        ...AXIS,
        type: "value",
        name: "Revenue (US dollars)",
        axisLabel: { formatter: (v: number) => compactMoney(v), color: "#3D4757" },
      },
      tooltip: { ...BASE.tooltip, valueFormatter: money },
      series: [
        {
          name: "Subscription",
          type: "bar",
          stack: "r",
          data: b.subscription_revenue_cents,
          itemStyle: { color: colorOf("subscription") },
        },
        { name: "Usage", type: "bar", stack: "r", data: b.usage_revenue_cents, itemStyle: { color: colorOf("usage") } },
      ],
    },
  };
}

export function cohortHeatmap(b: RevenueBreakdown): Built {
  const { labels, retention } = b.cohorts;
  if (labels.length === 0) return empty("No cohorts yet.");
  const width = Math.max(...retention.map((r) => r.length), 0);
  const cells: [number, number, number][] = [];
  retention.forEach((row, y) => row.forEach((v, x) => v !== null && cells.push([x, y, v])));
  const month6 = retention.map((r) => r[6]).filter((v): v is number => typeof v === "number");
  return {
    empty: false,
    summary: `Share of each signup cohort still paying, by months since signup${month6.length ? `. After six months the average is ${Math.round(month6.reduce((a, v) => a + v, 0) / month6.length)}%` : ""}.`,
    option: {
      ...BASE,
      grid: { left: 16, right: 24, top: 16, bottom: 72, containLabel: true },
      tooltip: {
        trigger: "item",
        confine: true,
        formatter: (p: unknown) => {
          const v = (p as { value: number[] }).value;
          return `${labels[v[1] ?? 0]} cohort, month ${v[0]}: ${v[2]}% still paying`;
        },
      },
      xAxis: {
        type: "category",
        data: Array.from({ length: width }, (_, i) => String(i)),
        name: "Months since signup",
        nameLocation: "middle",
        nameGap: 30,
        ...AXIS,
      },
      yAxis: { type: "category", data: labels.map(ym), name: "Signup month", ...AXIS },
      visualMap: {
        min: 0,
        max: 100,
        orient: "horizontal",
        left: "center",
        bottom: 0,
        inRange: { color: ["#FFF1F1", "#EDF5FF", "#0F62FE"] },
        text: ["100%", "0%"],
        textStyle: { color: "#161E2D" },
      },
      series: [
        {
          type: "heatmap",
          data: cells,
          label: {
            show: width <= 14,
            color: "#161E2D",
            formatter: (p: unknown) => `${(p as { value: number[] }).value[2]}`,
          },
        },
      ],
    },
  };
}

export function growth(b: RevenueBreakdown): Built {
  if (b.months.length === 0) return empty("No customers yet.");
  return {
    empty: false,
    summary: `Accounts grew from ${b.accounts[0]} to ${b.accounts[b.accounts.length - 1]}; ARPA moved from ${exactMoney(b.arpa_cents[0] ?? 0)} to ${exactMoney(b.arpa_cents[b.arpa_cents.length - 1] ?? 0)}.`,
    option: {
      ...BASE,
      xAxis: { type: "category", data: b.months.map(ym), name: "Month", nameLocation: "middle", nameGap: 32, ...AXIS },
      yAxis: [
        { type: "value", name: "Accounts", minInterval: 1, ...AXIS },
        {
          ...AXIS,
          type: "value",
          name: "ARPA (US dollars)",
          axisLabel: { formatter: (v: number) => compactMoney(v), color: "#3D4757" },
          splitLine: { show: false },
        },
      ],
      series: [
        { name: "Accounts", type: "bar", data: b.accounts, itemStyle: { color: PALETTE.blue } },
        {
          name: "ARPA",
          type: "line",
          yAxisIndex: 1,
          data: b.arpa_cents,
          showSymbol: false,
          lineStyle: { color: PALETTE.magenta, width: 2 },
          itemStyle: { color: PALETTE.magenta },
          tooltip: { valueFormatter: money },
        },
      ],
    },
  };
}

export function unitEconomics(b: RevenueBreakdown): Built {
  if (b.months.length === 0) return empty("No usage yet.");
  const last = b.months.length - 1;
  return {
    empty: false,
    summary: `Revenue per system is ${exactMoney(b.revenue_per_system_cents[last] ?? 0)} a month and the platform uses ${compactNumber(b.tokens_per_system[last] ?? 0)} tokens per system.`,
    option: {
      ...BASE,
      xAxis: { type: "category", data: b.months.map(ym), name: "Month", nameLocation: "middle", nameGap: 32, ...AXIS },
      yAxis: [
        {
          ...AXIS,
          type: "value",
          name: "Revenue per system (US dollars)",
          axisLabel: { formatter: (v: number) => compactMoney(v), color: "#3D4757" },
        },
        {
          ...AXIS,
          type: "value",
          name: "Tokens per system",
          axisLabel: { formatter: (v: number) => compactNumber(v), color: "#3D4757" },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: "Revenue per system",
          type: "line",
          data: b.revenue_per_system_cents,
          showSymbol: false,
          lineStyle: { color: PALETTE.green, width: 2 },
          itemStyle: { color: PALETTE.green },
          tooltip: { valueFormatter: money },
        },
        {
          name: "Tokens per system",
          type: "line",
          yAxisIndex: 1,
          data: b.tokens_per_system,
          showSymbol: false,
          lineStyle: { color: PALETTE.purple, width: 2, type: "dashed" },
          itemStyle: { color: PALETTE.purple },
        },
      ],
    },
  };
}

export type { EChartsOption };

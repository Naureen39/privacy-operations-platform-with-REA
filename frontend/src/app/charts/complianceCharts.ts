import type { EChartsOption } from "echarts";

import { AXIS, BASE, colorOf, compactNumber } from "./theme";

/** The shapes the compliance breakdown endpoint returns (`GET /analytics/compliance/breakdown`). */
export interface FindingsFlow {
  periods: string[];
  opened: number[];
  closed: number[];
  net: number[];
  open_by_severity: Record<string, number>;
  open_by_type: Record<string, number>;
}
export interface Heatmap {
  systems: string[];
  categories: string[];
  cells: [string, string, number][];
}
export interface DataFlow {
  nodes: { name: string; kind: "system" | "vendor" | "country"; gap: boolean }[];
  links: { source: string; target: string; value: number }[];
  gaps: string[];
}
export interface RequestVolume {
  periods: string[];
  received: number[];
  median_days: (number | null)[];
  answered: number;
  on_time_rate: number | null;
}
export interface Operations {
  tokens_by_system: Record<string, Record<string, number>>;
  calls: number;
  cache_hit_rate: number | null;
  failovers: number;
  rea_ms_by_kind: Record<string, number>;
  extractor_mix: Record<string, number>;
}
export interface Breakdown {
  start: string;
  end: string;
  granularity: string;
  findings: FindingsFlow;
  lawful_bases: Record<string, number>;
  category_heatmap: Heatmap;
  data_flow: DataFlow;
  requests: RequestVolume;
  assessments: Record<string, number>;
  freshness: Record<string, number>;
  confidence: Record<string, number>;
  operations: Operations;
}

export interface Built {
  option: EChartsOption | null;
  summary: string;
  empty: boolean;
}

const sum = (values: number[]) => values.reduce((a, b) => a + b, 0);
const label = (key: string) => key.replaceAll("_", " ");
const empty = (summary: string): Built => ({ option: null, summary, empty: true });

function periodLabel(iso: string, granularity: string): string {
  const d = new Date(iso + "T00:00:00");
  if (granularity === "month") return d.toLocaleDateString("en-US", { month: "short", year: "2-digit" });
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function findingsFlow(f: FindingsFlow, granularity: string): Built {
  const opened = sum(f.opened);
  const closed = sum(f.closed);
  if (opened + closed === 0) return empty("No findings were opened or closed in this period.");
  const x = f.periods.map((p) => periodLabel(p, granularity));
  return {
    empty: false,
    summary: `${opened} findings opened and ${closed} closed, a net change of ${opened - closed}.`,
    option: {
      ...BASE,
      xAxis: { type: "category", data: x, name: "Period", nameLocation: "middle", nameGap: 32, ...AXIS },
      yAxis: { type: "value", name: "Findings", ...AXIS },
      series: [
        { name: "Opened", type: "bar", stack: "flow", data: f.opened, itemStyle: { color: colorOf("opened") } },
        {
          name: "Closed",
          type: "bar",
          stack: "flow",
          data: f.closed.map((v) => 0 - v),
          itemStyle: { color: colorOf("closed") },
        },
        {
          name: "Net",
          type: "line",
          data: f.net,
          symbol: "circle",
          lineStyle: { color: colorOf("net"), width: 2 },
          itemStyle: { color: colorOf("net") },
        },
      ],
      tooltip: { ...BASE.tooltip, valueFormatter: (v) => String(Math.abs(Number(v))) },
    },
  };
}

export function horizontalBars(
  title: string,
  unit: string,
  data: Record<string, number>,
  colorFor: (k: string) => string = colorOf,
): Built {
  const entries = Object.entries(data).filter(([, v]) => v > 0);
  if (entries.length === 0) return empty(`No ${title.toLowerCase()} to show.`);
  const sorted = [...entries].sort((a, b) => a[1] - b[1]);
  return {
    empty: false,
    summary: `${title}: ${[...entries]
      .sort((a, b) => b[1] - a[1])
      .map(([k, v]) => `${label(k)} ${v}`)
      .join(", ")}.`,
    option: {
      ...BASE,
      grid: { left: 16, right: 24, top: 16, bottom: 36, containLabel: true },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, confine: true },
      xAxis: { type: "value", name: unit, nameLocation: "middle", nameGap: 26, ...AXIS },
      yAxis: { type: "category", data: sorted.map(([k]) => label(k)), ...AXIS },
      series: [
        {
          type: "bar",
          data: sorted.map(([k, v]) => ({ value: v, itemStyle: { color: colorFor(k) } })),
          label: { show: true, position: "right", color: "#161E2D" },
        },
      ],
    },
  };
}

export function donut(title: string, data: Record<string, number>, colorFor: (k: string) => string = colorOf): Built {
  const entries = Object.entries(data).filter(([, v]) => v > 0);
  const total = sum(entries.map(([, v]) => v));
  if (total === 0) return empty(`No data for ${title.toLowerCase()}.`);
  return {
    empty: false,
    summary: `${title}: ${entries.map(([k, v]) => `${label(k)} ${v} (${Math.round((v * 100) / total)}%)`).join(", ")}.`,
    option: {
      ...BASE,
      tooltip: { trigger: "item", confine: true, formatter: "{b}: {c} ({d}%)" },
      legend: { bottom: 0, textStyle: { color: "#161E2D" } },
      series: [
        {
          type: "pie",
          radius: ["45%", "70%"],
          center: ["50%", "44%"],
          avoidLabelOverlap: true,
          label: { color: "#161E2D", formatter: "{c}" },
          data: entries.map(([k, v]) => ({ name: label(k), value: v, itemStyle: { color: colorFor(k) } })),
        },
      ],
    },
  };
}

export function categoryHeatmap(h: Heatmap): Built {
  if (h.cells.length === 0) return empty("No classified data elements yet.");
  const max = Math.max(...h.cells.map((c) => c[2]));
  return {
    empty: false,
    summary: `${h.systems.length} systems and ${h.categories.length} data categories. The most common cell holds ${max} elements.`,
    option: {
      ...BASE,
      grid: { left: 16, right: 24, top: 16, bottom: 72, containLabel: true },
      tooltip: {
        trigger: "item",
        confine: true,
        formatter: (p: unknown) => {
          const v = (p as { value: [string, string, number] }).value;
          return `${v[0]} / ${v[1]}: ${v[2]} elements`;
        },
      },
      xAxis: {
        type: "category",
        data: h.categories.map(label),
        name: "Data category",
        nameLocation: "middle",
        nameGap: 56,
        axisLabel: { rotate: 35, color: "#3D4757" },
        splitArea: { show: true },
      },
      yAxis: { type: "category", data: h.systems, name: "System", ...AXIS },
      visualMap: {
        min: 0,
        max,
        calculable: false,
        orient: "horizontal",
        left: "center",
        bottom: 0,
        inRange: { color: ["#EDF5FF", "#0F62FE", "#0B1F3A"] },
        text: ["More", "Fewer"],
        textStyle: { color: "#161E2D" },
      },
      series: [
        {
          type: "heatmap",
          data: h.cells.map(([s, c, n]) => [h.categories.indexOf(c), h.systems.indexOf(s), n, s, c]),
          label: { show: true, color: "#161E2D" },
        },
      ],
    },
  };
}

export function dataFlowSankey(df: DataFlow): Built {
  if (df.links.length === 0) return empty("No recipients were found in the evidence.");
  const gaps = new Set(df.gaps);
  const kindColor = { system: "#0F62FE", vendor: "#8A3FFC", country: "#007D79" } as const;
  return {
    empty: false,
    summary: `${df.nodes.filter((n) => n.kind === "system").length} systems send data to ${df.nodes.filter((n) => n.kind === "vendor").length} vendors in ${df.nodes.filter((n) => n.kind === "country").length} countries. ${df.gaps.length === 0 ? "No transfer is missing a safeguard." : `Transfers without a safeguard: ${df.gaps.join(", ")}.`}`,
    option: {
      ...BASE,
      tooltip: { trigger: "item", confine: true },
      series: [
        {
          type: "sankey",
          left: 8,
          right: 90,
          top: 8,
          bottom: 8,
          emphasis: { focus: "adjacency" },
          data: df.nodes.map((n) => ({
            name: n.name,
            itemStyle: {
              color: n.gap ? "#DA1E28" : kindColor[n.kind],
              borderColor: n.gap ? "#A2191F" : undefined,
              borderWidth: n.gap ? 2 : 0,
            },
            label: { color: "#161E2D", fontWeight: n.gap ? 700 : 400 },
          })),
          links: df.links.map((l) => ({
            ...l,
            lineStyle: { color: gaps.has(l.source) || gaps.has(l.target) ? "#DA1E28" : "source", opacity: 0.45 },
          })),
        },
      ],
    },
  };
}

export function requestVolume(r: RequestVolume, granularity: string): Built {
  if (sum(r.received) === 0 && r.answered === 0) return empty("No access requests were received in this period.");
  const x = r.periods.map((p) => periodLabel(p, granularity));
  return {
    empty: false,
    summary: `${sum(r.received)} requests received and ${r.answered} answered${r.on_time_rate === null ? "" : `, ${r.on_time_rate}% of them within the deadline`}.`,
    option: {
      ...BASE,
      xAxis: { type: "category", data: x, name: "Period", nameLocation: "middle", nameGap: 32, ...AXIS },
      yAxis: [
        { type: "value", name: "Requests", minInterval: 1, ...AXIS },
        { ...AXIS, type: "value", name: "Median days to respond", splitLine: { show: false } },
      ],
      series: [
        { name: "Received", type: "bar", data: r.received, itemStyle: { color: "#0F62FE" } },
        {
          name: "Median days to respond",
          type: "line",
          yAxisIndex: 1,
          data: r.median_days,
          connectNulls: true,
          symbol: "circle",
          lineStyle: { color: "#8A3FFC", width: 2 },
          itemStyle: { color: "#8A3FFC" },
        },
      ],
    },
  };
}

export function histogram(title: string, unit: string, data: Record<string, number>, color = "#0F62FE"): Built {
  const keys = Object.keys(data);
  const total = sum(Object.values(data));
  if (total === 0) return empty(`No data for ${title.toLowerCase()}.`);
  return {
    empty: false,
    summary: `${title}: ${keys.map((k) => `${label(k)} ${data[k]}`).join(", ")}.`,
    option: {
      ...BASE,
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, confine: true },
      xAxis: { type: "category", data: keys.map(label), name: title, nameLocation: "middle", nameGap: 32, ...AXIS },
      yAxis: { type: "value", name: unit, minInterval: 1, ...AXIS },
      series: [
        {
          type: "bar",
          data: keys.map((k) => data[k] ?? 0),
          itemStyle: { color },
          label: { show: true, position: "top", color: "#161E2D" },
        },
      ],
    },
  };
}

export function assessmentPipeline(map: Record<string, number>): Built {
  const order = ["draft", "in_review", "approved", "rejected"];
  const total = sum(Object.values(map));
  if (total === 0) return empty("No impact assessments yet.");
  return {
    empty: false,
    summary: `Assessments by status: ${order.map((k) => `${label(k)} ${map[k] ?? 0}`).join(", ")}.`,
    option: {
      ...BASE,
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, confine: true },
      xAxis: { type: "category", data: order.map(label), name: "Status", nameLocation: "middle", nameGap: 32, ...AXIS },
      yAxis: { type: "value", name: "Assessments", minInterval: 1, ...AXIS },
      series: [
        {
          type: "bar",
          data: order.map((k) => ({ value: map[k] ?? 0, itemStyle: { color: colorOf(k) } })),
          label: { show: true, position: "top", color: "#161E2D" },
        },
      ],
    },
  };
}

export function tokensBySystem(ops: Operations): Built {
  const systems = Object.keys(ops.tokens_by_system);
  const providers = [...new Set(systems.flatMap((s) => Object.keys(ops.tokens_by_system[s] ?? {})))].sort();
  const total = sum(systems.flatMap((s) => Object.values(ops.tokens_by_system[s] ?? {})));
  if (total === 0) return empty("No model tokens were used in this period.");
  return {
    empty: false,
    summary: `${compactNumber(total)} tokens used across ${systems.length} systems; providers: ${providers.join(", ")}.`,
    option: {
      ...BASE,
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        confine: true,
        valueFormatter: (v) => compactNumber(Number(v)),
      },
      xAxis: { type: "category", data: systems, name: "System", nameLocation: "middle", nameGap: 32, ...AXIS },
      yAxis: {
        ...AXIS,
        type: "value",
        name: "Tokens",
        axisLabel: { formatter: (v: number) => compactNumber(v), color: "#3D4757" },
      },
      series: providers.map((p) => ({
        name: p,
        type: "bar",
        stack: "tokens",
        data: systems.map((s) => ops.tokens_by_system[s]?.[p] ?? 0),
        itemStyle: { color: colorOf(p) },
      })),
    },
  };
}

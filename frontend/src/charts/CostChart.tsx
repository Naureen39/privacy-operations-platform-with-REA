import { LineChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import ReactEChartsCore from "echarts-for-react/lib/core";

import { estimate, formatMoney, type Plan } from "@/lib/plans";

echarts.use([LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer]);

const COLORS: Record<string, string> = { starter: "#525E71", professional: "#0F62FE", enterprise: "#0B1F3A" };

/** Monthly cost of each plan as the number of systems grows (requests held at the chosen value). */
export default function CostChart({
  plans,
  requests,
  maxSystems = 200,
}: {
  plans: Plan[];
  requests: number;
  maxSystems?: number;
}) {
  const xs = Array.from({ length: maxSystems / 5 + 1 }, (_, i) => i * 5);
  const option = {
    animation: !window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    grid: { left: 64, right: 16, top: 40, bottom: 40 },
    tooltip: {
      trigger: "axis",
      valueFormatter: (v: number | null) => (v === null ? "Exceeds the plan" : formatMoney(Number(v))),
    },
    legend: { top: 0, textStyle: { color: "#161E2D" } },
    xAxis: { type: "category", data: xs, name: "Systems", nameLocation: "middle", nameGap: 28 },
    yAxis: { type: "value", axisLabel: { formatter: (v: number) => formatMoney(v * 100) } },
    series: plans.map((p) => ({
      name: p.name,
      type: "line",
      showSymbol: false,
      lineStyle: { width: 3, color: COLORS[p.code] ?? "#0F62FE" },
      itemStyle: { color: COLORS[p.code] ?? "#0F62FE" },
      data: xs.map((s) => {
        const e = estimate(p, s, requests);
        return e.fits ? e.totalCents / 100 : null;
      }),
    })),
  };
  return (
    <ReactEChartsCore
      echarts={echarts}
      option={option}
      style={{ height: 320, width: "100%" }}
      opts={{ renderer: "canvas" }}
      notMerge
    />
  );
}

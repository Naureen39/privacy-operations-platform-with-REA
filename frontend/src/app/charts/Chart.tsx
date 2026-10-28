import ReactEChartsCore from "echarts-for-react/lib/core";
import type { EChartsOption } from "echarts";

import { echarts } from "./echarts";

/** The ECharts canvas. It is imported lazily by ChartCard, so pages without charts never load it. */
export default function Chart({ option, height }: { option: EChartsOption; height: number }) {
  const reduce = typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  return (
    <ReactEChartsCore
      echarts={echarts}
      option={{ animation: !reduce, ...option }}
      style={{ height, width: "100%" }}
      opts={{ renderer: "canvas" }}
      notMerge
      lazyUpdate
    />
  );
}

import { BarChart, HeatmapChart, LineChart, PieChart, SankeyChart, TreemapChart } from "echarts/charts";
import {
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TooltipComponent,
  VisualMapComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";

// Only what the dashboards use is registered, so the chart chunk stays as small as it can.
echarts.use([
  BarChart,
  LineChart,
  PieChart,
  HeatmapChart,
  SankeyChart,
  TreemapChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  VisualMapComponent,
  MarkLineComponent,
  CanvasRenderer,
]);

export { echarts };

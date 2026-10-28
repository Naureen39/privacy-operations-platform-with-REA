import { rangeFor } from "../hooks/range";
import * as C from "./complianceCharts";
import * as R from "./revenueCharts";
import { colorOf, compactMoney, compactNumber, SERIES_COLOR } from "./theme";

type Series = {
  name?: string;
  type?: string;
  data?: unknown[];
  stack?: string;
  itemStyle?: { color?: string };
  lineStyle?: { type?: string };
};
const seriesOf = (b: C.Built): Series[] => (b.option?.series ?? []) as Series[];

const point = (period: string, over: Partial<R.RevenuePoint> = {}): R.RevenuePoint => ({
  period,
  last_day: period,
  days: 30,
  mrr_cents: 100_000,
  new_mrr_cents: 0,
  expansion_mrr_cents: 0,
  contraction_mrr_cents: 0,
  churned_mrr_cents: 0,
  usage_revenue_cents: 0,
  accounts: 5,
  paying_accounts: 4,
  arpa_cents: 25_000,
  nrr_bp: 10_000,
  gross_churn_bp: 100,
  ...over,
});

describe("series colors", () => {
  it("uses one color per name everywhere and a stable fallback for unknown names", () => {
    expect(colorOf("high")).toBe(SERIES_COLOR.high);
    expect(colorOf("groq")).toBe(SERIES_COLOR.groq);
    expect(colorOf("some other series")).toBe(colorOf("some other series"));
    expect(new Set(["critical", "high", "medium", "low"].map(colorOf)).size).toBe(4);
  });

  it("formats numbers compactly", () => {
    expect(compactNumber(12_500)).toBe("12.5K");
    expect(compactMoney(250_000_00)).toBe("$250K");
  });
});

describe("compliance charts", () => {
  it("draws closed findings below the axis with a net line, and says so in text", () => {
    const flow = {
      periods: ["2026-01-01", "2026-02-01"],
      opened: [5, 3],
      closed: [2, 4],
      net: [3, -1],
      open_by_severity: {},
      open_by_type: {},
    };
    const built = C.findingsFlow(flow, "month");
    const [opened, closed, net] = seriesOf(built);
    expect(opened?.data).toEqual([5, 3]);
    expect(closed?.data).toEqual([-2, -4]);
    expect(net?.type).toBe("line");
    expect(net?.data).toEqual([3, -1]);
    expect(opened?.itemStyle?.color).toBe(colorOf("opened"));
    expect(built.summary).toBe("8 findings opened and 6 closed, a net change of 2.");
  });

  it("shows an empty state instead of an empty chart", () => {
    expect(
      C.findingsFlow({ periods: [], opened: [], closed: [], net: [], open_by_severity: {}, open_by_type: {} }, "day")
        .empty,
    ).toBe(true);
    expect(C.donut("Lawful basis", {}).empty).toBe(true);
    expect(C.categoryHeatmap({ systems: [], categories: [], cells: [] }).empty).toBe(true);
    expect(C.dataFlowSankey({ nodes: [], links: [], gaps: [] }).empty).toBe(true);
    expect(
      C.tokensBySystem({
        tokens_by_system: {},
        calls: 0,
        cache_hit_rate: null,
        failovers: 0,
        rea_ms_by_kind: {},
        extractor_mix: {},
      }).empty,
    ).toBe(true);
  });

  it("colors severities the same in the bars and the donut", () => {
    const bars = C.horizontalBars("Open findings by severity", "Findings", { high: 3, low: 1 });
    const data = seriesOf(bars)[0]?.data as { value: number; itemStyle: { color: string } }[];
    expect(data.map((d) => d.itemStyle.color)).toEqual([colorOf("low"), colorOf("high")]); // sorted ascending
    const pie = seriesOf(C.donut("Severity", { high: 3, low: 1 }, colorOf))[0]?.data as {
      name: string;
      itemStyle: { color: string };
    }[];
    expect(pie.find((d) => d.name === "high")?.itemStyle.color).toBe(colorOf("high"));
    expect(bars.summary).toContain("high 3");
  });

  it("highlights vendors that receive data in a third country without a safeguard", () => {
    const built = C.dataFlowSankey({
      nodes: [
        { name: "Web shop", kind: "system", gap: false },
        { name: "AdCo", kind: "vendor", gap: true },
        { name: "US", kind: "country", gap: false },
      ],
      links: [
        { source: "Web shop", target: "AdCo", value: 1 },
        { source: "AdCo", target: "US", value: 1 },
      ],
      gaps: ["AdCo"],
    });
    const nodes = seriesOf(built)[0]?.data as { name: string; itemStyle: { color: string } }[];
    expect(nodes.find((n) => n.name === "AdCo")?.itemStyle.color).toBe("#DA1E28");
    expect(nodes.find((n) => n.name === "Web shop")?.itemStyle.color).not.toBe("#DA1E28");
    expect(built.summary).toContain("Transfers without a safeguard: AdCo.");
  });

  it("stacks tokens by provider per system", () => {
    const built = C.tokensBySystem({
      tokens_by_system: { Shop: { groq: 1200, gemini: 300 }, CRM: { groq: 500 } },
      calls: 4,
      cache_hit_rate: 25,
      failovers: 1,
      rea_ms_by_kind: {},
      extractor_mix: {},
    });
    const s = seriesOf(built);
    expect(s.map((x) => x.name)).toEqual(["gemini", "groq"]);
    expect(s.every((x) => x.stack === "tokens")).toBe(true);
    expect(s.find((x) => x.name === "groq")?.data).toEqual([1200, 500]);
  });

  it("puts the heatmap cells at the right coordinates", () => {
    const built = C.categoryHeatmap({
      systems: ["A", "B"],
      categories: ["email", "phone"],
      cells: [
        ["B", "email", 3],
        ["A", "phone", 1],
      ],
    });
    const data = seriesOf(built)[0]?.data as unknown[][];
    expect(data.map((d) => d.slice(0, 3))).toEqual([
      [0, 1, 3],
      [1, 0, 1],
    ]);
  });

  it("describes request volume with the on time rate", () => {
    const built = C.requestVolume(
      { periods: ["2026-01-01"], received: [4], median_days: [9], answered: 3, on_time_rate: 100 },
      "month",
    );
    expect(built.summary).toBe("4 requests received and 3 answered, 100% of them within the deadline.");
  });
});

describe("revenue charts", () => {
  it("projects a straight trend six periods ahead and draws it dashed", () => {
    expect(R.project([100, 200, 300, 400])).toEqual([500, 600, 700, 800, 900, 1000]);
    expect(R.project([100, 200])).toEqual([]);
    expect(R.project([500, 400, 300, 200, 100])).toEqual([0, 0, 0, 0, 0, 0]); // never negative
    const pts = ["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01"].map((p, i) =>
      point(p, { mrr_cents: (i + 1) * 100_00 }),
    );
    const built = R.mrrArea(pts, "month");
    const [measured, projection] = seriesOf(built);
    expect(measured?.data).toEqual([10_000, 20_000, 30_000, 40_000]);
    expect(projection?.lineStyle?.type).toBe("dashed");
    expect(projection?.data?.length).toBe(10);
    expect(built.summary).toContain("projection");
  });

  it("makes the waterfall add up to the net new MRR", () => {
    const pts = [
      point("2026-01-01", { new_mrr_cents: 500, churned_mrr_cents: 100 }),
      point("2026-02-01", { expansion_mrr_cents: 300, contraction_mrr_cents: 700 }),
    ];
    const stacked = R.movements(pts, "month", false);
    expect(seriesOf(stacked).map((s) => s.name)).toEqual(["New", "Expansion", "Contraction", "Churn", "Net new"]);
    expect(seriesOf(stacked)[2]?.data).toEqual([0, -700]);
    expect(seriesOf(stacked)[4]?.data).toEqual([400, -400]);
    const fall = R.movements(pts, "month", true);
    const [base, up, down] = seriesOf(fall);
    expect(base?.data).toEqual([0, 0]); // 0 to 400, then 400 down to 0
    expect(up?.data).toEqual([400, "-"]);
    expect(down?.data).toEqual(["-", 400]);
  });

  const breakdown: R.RevenueBreakdown = {
    as_of: "2026-04-30",
    months: ["2026-01", "2026-02", "2026-03"],
    mrr_by_plan: { starter: [0, 0, 0], professional: [100, 200, 200], enterprise: [0, 500, 500] },
    mrr_by_industry: { Retail: [100, 700, 700], Finance: [0, 0, 0] },
    mrr_by_region: { EU: [100, 400, 400], UK: [0, 300, 300] },
    subscription_revenue_cents: [100, 700, 700],
    usage_revenue_cents: [0, 50, 20],
    accounts: [1, 3, 3],
    arpa_cents: [100, 233, 233],
    revenue_per_system_cents: [10, 20, 20],
    tokens_per_system: [0, 300, 400],
    cohorts: {
      labels: ["2026-01", "2026-02"],
      sizes: [1, 2],
      retention: [
        [100, 100, 0],
        [100, 50, null],
      ],
    },
    top_customers: [],
    recent_invoices: [],
    simulated: true,
    note: "simulated",
  };

  it("stacks plans with the plan colors and leaves out industries with no MRR", () => {
    const plan = R.byPlan(breakdown);
    const s = seriesOf(plan);
    expect(s.map((x) => x.name)).toEqual(["starter", "professional", "enterprise"]);
    expect(s[1]?.itemStyle?.color).toBe(colorOf("professional"));
    const treemap = seriesOf(R.byIndustry(breakdown))[0]?.data as { name: string }[];
    expect(treemap.map((d) => d.name)).toEqual(["Retail"]);
  });

  it("draws the cohort heatmap from the retention matrix, skipping months that have not happened", () => {
    const built = R.cohortHeatmap(breakdown);
    const cells = seriesOf(built)[0]?.data as number[][];
    expect(cells).toHaveLength(5);
    expect(cells).toContainEqual([1, 1, 50]);
    expect(built.summary).toContain("months since signup");
  });

  it("splits subscription and usage revenue and reports both in text", () => {
    const built = R.subscriptionVsUsage(breakdown);
    expect(seriesOf(built).map((s) => s.name)).toEqual(["Subscription", "Usage"]);
    expect(built.summary).toContain("$15 "); // 100 + 700 + 700 cents = $15
  });
});

describe("date range presets", () => {
  it("counts the last 30 days inclusive and the last 12 months", () => {
    const today = new Date("2026-10-26T12:00:00Z");
    expect(rangeFor("30d", today)).toEqual({ start: "2026-09-27", end: "2026-10-26" });
    expect(rangeFor("90d", today)).toEqual({ start: "2026-07-29", end: "2026-10-26" });
    expect(rangeFor("12m", today)).toEqual({ start: "2025-10-27", end: "2026-10-26" });
  });
});

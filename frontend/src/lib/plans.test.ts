import { estimate, FALLBACK_PLANS, formatMoney, recommend } from "./plans";

const [starter, professional, enterprise] = FALLBACK_PLANS as [
  (typeof FALLBACK_PLANS)[number],
  (typeof FALLBACK_PLANS)[number],
  (typeof FALLBACK_PLANS)[number],
];

describe("estimate", () => {
  it("bills only the base fee within the allowance", () => {
    const e = estimate(professional, 25, 50);
    expect(e.totalCents).toBe(39_900);
    expect(e.extraSystems).toBe(0);
  });

  it("matches the invoice formula beyond the allowance (same numbers as the backend test)", () => {
    const e = estimate(professional, 28, 60);
    expect(e.extraSystemsCents).toBe(3 * 1_500);
    expect(e.extraRequestsCents).toBe(10 * 800);
    expect(e.totalCents).toBe(39_900 + 4_500 + 8_000);
  });

  it("says a plan with no overage price does not fit larger usage", () => {
    expect(estimate(starter, 3, 5).fits).toBe(true);
    expect(estimate(starter, 4, 5).fits).toBe(false);
    expect(estimate(starter, 3, 6).fits).toBe(false);
    expect(estimate(enterprise, 400, 2000).fits).toBe(true);
  });
});

describe("recommend", () => {
  it("picks the free plan when it fits", () => {
    expect(recommend(FALLBACK_PLANS, 2, 3)?.plan.code).toBe("starter");
  });

  it("picks the cheapest plan that fits", () => {
    expect(recommend(FALLBACK_PLANS, 12, 30)?.plan.code).toBe("professional");
  });

  it("moves to Enterprise once overage costs more than the base fee difference", () => {
    // Professional: 399 + 125 extra systems * 15 = 2,274; Enterprise: 1,800 base.
    const best = recommend(FALLBACK_PLANS, 150, 50);
    expect(best?.plan.code).toBe("enterprise");
    expect(best?.totalCents).toBe(180_000);
  });

  it("returns null when nothing fits", () => {
    expect(recommend([starter], 10, 10)).toBeNull();
  });
});

describe("formatMoney", () => {
  it("formats whole dollars without cents and others with two decimals", () => {
    expect(formatMoney(39_900)).toBe("$399");
    expect(formatMoney(1_550)).toBe("$15.50");
    expect(formatMoney(0)).toBe("$0");
  });
});

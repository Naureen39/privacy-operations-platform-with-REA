/** One color per series, used by every chart, so "high" or "groq" looks the same everywhere.
 *  Every color is at least 3:1 against white (graphical objects) and the set stays distinguishable
 *  for the common kinds of color blindness; charts also say what a series is in text. */

export const PALETTE = {
  blue: "#0F62FE",
  teal: "#007D79",
  purple: "#8A3FFC",
  magenta: "#D02670",
  amber: "#B28600",
  green: "#198038",
  navy: "#0B1F3A",
  gray: "#697077",
  red: "#DA1E28",
} as const;

export const SERIES_COLOR: Record<string, string> = {
  // severities
  critical: "#A2191F",
  high: PALETTE.red,
  medium: PALETTE.amber,
  low: PALETTE.blue,
  // findings flow
  opened: PALETTE.magenta,
  closed: PALETTE.teal,
  net: PALETTE.navy,
  // providers
  groq: PALETTE.purple,
  gemini: PALETTE.blue,
  unknown: PALETTE.gray,
  // plans
  starter: PALETTE.gray,
  professional: PALETTE.blue,
  enterprise: PALETTE.navy,
  // revenue movements
  new: PALETTE.green,
  expansion: PALETTE.teal,
  contraction: PALETTE.amber,
  churn: PALETTE.red,
  // revenue kinds
  subscription: PALETTE.blue,
  usage: PALETTE.teal,
  // assessments
  draft: PALETTE.gray,
  in_review: PALETTE.amber,
  approved: PALETTE.green,
  rejected: PALETTE.red,
  // extractors
  rea: PALETTE.blue,
  fallback: PALETTE.gray,
};

const CYCLE = [
  PALETTE.blue,
  PALETTE.teal,
  PALETTE.purple,
  PALETTE.magenta,
  PALETTE.amber,
  PALETTE.green,
  PALETTE.navy,
  PALETTE.gray,
];

/** The color of a named series; unknown names take a stable color from the cycle. */
export function colorOf(name: string): string {
  const known = SERIES_COLOR[name];
  if (known) return known;
  let hash = 0;
  for (const ch of name) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return CYCLE[hash % CYCLE.length] ?? PALETTE.blue;
}

export function compactNumber(value: number): string {
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

export function compactMoney(cents: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(cents / 100);
}

export function exactMoney(cents: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(
    cents / 100,
  );
}

export const AXIS = {
  axisLine: { lineStyle: { color: "#A0ACBE" } },
  axisLabel: { color: "#3D4757" },
  splitLine: { lineStyle: { color: "#E3E8EF" } },
};

export const BASE = {
  textStyle: { fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif" },
  grid: { left: 56, right: 24, top: 40, bottom: 48, containLabel: true },
  legend: { top: 0, textStyle: { color: "#161E2D" } },
  tooltip: { trigger: "axis" as const, confine: true },
};

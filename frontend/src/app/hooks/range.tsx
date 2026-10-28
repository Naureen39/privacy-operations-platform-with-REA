import { Download, Printer } from "lucide-react";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { Select } from "../ui/parts";
import { useToast } from "../ui/toast";

export type Preset = "30d" | "90d" | "12m" | "custom";
export type Granularity = "day" | "week" | "month";

const iso = (d: Date) => d.toISOString().slice(0, 10);

export function rangeFor(preset: Exclude<Preset, "custom">, today: Date): { start: string; end: string } {
  const end = new Date(today);
  const start = new Date(today);
  if (preset === "30d") start.setDate(start.getDate() - 29);
  else if (preset === "90d") start.setDate(start.getDate() - 89);
  else start.setFullYear(start.getFullYear() - 1, start.getMonth(), start.getDate() + 1);
  return { start: iso(start), end: iso(end) };
}

/** The controls shared by both dashboards: range presets, a custom range, granularity, comparison
 *  with the previous period, CSV export and a print layout. */
export function useRange(csvPath: string, defaultPreset: Preset = "90d", defaultGranularity: Granularity = "week") {
  const toast = useToast();
  const [preset, setPreset] = useState<Preset>(defaultPreset);
  const [custom, setCustom] = useState({ start: "", end: "" });
  const [granularity, setGranularity] = useState<Granularity>(defaultGranularity);
  const [compare, setCompare] = useState(true);

  const range = useMemo(() => {
    if (preset === "custom" && custom.start && custom.end && custom.start <= custom.end) return custom;
    return rangeFor(preset === "custom" ? "90d" : preset, new Date());
  }, [preset, custom]);

  const exportCsv = async () => {
    try {
      const { blob } = await api.blob(csvPath, { ...range, granularity, compare, format: "csv" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${csvPath.split("/").pop() ?? "export"}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      toast.error("The export failed");
    }
  };

  const controls = (
    <div className="mb-6 flex flex-wrap items-end gap-4 print:hidden" role="group" aria-label="Date range and options">
      <Select
        id="range-preset"
        label="Range"
        value={preset}
        onChange={(v) => setPreset(v as Preset)}
        options={[
          { value: "30d", label: "Last 30 days" },
          { value: "90d", label: "Last 90 days" },
          { value: "12m", label: "Last 12 months" },
          { value: "custom", label: "Custom" },
        ]}
      />
      {preset === "custom" && (
        <>
          <div className="space-y-1">
            <Label htmlFor="range-start">From</Label>
            <Input
              id="range-start"
              type="date"
              value={custom.start}
              onChange={(e) => setCustom({ ...custom, start: e.target.value })}
              className="w-44"
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="range-end">To</Label>
            <Input
              id="range-end"
              type="date"
              value={custom.end}
              onChange={(e) => setCustom({ ...custom, end: e.target.value })}
              className="w-44"
            />
          </div>
        </>
      )}
      <Select
        id="range-granularity"
        label="Group by"
        value={granularity}
        onChange={(v) => setGranularity(v as Granularity)}
        options={[
          { value: "day", label: "Day" },
          { value: "week", label: "Week" },
          { value: "month", label: "Month" },
        ]}
      />
      <label className="flex h-10 items-center gap-2 text-sm font-medium">
        <input
          type="checkbox"
          className="size-4 accent-primary"
          checked={compare}
          onChange={(e) => setCompare(e.target.checked)}
        />
        Compare with the previous period
      </label>
      <div className="ml-auto flex gap-2">
        <Button variant="secondary" onClick={() => void exportCsv()}>
          <Download aria-hidden="true" /> CSV
        </Button>
        <Button variant="secondary" onClick={() => window.print()}>
          <Printer aria-hidden="true" /> Print
        </Button>
      </div>
    </div>
  );

  return { range, granularity, compare, controls };
}

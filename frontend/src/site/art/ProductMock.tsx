import { cn } from "@/lib/utils";

/** An illustration of the console drawn with markup, not a screenshot. The captions say so. The
 *  figures are sample data from the reference estate. Real screenshots arrive with the console. */

export type MockView = "dashboard" | "findings" | "record" | "assessment" | "request";

const nav = ["Overview", "Systems", "Findings", "Records", "Assessments", "Requests"];

function Pill({ tone, children }: { tone: "red" | "amber" | "blue" | "green"; children: string }) {
  const tones = {
    red: "bg-danger/10 text-danger",
    amber: "bg-warning/15 text-[rgb(110_63_0)]",
    blue: "bg-primary/10 text-primary-hover",
    green: "bg-success/10 text-[rgb(8_88_47)]",
  } as const;
  return <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-semibold", tones[tone])}>{children}</span>;
}

function Row({ cells, head = false }: { cells: React.ReactNode[]; head?: boolean }) {
  return (
    <div
      className={cn(
        "grid grid-cols-[1.4fr_1fr_0.8fr] items-center gap-2 border-b border-border px-3 py-2 text-[12px]",
        head ? "bg-muted font-semibold text-navy" : "text-foreground",
      )}
    >
      {cells.map((c, i) => (
        <div key={i} className="truncate">
          {c}
        </div>
      ))}
    </div>
  );
}

function Kpi({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="rounded-md border border-border bg-card p-3">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="text-xl font-bold text-navy">{value}</div>
      <div className="text-[11px] text-muted-foreground">{hint}</div>
    </div>
  );
}

function Bars() {
  const heights = [38, 52, 44, 61, 58, 70, 66, 78, 72, 84, 80, 92];
  return (
    <div className="flex h-24 items-end gap-1.5 rounded-md border border-border bg-card p-3">
      {heights.map((h, i) => (
        <div key={i} className="flex-1 rounded-sm bg-primary/80" style={{ height: `${h}%` }} />
      ))}
    </div>
  );
}

function Screen({ view }: { view: MockView }) {
  if (view === "findings") {
    return (
      <div className="overflow-hidden rounded-md border border-border bg-card">
        <Row head cells={["Finding", "System", "Severity"]} />
        <Row
          cells={[
            "Recipient not declared",
            "Web shop",
            <Pill key="a" tone="red">
              High
            </Pill>,
          ]}
        />
        <Row
          cells={[
            "No transfer safeguard",
            "Web analytics",
            <Pill key="b" tone="red">
              High
            </Pill>,
          ]}
        />
        <Row
          cells={[
            "Retention conflict",
            "Helpdesk",
            <Pill key="c" tone="amber">
              Medium
            </Pill>,
          ]}
        />
        <Row
          cells={[
            "Field not in notice",
            "Newsletter",
            <Pill key="d" tone="amber">
              Medium
            </Pill>,
          ]}
        />
        <Row
          cells={[
            "No agreement on file",
            "CRM",
            <Pill key="e" tone="blue">
              Low
            </Pill>,
          ]}
        />
      </div>
    );
  }
  if (view === "record") {
    return (
      <div className="space-y-2 rounded-md border border-border bg-card p-3 text-[12px]">
        <div className="flex items-center justify-between">
          <div className="text-sm font-semibold text-navy">Customer support</div>
          <Pill tone="green">Approved v3</Pill>
        </div>
        {[
          ["Purposes", "Respond to customer enquiries"],
          ["Data categories", "Name, contact email, order reference"],
          ["Recipients", "Helpdesk vendor (processor, EU)"],
          ["Retention", "24 months after the last ticket"],
        ].map(([k, v]) => (
          <div key={k} className="grid grid-cols-[110px_1fr] gap-2 border-t border-border pt-2">
            <div className="text-muted-foreground">{k}</div>
            <div className="text-foreground">{v}</div>
          </div>
        ))}
        <div className="rounded-sm bg-muted px-2 py-1 text-[11px] text-muted-foreground">
          Draft for review by a qualified privacy professional. Not legal advice.
        </div>
      </div>
    );
  }
  if (view === "assessment") {
    return (
      <div className="space-y-2 rounded-md border border-border bg-card p-3 text-[12px]">
        <div className="flex items-center justify-between">
          <div className="text-sm font-semibold text-navy">Impact assessment</div>
          <Pill tone="amber">In review</Pill>
        </div>
        <div className="grid grid-cols-3 gap-1.5 text-center">
          {["Low", "Medium", "High"].map((l, i) => (
            <div
              key={l}
              className={cn(
                "rounded-sm py-2 font-semibold",
                i === 2 ? "bg-danger/10 text-danger" : "bg-muted text-navy",
              )}
            >
              {l}
              <div className="text-base">{[1, 3, 2][i]}</div>
            </div>
          ))}
        </div>
        <Row cells={["Unauthorized access", "Article 32", "Likely"]} />
        <Row cells={["Excessive collection", "Article 5(1)(c)", "Possible"]} />
      </div>
    );
  }
  if (view === "request") {
    return (
      <div className="space-y-2 rounded-md border border-border bg-card p-3 text-[12px]">
        <div className="flex items-center justify-between">
          <div className="text-sm font-semibold text-navy">Request REQ-2026-0007</div>
          <Pill tone="blue">Searching</Pill>
        </div>
        <div className="h-2 rounded-full bg-muted">
          <div className="h-2 w-1/2 rounded-full bg-accent" />
        </div>
        <div className="text-muted-foreground">Day 12 of 30. Reminder due in 7 days.</div>
        <Row cells={["Locations found", "7 systems", "Searched"]} />
        <Row cells={["Identity", "Verified", "Done"]} />
      </div>
    );
  }
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 gap-2">
        <Kpi label="Approved records" value="14" hint="2 due for review" />
        <Kpi label="Open findings" value="9" hint="3 high severity" />
        <Kpi label="Requests open" value="4" hint="0 overdue" />
      </div>
      <Bars />
    </div>
  );
}

export function ProductMock({ view = "dashboard", className }: { view?: MockView; className?: string }) {
  return (
    <figure className={cn("m-0", className)}>
      <div
        className="overflow-hidden rounded-lg border border-border bg-surface shadow-pop"
        role="img"
        aria-label="Illustration of the ProcessLedger console showing sample data"
      >
        <div className="flex items-center gap-1.5 border-b border-border bg-card px-3 py-2">
          <span className="size-2.5 rounded-full bg-border" />
          <span className="size-2.5 rounded-full bg-border" />
          <span className="size-2.5 rounded-full bg-border" />
          <span className="ml-3 text-[11px] text-muted-foreground">Northbridge Group</span>
        </div>
        <div className="grid grid-cols-[104px_1fr]">
          <div className="hidden border-r border-border bg-navy p-2 text-[11px] text-white/80 sm:block">
            {nav.map((n, i) => (
              <div key={n} className={cn("rounded px-2 py-1.5", i === 0 && "bg-white/10 font-semibold text-white")}>
                {n}
              </div>
            ))}
          </div>
          <div className="col-span-2 p-3 sm:col-span-1">
            <Screen view={view} />
          </div>
        </div>
      </div>
      <figcaption className="mt-2 text-xs text-muted-foreground">
        Illustrative interface with sample data from the reference estate.
      </figcaption>
    </figure>
  );
}

import { Badge } from "@/components/ui/badge";
import type { Activity } from "../../types";

function List({ items }: { items: readonly unknown[] | null | undefined }) {
  if (!items || items.length === 0) return <span className="text-muted-foreground">Not recorded</span>;
  return (
    <ul className="list-disc space-y-0.5 pl-5">
      {items.map((item, i) => (
        <li key={i}>{typeof item === "string" ? item : describe(item)}</li>
      ))}
    </ul>
  );
}

function describe(value: unknown): string {
  if (value && typeof value === "object") {
    const o = value as Record<string, unknown>;
    const label = o.vendor ?? o.name ?? o.domain ?? o.label;
    const extra = [o.country, o.role, o.safeguard].filter(Boolean).join(", ");
    if (label) return extra ? `${String(label)} (${extra})` : String(label);
  }
  return JSON.stringify(value);
}

export const FIELD_LABELS: Record<string, string> = {
  purposes: "Purposes",
  data_subjects: "Categories of data subjects",
  data_categories: "Categories of personal data",
  recipients: "Recipients",
  transfers: "Transfers to third countries",
  retention: "Retention",
  security_measures: "Security measures",
  lawful_basis: "Lawful basis",
  special_category_condition: "Article 9 condition",
  next_review_date: "Next review",
};

/** The Article 30 fields of a record, with a marker where one is missing and the evidence it cites. */
export function RecordFields({ record }: { record: Activity }) {
  const missing = new Set(record.missing_fields);
  const rows: [string, React.ReactNode][] = [
    ["purposes", <List key="p" items={record.purposes} />],
    ["data_subjects", <List key="s" items={record.data_subjects} />],
    ["data_categories", <List key="c" items={record.data_categories} />],
    ["recipients", <List key="r" items={record.recipients} />],
    ["transfers", <List key="t" items={record.transfers} />],
    ["retention", record.retention || <span className="text-muted-foreground">Not recorded</span>],
    ["security_measures", record.security_measures || <span className="text-muted-foreground">Not recorded</span>],
    ["lawful_basis", record.lawful_basis || <span className="text-muted-foreground">Not recorded</span>],
    [
      "special_category_condition",
      record.special_category_condition || <span className="text-muted-foreground">Not recorded</span>,
    ],
    ["next_review_date", record.next_review_date || <span className="text-muted-foreground">Not set</span>],
  ];
  const citations = (record.citations ?? {}) as Record<string, unknown>;
  return (
    <dl className="divide-y divide-border">
      {rows.map(([key, value]) => {
        const cited = citations[key];
        const count = Array.isArray(cited) ? cited.length : cited ? 1 : 0;
        return (
          <div key={key} className="grid gap-1 py-3 sm:grid-cols-[14rem_1fr]">
            <dt className="font-medium text-navy dark:text-foreground">
              {FIELD_LABELS[key]}
              {missing.has(key) && (
                <Badge tone="amber" className="ml-2">
                  Missing
                </Badge>
              )}
            </dt>
            <dd>
              {value}
              {count > 0 && (
                <p className="mt-1 text-xs text-muted-foreground">
                  Cites {count} {count === 1 ? "source" : "sources"}
                </p>
              )}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

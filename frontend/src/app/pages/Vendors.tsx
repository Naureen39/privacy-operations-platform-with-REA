import { useState } from "react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { usePageMeta } from "@/lib/queries";
import { useVendors } from "../hooks/data";
import { DataTable } from "../ui/DataTable";
import { PageHeader, Panel } from "../ui/parts";
import type { Vendor } from "../types";

const GAP_LABEL: Record<string, string> = {
  third_country_no_safeguard: "Transfer without safeguard",
  missing_agreement: "No agreement on file",
  undeclared_recipient: "Not declared in the record",
};

/** The processor register: one row per vendor, the systems that use it, the country, and the open
 *  gaps (transfer safeguard, agreement, declaration). */
export default function Vendors() {
  usePageMeta("Vendors and transfers");
  const vendors = useVendors();
  const [selected, setSelected] = useState<Vendor | null>(null);
  const withGaps = (vendors.data ?? []).filter((v) => v.open_findings.length > 0).length;
  return (
    <>
      <PageHeader
        title="Vendors and transfers"
        description={`${(vendors.data ?? []).length} vendors across your systems, ${withGaps} with open gaps.`}
      />
      <div className="grid gap-6 xl:grid-cols-[1.7fr_1fr]">
        <DataTable<Vendor>
          data={vendors.data ?? []}
          loading={vendors.isLoading}
          caption="Vendors"
          searchPlaceholder="Search vendors"
          onRowClick={setSelected}
          empty={{ title: "No vendors found", text: "Vendors appear when discovery finds recipients in the evidence." }}
          columns={[
            {
              accessorKey: "name",
              header: "Vendor",
              cell: (c) => <span className="font-semibold">{String(c.getValue())}</span>,
            },
            { accessorKey: "role", header: "Role" },
            { accessorKey: "country", header: "Country", cell: (c) => c.getValue() ?? "Unknown" },
            { id: "systems", header: "Systems", accessorFn: (v) => v.systems.length },
            {
              id: "gaps",
              header: "Open gaps",
              accessorFn: (v) => v.open_findings.length,
              cell: ({ row }) =>
                row.original.open_findings.length === 0 ? (
                  <span className="text-muted-foreground">None</span>
                ) : (
                  <Badge tone="amber">{row.original.open_findings.length}</Badge>
                ),
            },
          ]}
        />
        <Panel title={selected ? selected.name : "Details"}>
          {!selected ? (
            <p className="text-muted-foreground">Select a vendor to see where it is used and what is open.</p>
          ) : (
            <div className="space-y-4 text-sm">
              <dl className="grid grid-cols-[7rem_1fr] gap-x-3 gap-y-1">
                <dt className="text-muted-foreground">Role</dt>
                <dd>{selected.role}</dd>
                <dt className="text-muted-foreground">Country</dt>
                <dd>{selected.country ?? "Unknown"}</dd>
                <dt className="text-muted-foreground">Category</dt>
                <dd>{selected.category ?? "Not set"}</dd>
                <dt className="text-muted-foreground">Domains</dt>
                <dd className="break-all">{selected.domains.join(", ")}</dd>
              </dl>
              <div>
                <h3 className="text-base">Systems</h3>
                <ul className="mt-1 space-y-1">
                  {selected.systems.map((s) => (
                    <li key={String(s.id)}>
                      <Link to={`/app/systems/${String(s.id)}`} className="text-primary hover:underline">
                        {String(s.name)}
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <h3 className="text-base">Open gaps</h3>
                {selected.open_findings.length === 0 ? (
                  <p className="text-muted-foreground">None.</p>
                ) : (
                  <ul className="mt-1 list-disc space-y-1 pl-5">
                    {selected.open_findings.map((f) => (
                      <li key={f}>{GAP_LABEL[f] ?? f.replaceAll("_", " ")}</li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          )}
        </Panel>
      </div>
    </>
  );
}

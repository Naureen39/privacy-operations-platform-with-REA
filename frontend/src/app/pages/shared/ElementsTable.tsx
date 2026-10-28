import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { useAction, useElements } from "../../hooks/data";
import { useSession } from "../../session";
import { DataTable } from "../../ui/DataTable";
import type { DataElement, TaxonomyCategory } from "../../types";
import { EvidenceDrawer } from "./EvidenceDrawer";

/** The data elements of a system with their category, confidence and review state. Editors can
 *  accept an element or override its category; every row links to its evidence. */
export function ElementsTable({ systemId, reviewable = true }: { systemId: string; reviewable?: boolean }) {
  const { can } = useSession();
  const elements = useElements(systemId);
  const taxonomy = useQuery({
    queryKey: ["taxonomy"],
    queryFn: () => api.get<TaxonomyCategory[]>("/api/v1/taxonomy"),
    staleTime: 600_000,
  });
  const [drawer, setDrawer] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [category, setCategory] = useState("");

  const review = useAction({
    run: (input: { id: string; body: Record<string, unknown> }) =>
      api.patch<DataElement>(`/api/v1/systems/${systemId}/data-elements/${input.id}`, input.body),
    success: "Saved",
    invalidate: [["elements", systemId], ["review-queue"]],
    onDone: () => setEditing(null),
  });
  const editable = reviewable && can("write");

  return (
    <>
      <DataTable<DataElement>
        data={elements.data ?? []}
        loading={elements.isLoading}
        caption="Data elements"
        searchPlaceholder="Search elements"
        empty={{ title: "No data elements yet", text: "Run discovery and classification to find them." }}
        columns={[
          {
            accessorKey: "name",
            header: "Element",
            cell: (c) => <span className="font-medium">{String(c.getValue())}</span>,
          },
          {
            accessorKey: "category",
            header: "Category",
            cell: ({ row }) =>
              editing === row.original.id ? (
                <div className="flex items-center gap-2">
                  <select
                    aria-label={`Category for ${row.original.name}`}
                    value={category}
                    onChange={(e) => setCategory(e.target.value)}
                    className="h-9 rounded-md border border-input bg-background px-2 text-sm"
                  >
                    <option value="">Choose a category</option>
                    {(taxonomy.data ?? []).map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.label}
                      </option>
                    ))}
                  </select>
                  <Button
                    size="sm"
                    disabled={!category || review.isPending}
                    onClick={() =>
                      review.mutate({ id: row.original.id, body: { review_status: "overridden", category } })
                    }
                  >
                    Save
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setEditing(null)}>
                    Cancel
                  </Button>
                </div>
              ) : (
                (row.original.category ?? "Not classified")
              ),
          },
          {
            accessorKey: "special_category",
            header: "Special category",
            cell: (c) => (c.getValue() ? <Badge tone="amber">Article 9</Badge> : "No"),
          },
          {
            accessorKey: "confidence",
            header: "Confidence",
            cell: (c) =>
              c.getValue() === null || c.getValue() === undefined
                ? "None"
                : `${Math.round(Number(c.getValue()) * 100)}%`,
          },
          {
            accessorKey: "review_status",
            header: "Review",
            cell: (c) => <Badge tone={c.getValue() === "pending" ? "amber" : "green"}>{String(c.getValue())}</Badge>,
          },
          {
            id: "actions",
            header: "Actions",
            enableSorting: false,
            cell: ({ row }) => (
              <div className="flex flex-wrap gap-2">
                {row.original.evidence_id && (
                  <Button size="sm" variant="ghost" onClick={() => setDrawer(row.original.evidence_id ?? null)}>
                    Evidence
                  </Button>
                )}
                {editable && row.original.review_status === "pending" && (
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => review.mutate({ id: row.original.id, body: { review_status: "accepted" } })}
                  >
                    Accept
                  </Button>
                )}
                {editable && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      setCategory(row.original.category ?? "");
                      setEditing(row.original.id);
                    }}
                  >
                    Override
                  </Button>
                )}
              </div>
            ),
          },
        ]}
      />
      <EvidenceDrawer evidenceId={drawer} onClose={() => setDrawer(null)} />
    </>
  );
}

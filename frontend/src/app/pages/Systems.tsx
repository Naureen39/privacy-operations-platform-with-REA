import { Link, useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { usePageMeta } from "@/lib/queries";
import { useActivities, useFindings, useSystems } from "../hooks/data";
import { useSession } from "../session";
import { DataTable } from "../ui/DataTable";
import { formatDateTime, StatusBadge } from "../ui/kit";
import { PageHeader } from "../ui/parts";
import type { System } from "../types";

export default function Systems() {
  usePageMeta("Systems");
  const { can } = useSession();
  const navigate = useNavigate();
  const systems = useSystems();
  const activities = useActivities();
  const findings = useFindings({ status: "open" });

  const recordOf = (systemId: string) => (activities.data ?? []).find((a) => a.system_ids.includes(systemId));
  const openCount = (systemId: string) => (findings.data ?? []).filter((f) => f.system_id === systemId).length;

  return (
    <>
      <PageHeader
        title="Systems"
        description="Every system that processes personal data, with its record and open findings."
        actions={
          can("write") && (
            <Button asChild>
              <Link to="/app/systems/new">Add a system</Link>
            </Button>
          )
        }
      />
      <DataTable<System>
        data={systems.data ?? []}
        loading={systems.isLoading}
        caption="Systems"
        searchPlaceholder="Search systems"
        onRowClick={(s) => navigate(`/app/systems/${s.id}`)}
        empty={{
          title: "No systems yet",
          text: "Add the first system to start building the inventory.",
          action: can("write") ? (
            <Button asChild>
              <Link to="/app/systems/new">Add a system</Link>
            </Button>
          ) : undefined,
        }}
        columns={[
          {
            accessorKey: "name",
            header: "System",
            cell: ({ row }) => (
              <Link
                to={`/app/systems/${row.original.id}`}
                className="font-semibold text-primary hover:underline"
                onClick={(e) => e.stopPropagation()}
              >
                {row.original.name}
              </Link>
            ),
          },
          { accessorKey: "owner_user_id", header: "Owner", cell: (c) => (c.getValue() ? "Assigned" : "Unassigned") },
          {
            accessorKey: "status",
            header: "Stage",
            cell: (c) => <StatusBadge value={String(c.getValue()).toLowerCase()} />,
          },
          {
            accessorKey: "last_discovery_at",
            header: "Last discovery",
            cell: (c) => formatDateTime(c.getValue() as string | null),
          },
          {
            id: "record",
            header: "Record",
            accessorFn: (s) => recordOf(s.id)?.status ?? "none",
            cell: (c) =>
              c.getValue() === "none" ? (
                <span className="text-muted-foreground">No record</span>
              ) : (
                <StatusBadge value={String(c.getValue())} />
              ),
          },
          { id: "findings", header: "Open findings", accessorFn: (s) => openCount(s.id) },
        ]}
      />
    </>
  );
}

import { ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { usePageMeta } from "@/lib/queries";
import { useActivities, useDpias, useFindings, useReminders, useRequests, useSystems, useTasks } from "../hooks/data";
import { useSession } from "../session";
import { EmptyState, formatDate, SeverityBadge, Skeleton } from "../ui/kit";
import { PageHeader, Panel, Stat } from "../ui/parts";

const quickStart = [
  { step: "Add a system", text: "Register it and assign an owner.", to: "/app/systems/new" },
  {
    step: "Attach evidence",
    text: "A privacy notice, a questionnaire, a network capture or a database schema.",
    to: "/app/systems",
  },
  {
    step: "Review the record",
    text: "Check the generated record and the findings, then submit it.",
    to: "/app/records",
  },
];

/** Live counts from the organization's own lists (the nightly snapshots feed the analytics page). */
export default function Overview() {
  usePageMeta("Overview");
  const { me, can } = useSession();
  const systems = useSystems();
  const activities = useActivities();
  const openFindings = useFindings({ status: "open" });
  const dpias = useDpias();
  const requests = useRequests();
  const reminders = useReminders();
  const tasks = useTasks();
  const staff = me.role !== "system_owner";

  const today = new Date().toISOString().slice(0, 10);
  const records = activities.data ?? [];
  const approved = records.filter((a) => a.status === "approved" || a.status === "published").length;
  const stale = records.filter((a) => a.next_review_date && a.next_review_date < today).length;
  const inProgress = (dpias.data ?? []).filter((d) => d.status === "draft" || d.status === "in_review").length;
  const openRequests = (requests.data ?? []).filter((r) => !["responded", "closed", "rejected"].includes(r.status));
  const due = openRequests.filter((r) => (r.days_remaining ?? 99) <= 7);
  const myTasks = (tasks.data ?? []).filter((t) => t.status !== "done").slice(0, 6);
  const recent = [...(openFindings.data ?? [])].slice(0, 6);
  const loading = systems.isLoading || activities.isLoading;

  return (
    <>
      <PageHeader
        title={`Welcome, ${me.user.full_name.split(" ")[0]}`}
        description="Where the organization stands today: records, findings, assessments and requests."
        actions={
          can("write") && (
            <Button asChild>
              <Link to="/app/systems/new">Add a system</Link>
            </Button>
          )
        }
      />
      {loading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
      ) : (
        <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5" aria-label="Compliance posture">
          <Stat label="Systems" value={(systems.data ?? []).length} hint="in the inventory" />
          <Stat label="Approved records" value={approved} hint={`${records.length} records in total`} />
          <Stat label="Stale records" value={stale} hint="past their review date" />
          <Stat label="Open findings" value={(openFindings.data ?? []).length} />
          {staff ? (
            <Stat
              label="Requests due"
              value={due.length}
              hint={`${openRequests.length} open, ${inProgress} assessments in progress`}
            />
          ) : (
            <Stat label="Tasks" value={myTasks.length} hint="open" />
          )}
        </dl>
      )}

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Panel
          title="Recent findings"
          actions={
            <Link to="/app/findings" className="text-sm font-semibold text-primary hover:underline">
              All findings
            </Link>
          }
        >
          {openFindings.isLoading ? (
            <Skeleton className="h-32" />
          ) : recent.length === 0 ? (
            <EmptyState title="No open findings" text="Findings appear when the sources of a system disagree." />
          ) : (
            <ul className="divide-y divide-border">
              {recent.map((f) => (
                <li key={f.id} className="flex items-center justify-between gap-3 py-3">
                  <span className="min-w-0 truncate">{f.title}</span>
                  <SeverityBadge value={f.severity} />
                </li>
              ))}
            </ul>
          )}
        </Panel>
        <Panel title="Tasks due">
          {tasks.isLoading ? (
            <Skeleton className="h-32" />
          ) : myTasks.length === 0 ? (
            <EmptyState title="No open tasks" text="Review reminders and tasks from findings show up here." />
          ) : (
            <ul className="divide-y divide-border">
              {myTasks.map((t) => (
                <li key={t.id} className="flex items-center justify-between gap-3 py-3">
                  <span className="min-w-0 truncate">{t.title}</span>
                  <span className="shrink-0 text-sm text-muted-foreground">{formatDate(t.due_date)}</span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
        {staff && (
          <Panel
            title="Requests nearing their deadline"
            actions={
              <Link to="/app/requests" className="text-sm font-semibold text-primary hover:underline">
                All requests
              </Link>
            }
          >
            {reminders.isLoading ? (
              <Skeleton className="h-32" />
            ) : (reminders.data ?? []).length === 0 ? (
              <EmptyState title="Nothing is close to its deadline" />
            ) : (
              <ul className="divide-y divide-border">
                {(reminders.data ?? []).slice(0, 6).map((r) => (
                  <li key={r.id} className="flex items-center justify-between gap-3 py-3">
                    <Link to={`/app/requests/${r.id}`} className="font-semibold text-primary hover:underline">
                      {r.reference}
                    </Link>
                    <span className={r.overdue ? "font-semibold text-danger" : "text-muted-foreground"}>
                      {r.overdue ? "Overdue" : `${r.days_remaining} days left`}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        )}
        <Panel title="Quick start">
          <ol className="space-y-4">
            {quickStart.map((q, i) => (
              <li key={q.step} className="flex gap-3">
                <span className="grid size-7 shrink-0 place-items-center rounded-full bg-navy text-sm font-bold text-white">
                  {i + 1}
                </span>
                <div>
                  <p className="font-semibold text-navy dark:text-foreground">{q.step}</p>
                  <p className="text-sm text-muted-foreground">{q.text}</p>
                </div>
                {can("write") && (
                  <Link to={q.to} aria-label={`Go to: ${q.step}`} className="ml-auto self-center text-primary">
                    <ArrowRight aria-hidden="true" className="size-4" />
                  </Link>
                )}
              </li>
            ))}
          </ol>
          <p className="mt-4 text-sm text-muted-foreground">
            The reference estate (a fictional retailer with eight systems) is in <code>datasets/estate</code>; its
            evidence files can be uploaded to try the wizard.
          </p>
        </Panel>
      </div>
    </>
  );
}

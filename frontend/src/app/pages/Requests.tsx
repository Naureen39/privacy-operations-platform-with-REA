import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { usePageMeta } from "@/lib/queries";
import { cn } from "@/lib/utils";
import NotFound from "../../site/pages/NotFound";
import { useAction, useRequests } from "../hooks/data";
import { useSession } from "../session";
import { DataTable } from "../ui/DataTable";
import { ErrorNote, formatDate, formatDateTime, Skeleton, StatusBadge } from "../ui/kit";
import { PageHeader, Panel, Select } from "../ui/parts";
import type { RequestItem, RequestResponse, RequestResult } from "../types";

function Deadline({ r }: { r: RequestItem }) {
  if (["responded", "closed", "rejected"].includes(r.status))
    return <span className="text-muted-foreground">Finished</span>;
  if (r.overdue) return <span className="font-semibold text-danger">Overdue</span>;
  const days = r.days_remaining ?? 0;
  return (
    <span className={cn(days <= 7 ? "font-semibold text-[rgb(110_63_0)]" : "text-muted-foreground")}>
      {days} days left
    </span>
  );
}

function NewRequest({ onDone }: { onDone: (id: string) => void }) {
  const [type, setType] = useState("email");
  const [identifier, setIdentifier] = useState("");
  const [received, setReceived] = useState("");
  const create = useAction({
    run: () =>
      api.post<RequestItem>("/api/v1/access-requests", {
        identifier_type: type,
        identifier,
        received_date: received || undefined,
      }),
    success: (r) => `Logged ${r.reference}`,
    invalidate: [["requests"], ["reminders"]],
    onDone: (r) => onDone(r.id),
  });
  return (
    <form
      className="grid max-w-3xl gap-4 sm:grid-cols-[10rem_1fr_12rem_auto] sm:items-end"
      aria-label="Log a request"
      onSubmit={(e) => {
        e.preventDefault();
        if (identifier.trim().length >= 3) create.mutate(undefined);
      }}
    >
      <Select
        id="req-type"
        label="Identifier"
        value={type}
        onChange={setType}
        options={[
          { value: "email", label: "Email" },
          { value: "phone", label: "Phone" },
        ]}
      />
      <Field id="req-id" label="Email address or number" hint="Stored only as a keyed hash.">
        {(p) => (
          <Input
            {...p}
            value={identifier}
            onChange={(e) => setIdentifier(e.target.value)}
            autoComplete="off"
            required
          />
        )}
      </Field>
      <Field id="req-date" label="Received on">
        {(p) => <Input {...p} type="date" value={received} onChange={(e) => setReceived(e.target.value)} />}
      </Field>
      <Button type="submit" disabled={create.isPending || identifier.trim().length < 3}>
        Log request
      </Button>
    </form>
  );
}

export function RequestsList() {
  usePageMeta("Access requests");
  const { can } = useSession();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const requests = useRequests();
  const creating = params.get("new") === "1";
  return (
    <>
      <PageHeader
        title="Access requests"
        description="Requests from people to see their data, with the deadline of each."
        actions={can("write") && !creating && <Button onClick={() => setParams({ new: "1" })}>Log a request</Button>}
      />
      {creating && (
        <Panel title="Log a request" className="mb-6">
          <NewRequest onDone={(id) => navigate(`/app/requests/${id}`)} />
        </Panel>
      )}
      <DataTable<RequestItem>
        data={requests.data ?? []}
        loading={requests.isLoading}
        caption="Access requests"
        searchPlaceholder="Search requests"
        onRowClick={(r) => navigate(`/app/requests/${r.id}`)}
        empty={{ title: "No requests yet", text: "Log a request when a person asks what is held about them." }}
        columns={[
          {
            accessorKey: "reference",
            header: "Reference",
            cell: ({ row }) => (
              <Link
                to={`/app/requests/${row.original.id}`}
                className="font-semibold text-primary hover:underline"
                onClick={(e) => e.stopPropagation()}
              >
                {row.original.reference}
              </Link>
            ),
          },
          { accessorKey: "status", header: "Status", cell: (c) => <StatusBadge value={String(c.getValue())} /> },
          { accessorKey: "received_date", header: "Received", cell: (c) => formatDate(String(c.getValue())) },
          { accessorKey: "deadline_date", header: "Deadline", cell: (c) => formatDate(String(c.getValue())) },
          {
            id: "timer",
            header: "Time left",
            accessorFn: (r) => r.days_remaining ?? 0,
            cell: ({ row }) => <Deadline r={row.original} />,
          },
          { accessorKey: "systems_matched", header: "Systems matched", cell: (c) => c.getValue() ?? "Not searched" },
        ]}
      />
    </>
  );
}

const CHECKLIST: [string, string][] = [
  ["name_matches_records", "The name matches our records"],
  ["contact_details_confirmed", "Contact details are confirmed"],
  ["identity_document_seen", "An identity document was seen"],
];

const FLOW = ["received", "identity_verification", "searching", "drafting", "awaiting_approval", "responded", "closed"];

export function RequestDetail() {
  const { id = "" } = useParams();
  const { can } = useSession();
  const query = useQuery({
    queryKey: ["request", id],
    queryFn: () => api.get<RequestItem>(`/api/v1/access-requests/${id}`),
  });
  const results = useQuery({
    queryKey: ["request-results", id],
    queryFn: () => api.get<RequestResult[]>(`/api/v1/access-requests/${id}/results`),
    retry: false,
  });
  const response = useQuery({
    queryKey: ["request-response", id],
    queryFn: () => api.get<RequestResponse>(`/api/v1/access-requests/${id}/response`),
    retry: false,
  });
  usePageMeta(query.data?.reference ?? "Request");
  const [checklist, setChecklist] = useState<Record<string, boolean>>({});
  const [identifier, setIdentifier] = useState("");
  const [cover, setCover] = useState(false);
  const [body, setBody] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [months, setMonths] = useState(1);
  const [reason, setReason] = useState("");
  const refresh = [["request", id], ["requests"], ["request-results", id], ["request-response", id], ["reminders"]];
  const step = (path: string, payload?: unknown, success?: string) => ({
    run: () => api.post(`/api/v1/access-requests/${id}/${path}`, payload),
    success,
    invalidate: refresh,
  });
  const identity = useAction({ ...step("identity", { checklist, note: note || null }, "Identity recorded") });
  const search = useAction({ ...step("search", { identifier }, "Search finished"), onDone: () => setIdentifier("") });
  const disclose = useAction({
    run: (ids: string[]) => api.post(`/api/v1/access-requests/${id}/disclosure`, { result_ids: ids }),
    success: "Disclosure saved",
    invalidate: refresh,
  });
  const draft = useAction({ ...step("response", { cover_note: cover }, "Response drafted") });
  const saveBody = useAction({
    run: () => api.patch(`/api/v1/access-requests/${id}/response`, { body, cover_note: null }),
    success: "Response saved",
    invalidate: refresh,
    onDone: () => setBody(null),
  });
  const submit = useAction(step("submit", undefined, "Submitted for approval"));
  const approve = useAction(step("approve", { note: note || null }, "Approved"));
  const back = useAction(step("return", { note: note || "Returned for changes" }, "Returned for changes"));
  const respond = useAction(step("respond", undefined, "Marked as sent"));
  const close = useAction(step("close", undefined, "Closed"));
  const extend = useAction(step("extension", { months, reason }, "Deadline extended"));
  const reject = useAction(step("reject", { reason }, "Request rejected"));

  if (query.isLoading) return <Skeleton className="h-64" />;
  if (query.isError) {
    return (query.error as { status?: number }).status === 404 ? (
      <NotFound />
    ) : (
      <ErrorNote error={query.error} retry={() => void query.refetch()} />
    );
  }
  const r = query.data;
  if (!r) return null;
  const idx = FLOW.indexOf(r.status);
  const found = results.data ?? [];
  const approved = new Set(found.filter((x) => x.disclosure_approved).map((x) => x.id));
  const editor = can("write");
  const finished = ["responded", "closed", "rejected"].includes(r.status);

  return (
    <>
      <PageHeader
        title={`Request ${r.reference}`}
        description={`Received ${formatDate(r.received_date)}. Deadline ${formatDate(r.deadline_date)}${r.extended ? ` (extended by ${r.extension_months} months)` : ""}.`}
        actions={
          <>
            <StatusBadge value={r.status} />
            <Deadline r={r} />
          </>
        }
      />
      <ol className="mb-6 flex flex-wrap gap-2" aria-label="Progress">
        {FLOW.map((s, i) => (
          <li
            key={s}
            aria-current={i === idx ? "step" : undefined}
            className={cn(
              "rounded-full border px-3 py-1 text-xs font-medium",
              i < idx && "border-success/40 bg-success/10 text-[rgb(8_88_47)]",
              i === idx && "border-primary bg-primary text-primary-foreground",
              i > idx && "border-border text-muted-foreground",
            )}
          >
            {s.replaceAll("_", " ")}
          </li>
        ))}
        {r.status === "rejected" && (
          <li className="rounded-full border border-danger px-3 py-1 text-xs font-medium text-danger">rejected</li>
        )}
      </ol>

      {(r.possible_duplicates ?? []).length > 0 && (
        <p role="status" className="mb-4 rounded-md border border-warning/40 bg-warning/10 p-3 text-sm">
          This may duplicate: {(r.possible_duplicates ?? []).join(", ")}.
        </p>
      )}

      <div className="grid gap-6 xl:grid-cols-2">
        <Panel title="1. Identity">
          <div className="space-y-2">
            {CHECKLIST.map(([key, label]) => (
              <label key={key} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="size-4 accent-primary"
                  disabled={!editor || finished}
                  checked={checklist[key] ?? Boolean((r.identity_checklist as Record<string, boolean>)[key])}
                  onChange={(e) => setChecklist({ ...checklist, [key]: e.target.checked })}
                />
                {label}
              </label>
            ))}
            {editor && !finished && (
              <Button size="sm" onClick={() => identity.mutate(undefined)} disabled={identity.isPending}>
                Record the identity check
              </Button>
            )}
            <p className="text-sm text-muted-foreground">
              {r.identity_verified ? "Identity verified." : "Not verified yet. No identity document is stored."}
            </p>
          </div>
        </Panel>

        <Panel title="2. Search the systems">
          {editor && !finished ? (
            <form
              className="space-y-3"
              aria-label="Search"
              onSubmit={(e) => {
                e.preventDefault();
                if (identifier.trim()) search.mutate(undefined);
              }}
            >
              <p className="text-sm text-muted-foreground">
                Enter the identifier again for the search. It is used for this call only and is never stored or logged.
              </p>
              <Input
                aria-label="Identifier for the search"
                value={identifier}
                onChange={(e) => setIdentifier(e.target.value)}
                autoComplete="off"
              />
              <Button type="submit" disabled={search.isPending || !identifier.trim() || !r.identity_verified}>
                {r.identity_verified ? "Search" : "Verify the identity first"}
              </Button>
            </form>
          ) : (
            <p className="text-muted-foreground">
              Searched {r.searched_at ? formatDateTime(r.searched_at) : "not yet"}.
            </p>
          )}
        </Panel>

        <Panel
          title={`3. Results (${found.length} locations in ${r.systems_matched ?? 0} systems)`}
          className="xl:col-span-2"
        >
          <DataTable<RequestResult>
            data={found}
            loading={results.isLoading}
            caption="Search results"
            searchPlaceholder="Search results"
            empty={{ title: "No results yet", text: "Run the search to see where the person appears." }}
            columns={[
              { accessorKey: "system_name", header: "System" },
              { accessorKey: "table", header: "Table" },
              { accessorKey: "column", header: "Column" },
              { accessorKey: "category", header: "Category", cell: (c) => c.getValue() ?? "Unclassified" },
              { accessorKey: "match_count", header: "Rows" },
              {
                id: "disclose",
                header: "Disclose",
                enableSorting: false,
                cell: ({ row }) => (
                  <input
                    type="checkbox"
                    aria-label={`Disclose ${row.original.system_name} ${row.original.table}`}
                    className="size-4 accent-primary"
                    disabled={!can("approve") || finished}
                    checked={approved.has(row.original.id)}
                    onChange={(e) => {
                      const next = new Set(approved);
                      if (e.target.checked) next.add(row.original.id);
                      else next.delete(row.original.id);
                      disclose.mutate([...next]);
                    }}
                  />
                ),
              },
            ]}
          />
        </Panel>

        <Panel title="4. Response" className="xl:col-span-2">
          {!response.data ? (
            editor && !finished ? (
              <div className="max-w-2xl space-y-3">
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="size-4 accent-primary"
                    checked={cover}
                    onChange={(e) => setCover(e.target.checked)}
                  />
                  Add a short cover note written by the assistant (it sees three numbers and a tone, never a name or an
                  identifier)
                </label>
                <Button onClick={() => draft.mutate(undefined)} disabled={draft.isPending || !r.searched_at}>
                  {r.searched_at ? "Draft the response" : "Search first"}
                </Button>
              </div>
            ) : (
              <p className="text-muted-foreground">No response drafted.</p>
            )
          ) : (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">
                Version {response.data.version}, {response.data.status}. Draft for review by a qualified privacy
                professional. Not legal advice.
              </p>
              {body !== null ? (
                <>
                  <Textarea
                    aria-label="Response letter"
                    className="min-h-72 font-mono text-sm"
                    value={body}
                    onChange={(e) => setBody(e.target.value)}
                  />
                  <div className="flex gap-2">
                    <Button onClick={() => saveBody.mutate(undefined)} disabled={saveBody.isPending}>
                      Save
                    </Button>
                    <Button variant="ghost" onClick={() => setBody(null)}>
                      Cancel
                    </Button>
                  </div>
                </>
              ) : (
                <>
                  <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-md bg-muted p-4 text-sm">
                    {response.data.body}
                  </pre>
                  {editor && !finished && r.status === "drafting" && (
                    <Button variant="secondary" size="sm" onClick={() => setBody(response.data?.body ?? "")}>
                      Edit the letter
                    </Button>
                  )}
                </>
              )}
            </div>
          )}
        </Panel>

        <Panel title="5. Workflow" className="xl:col-span-2">
          <div className="space-y-4">
            <div className="max-w-2xl space-y-1.5">
              <Label htmlFor="wf-note">Note for the decision, or reason for an extension or rejection</Label>
              <Textarea
                id="wf-note"
                className="min-h-16"
                value={note || reason}
                onChange={(e) => {
                  setNote(e.target.value);
                  setReason(e.target.value);
                }}
              />
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {editor && r.status === "drafting" && (
                <Button onClick={() => submit.mutate(undefined)}>Submit for approval</Button>
              )}
              {can("approve") && r.status === "awaiting_approval" && (
                <>
                  <Button onClick={() => approve.mutate(undefined)}>Approve the response</Button>
                  <Button variant="secondary" onClick={() => back.mutate(undefined)}>
                    Return for changes
                  </Button>
                  <Button variant="secondary" onClick={() => respond.mutate(undefined)}>
                    Send the response
                  </Button>
                </>
              )}
              {editor && r.status === "responded" && (
                <Button onClick={() => close.mutate(undefined)}>Close the case</Button>
              )}
              {can("approve") && !finished && (
                <>
                  <label className="flex items-center gap-2 text-sm">
                    Extend by
                    <select
                      aria-label="Months"
                      value={months}
                      onChange={(e) => setMonths(Number(e.target.value))}
                      className="h-9 rounded-md border border-input bg-background px-2"
                    >
                      <option value={1}>1 month</option>
                      <option value={2}>2 months</option>
                    </select>
                  </label>
                  <Button
                    variant="secondary"
                    onClick={() => extend.mutate(undefined)}
                    disabled={reason.trim().length < 10 || r.extended}
                  >
                    Extend the deadline
                  </Button>
                  <Button variant="ghost" onClick={() => reject.mutate(undefined)} disabled={reason.trim().length < 10}>
                    Reject the request
                  </Button>
                </>
              )}
            </div>
          </div>
        </Panel>
      </div>
    </>
  );
}

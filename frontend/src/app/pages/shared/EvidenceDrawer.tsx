import * as Dialog from "@radix-ui/react-dialog";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";

import { api } from "@/lib/api";
import type { DiscoveryEvidence } from "../../types";
import { ErrorNote, formatDateTime, Skeleton } from "../../ui/kit";

/** The raw extractor output behind a data element or a recipient, with the command that produced
 *  it. Shown beside the table so a reviewer can check a claim against its source. */
export function EvidenceDrawer({ evidenceId, onClose }: { evidenceId: string | null; onClose: () => void }) {
  const query = useQuery({
    queryKey: ["discovery-evidence", evidenceId],
    enabled: evidenceId !== null,
    queryFn: () => api.get<DiscoveryEvidence>(`/api/v1/discovery-evidence/${evidenceId}`),
  });
  const e = query.data;
  return (
    <Dialog.Root open={evidenceId !== null} onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-navy/50" />
        <Dialog.Content className="fixed inset-y-0 right-0 z-50 flex w-[min(40rem,100vw)] flex-col bg-background shadow-pop">
          <div className="flex items-center justify-between border-b border-border p-4">
            <Dialog.Title className="text-lg font-semibold text-navy dark:text-foreground">Evidence</Dialog.Title>
            <Dialog.Close className="rounded-md p-2 hover:bg-muted" aria-label="Close evidence">
              <X aria-hidden="true" className="size-5" />
            </Dialog.Close>
          </div>
          <Dialog.Description className="sr-only">Extractor output for one item</Dialog.Description>
          <div className="flex-1 overflow-y-auto p-4">
            {query.isLoading && <Skeleton className="h-40" />}
            {query.isError && <ErrorNote error={query.error} retry={() => void query.refetch()} />}
            {e && (
              <>
                <dl className="grid grid-cols-[8rem_1fr] gap-x-3 gap-y-2 text-sm">
                  <dt className="text-muted-foreground">Extractor</dt>
                  <dd className="font-semibold">{e.extractor}</dd>
                  <dt className="text-muted-foreground">Status</dt>
                  <dd>{e.status}</dd>
                  <dt className="text-muted-foreground">Duration</dt>
                  <dd>{e.duration_ms === null ? "Not recorded" : `${e.duration_ms} ms`}</dd>
                  <dt className="text-muted-foreground">Command</dt>
                  <dd className="break-all font-mono text-xs">{e.command ?? "None"}</dd>
                  <dt className="text-muted-foreground">Recorded</dt>
                  <dd>{formatDateTime(e.created_at)}</dd>
                  <dt className="text-muted-foreground">SHA-256</dt>
                  <dd className="break-all font-mono text-xs">{e.raw_sha256 ?? "None"}</dd>
                </dl>
                {e.error && (
                  <p role="alert" className="mt-3 rounded-md bg-danger/10 p-3 text-sm text-danger">
                    {e.error}
                  </p>
                )}
                <h3 className="mb-2 mt-5 text-base">Output{e.raw_truncated ? " (truncated)" : ""}</h3>
                {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
                <pre tabIndex={0} className="max-h-[50vh] overflow-auto rounded-md bg-navy p-3 text-xs text-white">
                  {JSON.stringify(e.raw_output, null, 2)}
                </pre>
              </>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

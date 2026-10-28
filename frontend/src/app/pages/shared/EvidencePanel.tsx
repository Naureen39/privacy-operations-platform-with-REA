import { Upload } from "lucide-react";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { useAction, useEvidence } from "../../hooks/data";
import { useSession } from "../../session";
import { formatDateTime } from "../../ui/kit";
import { DataTable } from "../../ui/DataTable";
import { Select } from "../../ui/parts";
import type { Evidence } from "../../types";

export const EVIDENCE_KINDS = [
  { value: "privacy_policy", label: "Privacy notice (text or PDF)" },
  { value: "questionnaire", label: "Questionnaire (JSON)" },
  { value: "har", label: "Network capture (HAR)" },
  { value: "sqlite_snapshot", label: "Database snapshot (SQLite)" },
  { value: "javascript_bundle", label: "JavaScript bundle" },
  { value: "website", label: "Saved web page" },
  { value: "vendor_agreement", label: "Vendor agreement" },
];

function size(bytes: number): string {
  return bytes < 1024
    ? `${bytes} B`
    : bytes < 1048576
      ? `${(bytes / 1024).toFixed(1)} KB`
      : `${(bytes / 1048576).toFixed(1)} MB`;
}

/** Evidence of one system: what is attached, and the controls to attach more (a file or a URL on
 *  the observation allowlist). */
export function EvidencePanel({ systemId }: { systemId: string }) {
  const { can } = useSession();
  const evidence = useEvidence(systemId);
  const [kind, setKind] = useState("privacy_policy");
  const [url, setUrl] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const upload = useAction({
    run: async (file: File) => {
      const form = new FormData();
      form.append("kind", kind);
      form.append("file", file);
      return api.post<Evidence>(`/api/v1/systems/${systemId}/evidence`, form);
    },
    success: (e) => `Attached ${e.filename}`,
    invalidate: [["evidence", systemId]],
    onDone: () => {
      if (fileRef.current) fileRef.current.value = "";
    },
  });
  const register = useAction({
    run: (value: string) => api.post<Evidence>(`/api/v1/systems/${systemId}/evidence/url`, { url: value }),
    success: "The address was accepted for observation",
    invalidate: [["evidence", systemId]],
    onDone: () => setUrl(""),
  });

  return (
    <div className="space-y-5">
      {can("upload") && (
        <div className="grid gap-4 rounded-lg border border-border bg-card p-4 md:grid-cols-2">
          <form
            className="space-y-3"
            aria-label="Attach a file"
            onSubmit={(e) => {
              e.preventDefault();
              const file = fileRef.current?.files?.[0];
              if (file) upload.mutate(file);
            }}
          >
            <Select id={`kind-${systemId}`} label="Type" value={kind} onChange={setKind} options={EVIDENCE_KINDS} />
            <div>
              <label
                htmlFor={`file-${systemId}`}
                className="mb-1 block text-sm font-medium text-navy dark:text-foreground"
              >
                File
              </label>
              <input id={`file-${systemId}`} ref={fileRef} type="file" className="block w-full text-sm" required />
            </div>
            <Button type="submit" disabled={upload.isPending}>
              <Upload aria-hidden="true" /> {upload.isPending ? "Uploading..." : "Attach file"}
            </Button>
          </form>
          <form
            className="space-y-3"
            aria-label="Observe an address"
            onSubmit={(e) => {
              e.preventDefault();
              if (url.trim()) register.mutate(url.trim());
            }}
          >
            <div>
              <label
                htmlFor={`url-${systemId}`}
                className="mb-1 block text-sm font-medium text-navy dark:text-foreground"
              >
                Web address to observe
              </label>
              <Input
                id={`url-${systemId}`}
                type="url"
                placeholder="https://shop.example.test/"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
              />
              <p className="mt-1 text-xs text-muted-foreground">Only addresses on the allowlist are accepted.</p>
            </div>
            <Button type="submit" variant="secondary" disabled={register.isPending || !url.trim()}>
              Register address
            </Button>
          </form>
        </div>
      )}
      <DataTable<Evidence>
        data={evidence.data ?? []}
        loading={evidence.isLoading}
        caption="Evidence"
        searchPlaceholder="Search evidence"
        empty={{ title: "No evidence yet", text: "Attach a notice, a questionnaire, a capture or a schema to begin." }}
        columns={[
          { accessorKey: "filename", header: "File" },
          { accessorKey: "kind", header: "Type", cell: (c) => String(c.getValue()).replaceAll("_", " ") },
          { accessorKey: "size_bytes", header: "Size", cell: (c) => size(Number(c.getValue())) },
          { accessorKey: "created_at", header: "Attached", cell: (c) => formatDateTime(String(c.getValue())) },
          { accessorKey: "encrypted", header: "Encrypted", cell: (c) => (c.getValue() ? "Yes" : "No") },
        ]}
      />
    </div>
  );
}

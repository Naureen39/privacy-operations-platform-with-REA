import { useMutation, useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";

import { api, ApiError } from "@/lib/api";
import { useToast } from "../ui/toast";
import type {
  Activity,
  AuditEntry,
  DataElement,
  Dpia,
  DpiaSummary,
  Evidence,
  Finding,
  InvoiceSummary,
  Job,
  Notification,
  Recipient,
  RequestItem,
  ReviewItem,
  System,
  Task,
  Technology,
  Vendor,
  Version,
} from "../types";

const LIST = { limit: 200 };

export const useSystems = () =>
  useQuery({ queryKey: ["systems"], queryFn: () => api.get<System[]>("/api/v1/systems", LIST) });
export const useSystem = (id: string) =>
  useQuery({ queryKey: ["system", id], queryFn: () => api.get<System>(`/api/v1/systems/${id}`) });
export const useEvidence = (id: string) =>
  useQuery({ queryKey: ["evidence", id], queryFn: () => api.get<Evidence[]>(`/api/v1/systems/${id}/evidence`, LIST) });
export const useElements = (id: string) =>
  useQuery({
    queryKey: ["elements", id],
    queryFn: () => api.get<DataElement[]>(`/api/v1/systems/${id}/data-elements`, LIST),
  });
export const useRecipients = (id: string) =>
  useQuery({
    queryKey: ["recipients", id],
    queryFn: () => api.get<Recipient[]>(`/api/v1/systems/${id}/recipients`, LIST),
  });
export const useTechnologies = (id: string) =>
  useQuery({
    queryKey: ["technologies", id],
    queryFn: () => api.get<Technology[]>(`/api/v1/systems/${id}/technologies`, LIST),
  });

export const useActivities = () =>
  useQuery({ queryKey: ["activities"], queryFn: () => api.get<Activity[]>("/api/v1/activities", LIST) });
export const useActivity = (id: string) =>
  useQuery({ queryKey: ["activity", id], queryFn: () => api.get<Activity>(`/api/v1/activities/${id}`) });
export const useVersions = (id: string) =>
  useQuery({ queryKey: ["versions", id], queryFn: () => api.get<Version[]>(`/api/v1/activities/${id}/versions`) });

export const useFindings = (params: Record<string, string> = {}) =>
  useQuery({
    queryKey: ["findings", params],
    queryFn: () => api.get<Finding[]>("/api/v1/findings", { ...LIST, ...params }),
  });
export const useDpias = () =>
  useQuery({ queryKey: ["dpias"], queryFn: () => api.get<DpiaSummary[]>("/api/v1/dpias", LIST) });
export const useDpia = (id: string) =>
  useQuery({ queryKey: ["dpia", id], queryFn: () => api.get<Dpia>(`/api/v1/dpias/${id}`) });
export const useRequests = () =>
  useQuery({ queryKey: ["requests"], queryFn: () => api.get<RequestItem[]>("/api/v1/access-requests", LIST) });
export const useVendors = () =>
  useQuery({ queryKey: ["vendors"], queryFn: () => api.get<Vendor[]>("/api/v1/vendors", LIST) });
export const useTasks = () => useQuery({ queryKey: ["tasks"], queryFn: () => api.get<Task[]>("/api/v1/tasks", LIST) });
export const useReviewQueue = () =>
  useQuery({ queryKey: ["review-queue"], queryFn: () => api.get<ReviewItem[]>("/api/v1/review-queue", LIST) });
export const useReminders = () =>
  useQuery({ queryKey: ["reminders"], queryFn: () => api.get<RequestItem[]>("/api/v1/access-requests/reminders") });
export const useNotifications = () =>
  useQuery({
    queryKey: ["notifications"],
    queryFn: () => api.get<Notification[]>("/api/v1/notifications", { limit: 30 }),
    refetchInterval: 60_000,
  });
export const useAudit = (params: Record<string, string>) =>
  useQuery({
    queryKey: ["audit", params],
    queryFn: () => api.page<AuditEntry>("/api/v1/audit-log", { limit: 50, ...params }),
  });
export const useInvoices = () =>
  useQuery({
    queryKey: ["invoices"],
    queryFn: () => api.get<InvoiceSummary[]>("/api/v1/billing/invoices", LIST),
  });
export const useJob = (id: string | null) =>
  useQuery({
    queryKey: ["job", id],
    enabled: id !== null,
    queryFn: () => api.get<Job>(`/api/v1/jobs/${id}`),
    refetchInterval: (query) => {
      const state = query.state.data?.state;
      return state === "queued" || state === "running" || state === undefined ? 1500 : false;
    },
  });

/** A mutation that reports success and failure as toasts and refreshes the listed queries. */
export function useAction<TInput, TOutput>(options: {
  run: (input: TInput) => Promise<TOutput>;
  success?: string | ((output: TOutput) => string);
  invalidate?: QueryKey[];
  onDone?: (output: TOutput) => void;
}) {
  const toast = useToast();
  const client = useQueryClient();
  return useMutation({
    mutationFn: options.run,
    onSuccess: async (output) => {
      for (const key of options.invalidate ?? []) await client.invalidateQueries({ queryKey: key });
      if (options.success)
        toast.success(typeof options.success === "function" ? options.success(output) : options.success);
      options.onDone?.(output);
    },
    onError: (error) => {
      toast.error(
        error instanceof ApiError ? error.message : "Something went wrong.",
        error instanceof ApiError && error.requestId ? `Reference: ${error.requestId}` : undefined,
      );
    },
  });
}

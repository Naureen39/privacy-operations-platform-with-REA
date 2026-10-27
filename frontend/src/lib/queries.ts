import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";

import { api, type PublicMetrics } from "./api";
import { fetchPlans, FALLBACK_PLANS, type Plan } from "./plans";

export function usePublicMetrics() {
  return useQuery({
    queryKey: ["public-metrics"],
    queryFn: () => api.get<PublicMetrics>("/api/v1/public/metrics"),
    staleTime: 60_000,
    retry: 1,
  });
}

/** The price list from the API, or the seeded defaults when the API cannot be reached. */
export function usePlans(): { plans: Plan[]; live: boolean; loading: boolean } {
  const query = useQuery({ queryKey: ["public-plans"], queryFn: fetchPlans, staleTime: 300_000, retry: 1 });
  if (query.data && query.data.length > 0) return { plans: query.data, live: true, loading: false };
  return { plans: FALLBACK_PLANS, live: false, loading: query.isLoading };
}

/** Sets the document title and the description for the page. */
export function usePageMeta(title: string, description?: string): void {
  useEffect(() => {
    document.title = title === "ProcessLedger" ? title : `${title} | ProcessLedger`;
    if (description) {
      let tag = document.querySelector<HTMLMetaElement>('meta[name="description"]');
      if (!tag) {
        tag = document.createElement("meta");
        tag.name = "description";
        document.head.appendChild(tag);
      }
      tag.content = description;
    }
  }, [title, description]);
}

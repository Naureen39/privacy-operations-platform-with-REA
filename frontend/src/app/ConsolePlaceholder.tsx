import { useQuery } from "@tanstack/react-query";
import { Navigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { api, ApiError, type Session } from "@/lib/api";
import { usePageMeta } from "@/lib/queries";

interface Me {
  user: Session["user"];
  org_id: string;
  role: Session["role"];
}

/** The signed in landing point until the console is built. It confirms the session and signs out. */
export default function ConsolePlaceholder() {
  usePageMeta("Console");
  const { data, error, isLoading } = useQuery({
    queryKey: ["me"],
    queryFn: () => api.get<Me>("/api/v1/auth/me"),
    retry: 0,
  });
  if (isLoading)
    return (
      <p className="p-8" aria-busy="true">
        Loading...
      </p>
    );
  if (error instanceof ApiError && error.status === 401) return <Navigate to="/login" replace />;
  if (!data)
    return (
      <p role="alert" className="p-8">
        The console could not be loaded. Please try again.
      </p>
    );
  return (
    <main id="main" className="container max-w-2xl py-24 text-center">
      <p className="eyebrow">Console</p>
      <h1 className="text-4xl">You are signed in</h1>
      <p className="lead mt-4">
        {data.user.full_name} ({data.role.replace("_", " ")}). The authenticated console is the next piece of work; the
        API behind it is complete.
      </p>
      <Button
        className="mt-8"
        variant="secondary"
        onClick={async () => {
          await api.post("/api/v1/auth/logout").catch(() => undefined);
          window.location.assign("/login");
        }}
      >
        Sign out
      </Button>
    </main>
  );
}

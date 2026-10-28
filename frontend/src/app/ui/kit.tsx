import { AlertTriangle, Inbox } from "lucide-react";
import { Component, type ErrorInfo, type ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden="true" className={cn("animate-pulse rounded-md bg-muted", className)} />;
}

export function SkeletonRows({ rows = 5 }: { rows?: number }) {
  return (
    <div role="status" aria-label="Loading" className="space-y-3">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </div>
  );
}

export function EmptyState({ title, text, action }: { title: string; text?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center rounded-lg border border-dashed border-border px-6 py-12 text-center">
      <Inbox aria-hidden="true" className="mb-3 size-8 text-muted-foreground" />
      <p className="text-lg font-semibold text-navy dark:text-foreground">{title}</p>
      {text && <p className="mt-1 max-w-md text-muted-foreground">{text}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorNote({ error, retry }: { error: unknown; retry?: () => void }) {
  const message = error instanceof ApiError ? error.message : "Something went wrong.";
  const id = error instanceof ApiError ? error.requestId : null;
  return (
    <div role="alert" className="flex items-start gap-3 rounded-lg border border-danger/40 bg-danger/10 p-4">
      <AlertTriangle aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-danger" />
      <div className="flex-1">
        <p className="font-semibold text-foreground">{message}</p>
        {id && <p className="text-xs text-muted-foreground">Reference: {id}</p>}
      </div>
      {retry && (
        <Button size="sm" variant="secondary" onClick={retry}>
          Try again
        </Button>
      )}
    </div>
  );
}

interface BoundaryState {
  failed: boolean;
}

/** Catches a render error in a page so the rest of the console keeps working. */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, BoundaryState> {
  override state: BoundaryState = { failed: false };

  static getDerivedStateFromError(): BoundaryState {
    return { failed: true };
  }

  override componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Console page failed", error, info.componentStack);
  }

  override componentDidUpdate(prev: { resetKey?: string }) {
    if (prev.resetKey !== this.props.resetKey && this.state.failed) this.setState({ failed: false });
  }

  override render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div role="alert" className="mx-auto max-w-lg py-20 text-center">
        <h1 className="text-2xl">This page could not be shown</h1>
        <p className="mt-2 text-muted-foreground">An unexpected error occurred. The rest of the console still works.</p>
        <Button className="mt-6" onClick={() => this.setState({ failed: false })}>
          Try again
        </Button>
      </div>
    );
  }
}

const severityTone = { critical: "red", high: "red", medium: "amber", low: "blue" } as const;

export function SeverityBadge({ value }: { value: string }) {
  const tone: string = severityTone[value as keyof typeof severityTone] ?? "neutral";
  return (
    <span
      className={cn(
        "inline-flex rounded-full px-2.5 py-0.5 text-xs font-semibold capitalize",
        tone === "red" && "bg-danger/10 text-[rgb(150_20_30)]",
        tone === "amber" && "bg-warning/15 text-[rgb(110_63_0)]",
        tone === "blue" && "bg-primary/10 text-primary-hover",
        tone === "neutral" && "bg-muted text-navy",
      )}
    >
      {value}
    </span>
  );
}

const statusTone: Record<string, "blue" | "teal" | "amber" | "green" | "neutral"> = {
  draft: "neutral",
  in_review: "amber",
  awaiting_review: "amber",
  awaiting_approval: "amber",
  approved: "green",
  published: "green",
  rejected: "neutral",
  open: "amber",
  acknowledged: "blue",
  resolved: "green",
  dismissed: "neutral",
  responded: "green",
  closed: "green",
  active: "green",
  paid: "green",
  overdue: "amber",
  void: "neutral",
};

export function StatusBadge({ value }: { value: string }) {
  return <Badge tone={statusTone[value] ?? "blue"}>{value.replaceAll("_", " ")}</Badge>;
}

export function Money({ cents }: { cents: number }) {
  return (
    <>
      {new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(
        cents / 100,
      )}
    </>
  );
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "None";
  const d = new Date(value);
  return Number.isNaN(d.getTime())
    ? value
    : d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "None";
  const d = new Date(value);
  return Number.isNaN(d.getTime())
    ? value
    : d.toLocaleString("en-US", {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
}

export function compact(n: number): string {
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(n);
}

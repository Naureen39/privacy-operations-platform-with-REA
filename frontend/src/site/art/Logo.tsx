import { cn } from "@/lib/utils";

export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={cn("size-8", className)} aria-hidden="true" focusable="false">
      <rect width="32" height="32" rx="8" fill="#0F62FE" />
      <path d="M9 10h14M9 16h14M9 22h8" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" />
      <circle cx="23" cy="22" r="3" fill="#00A3A3" />
    </svg>
  );
}

export function Logo({ inverse = false, className }: { inverse?: boolean; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <LogoMark />
      <span className={cn("text-lg font-bold tracking-tight", inverse ? "text-white" : "text-navy")}>
        ProcessLedger
      </span>
    </span>
  );
}

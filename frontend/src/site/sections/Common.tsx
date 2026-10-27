import { ArrowRight } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function PageHero({
  eyebrow,
  title,
  lead,
  children,
}: {
  eyebrow?: string;
  title: string;
  lead?: string;
  children?: ReactNode;
}) {
  return (
    <section className="border-b border-border bg-surface">
      <div className="container py-14 md:py-20">
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h1 className="max-w-3xl text-4xl md:text-5xl">{title}</h1>
        {lead && <p className="lead mt-5 max-w-3xl">{lead}</p>}
        {children && <div className="mt-8">{children}</div>}
      </div>
    </section>
  );
}

export function SectionHeading({
  eyebrow,
  title,
  lead,
  center = false,
}: {
  eyebrow?: string;
  title: string;
  lead?: string;
  center?: boolean;
}) {
  return (
    <div className={cn("mb-10 max-w-3xl", center && "mx-auto text-center")}>
      {eyebrow && <p className="eyebrow">{eyebrow}</p>}
      <h2 className="text-3xl md:text-4xl">{title}</h2>
      {lead && <p className="lead mt-4">{lead}</p>}
    </div>
  );
}

export function CtaBand({
  title = "See it on the reference estate",
  text = "Sign in to the seeded demonstration environment, or send us a message.",
}: {
  title?: string;
  text?: string;
}) {
  return (
    <section className="bg-navy text-white">
      <div className="container flex flex-col items-start justify-between gap-6 py-14 md:flex-row md:items-center">
        <div className="max-w-2xl">
          <h2 className="text-3xl text-white">{title}</h2>
          <p className="mt-2 text-lg text-white/80">{text}</p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Button asChild variant="inverse" size="lg">
            <Link to="/login">
              Open console <ArrowRight aria-hidden="true" />
            </Link>
          </Button>
          <Button asChild variant="outlineInverse" size="lg">
            <Link to="/contact?tab=demo">Request a demo</Link>
          </Button>
        </div>
      </div>
    </section>
  );
}

export function Notice({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "warn" }) {
  return (
    <p
      className={cn(
        "rounded-md border p-4 text-sm",
        tone === "warn"
          ? "border-warning/40 bg-warning/10 text-foreground"
          : "border-primary/30 bg-primary/5 text-foreground",
      )}
    >
      {children}
    </p>
  );
}

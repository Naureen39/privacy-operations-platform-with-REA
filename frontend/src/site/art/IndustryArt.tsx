import { Banknote, Building2, Cpu, HeartPulse, ShoppingBag, type LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";
import type { Industry } from "../content/site";

const icons: Record<string, LucideIcon> = {
  healthcare: HeartPulse,
  retail: ShoppingBag,
  "financial-services": Banknote,
  "public-sector": Building2,
  technology: Cpu,
};

/** A generated tile in place of a photograph: a gradient from the brand palette, a pattern and an icon. */
export function IndustryArt({ industry, className }: { industry: Industry; className?: string }) {
  const Icon = icons[industry.slug] ?? Cpu;
  const id = `pat-${industry.slug}`;
  return (
    <div
      className={cn("relative overflow-hidden", className)}
      style={{ background: `linear-gradient(135deg, ${industry.from}, ${industry.to})` }}
      aria-hidden="true"
    >
      <svg className="absolute inset-0 size-full opacity-25" width="100%" height="100%">
        <defs>
          <pattern id={id} width="28" height="28" patternUnits="userSpaceOnUse">
            <circle cx="2" cy="2" r="1.6" fill="#fff" />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill={`url(#${id})`} />
      </svg>
      <Icon className="absolute bottom-4 right-4 size-16 text-white/90" strokeWidth={1.25} />
    </div>
  );
}

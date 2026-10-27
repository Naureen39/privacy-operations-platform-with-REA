import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/utils";

const badgeVariants = cva("inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold", {
  variants: {
    tone: {
      neutral: "bg-muted text-navy",
      blue: "bg-primary/10 text-primary-hover",
      teal: "bg-accent/15 text-[rgb(0_99_99)]",
      amber: "bg-warning/15 text-[rgb(110_63_0)]",
      green: "bg-success/15 text-[rgb(8_88_47)]",
    },
  },
  defaultVariants: { tone: "neutral" },
});

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}

import { animate, useInView, useReducedMotion } from "framer-motion";
import { useEffect, useRef, useState } from "react";

import { usePublicMetrics } from "@/lib/queries";

export function Counter({ value }: { value: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true });
  const reduce = useReducedMotion();
  const [animated, setAnimated] = useState(0);
  useEffect(() => {
    if (reduce || !inView) return;
    const controls = animate(0, value, { duration: 1.2, ease: "easeOut", onUpdate: (v) => setAnimated(Math.round(v)) });
    return () => controls.stop();
  }, [inView, reduce, value]);
  const shown = reduce ? value : animated;
  return (
    <span ref={ref} aria-label={value.toLocaleString("en-US")}>
      {shown.toLocaleString("en-US")}
    </span>
  );
}

/** Headline figures from the public metrics endpoint, labelled as the demonstration environment. */
export function MetricBand() {
  const { data, isError, isLoading } = usePublicMetrics();
  if (isError) return null;
  const items = data
    ? [
        { label: "Organizations", value: data.accounts },
        { label: "Systems onboarded", value: data.systems },
        { label: "Requests handled (latest day)", value: data.requests },
        { label: "Regulation passages indexed", value: data.regulation_passages },
      ]
    : [];
  return (
    <section aria-label="Demonstration environment figures" className="border-y border-border bg-surface">
      <div className="container py-10">
        {isLoading ? (
          <p className="text-center text-sm text-muted-foreground">Loading figures...</p>
        ) : (
          <>
            <dl className="grid grid-cols-2 gap-6 text-center lg:grid-cols-4">
              {items.map((m) => (
                <div key={m.label}>
                  <dd className="text-4xl font-bold text-navy">
                    <Counter value={m.value} />
                  </dd>
                  <dt className="mt-1 text-sm text-muted-foreground">{m.label}</dt>
                </div>
              ))}
            </dl>
            <p className="mt-6 text-center text-xs text-muted-foreground">
              Demo environment figures{data?.as_of ? `, as of ${data.as_of}` : ""}. {data?.note}
            </p>
          </>
        )}
      </div>
    </section>
  );
}

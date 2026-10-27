import { lazy, Suspense, useId, useState } from "react";

import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { estimate, formatMoney, recommend, type Plan } from "@/lib/plans";

const CostChart = lazy(() => import("@/charts/CostChart"));

function clamp(value: number, max: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.min(max, Math.max(0, Math.round(value)));
}

export function CostCalculator({ plans }: { plans: Plan[] }) {
  const [systems, setSystems] = useState(12);
  const [requests, setRequests] = useState(30);
  const sid = useId();
  const rid = useId();
  const best = recommend(plans, systems, requests);
  return (
    <div className="grid grid-cols-1 gap-8 lg:grid-cols-[1fr_1.4fr]">
      <Card>
        <CardContent className="space-y-6">
          <div className="space-y-2">
            <Label htmlFor={sid}>Systems that process personal data</Label>
            <Input
              id={sid}
              type="number"
              inputMode="numeric"
              min={0}
              max={1000}
              value={systems}
              onChange={(e) => setSystems(clamp(e.target.valueAsNumber, 1000))}
            />
            <input
              aria-label="Systems slider"
              type="range"
              min={0}
              max={200}
              value={Math.min(systems, 200)}
              onChange={(e) => setSystems(Number(e.target.value))}
              className="w-full accent-primary"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor={rid}>Access requests handled each month</Label>
            <Input
              id={rid}
              type="number"
              inputMode="numeric"
              min={0}
              max={5000}
              value={requests}
              onChange={(e) => setRequests(clamp(e.target.valueAsNumber, 5000))}
            />
            <input
              aria-label="Requests slider"
              type="range"
              min={0}
              max={600}
              value={Math.min(requests, 600)}
              onChange={(e) => setRequests(Number(e.target.value))}
              className="w-full accent-primary"
            />
          </div>
          <div aria-live="polite" className="rounded-md bg-surface p-4">
            {best ? (
              <>
                <p className="text-sm text-muted-foreground">Estimated monthly cost</p>
                <p className="text-4xl font-bold text-navy">{formatMoney(best.totalCents)}</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  on the <strong>{best.plan.name}</strong> plan, the lowest cost that fits.
                </p>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">No plan fits this usage.</p>
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            An estimate for the demonstration. Billing is simulated and no payment is taken.
          </p>
        </CardContent>
      </Card>
      <div className="min-w-0 space-y-6">
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Estimated monthly cost by plan</caption>
            <thead className="bg-muted text-navy">
              <tr>
                <th scope="col" className="px-4 py-3">
                  Plan
                </th>
                <th scope="col" className="px-4 py-3">
                  Base
                </th>
                <th scope="col" className="px-4 py-3">
                  Extra systems
                </th>
                <th scope="col" className="px-4 py-3">
                  Extra requests
                </th>
                <th scope="col" className="px-4 py-3">
                  Total
                </th>
              </tr>
            </thead>
            <tbody>
              {plans.map((p) => {
                const e = estimate(p, systems, requests);
                return (
                  <tr key={p.code} className="border-t border-border">
                    <th scope="row" className="px-4 py-3 font-semibold text-navy">
                      {p.name}{" "}
                      {best?.plan.code === p.code && (
                        <Badge tone="blue" className="ml-1">
                          Best fit
                        </Badge>
                      )}
                    </th>
                    <td className="px-4 py-3">{formatMoney(e.baseCents)}</td>
                    <td className="px-4 py-3">{e.fits ? formatMoney(e.extraSystemsCents) : "Over the allowance"}</td>
                    <td className="px-4 py-3">{e.fits ? formatMoney(e.extraRequestsCents) : "Over the allowance"}</td>
                    <td className="px-4 py-3 font-semibold">{e.fits ? formatMoney(e.totalCents) : "Not available"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <Suspense fallback={<div className="h-80" aria-busy="true" />}>
          <figure>
            <CostChart plans={plans} requests={requests} />
            <figcaption className="text-sm text-muted-foreground">
              Monthly cost by number of systems at {requests} requests a month. A line stops where the plan cannot take
              the usage.
            </figcaption>
          </figure>
        </Suspense>
      </div>
    </div>
  );
}

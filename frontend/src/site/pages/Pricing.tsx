import { Check } from "lucide-react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { formatMoney, type Plan } from "@/lib/plans";
import { usePageMeta, usePlans } from "@/lib/queries";
import { cn } from "@/lib/utils";
import { CostCalculator } from "../sections/CostCalculator";
import { CtaBand, Notice, PageHero, SectionHeading } from "../sections/Common";

function priceOf(p: Plan): string {
  return p.monthly_fee_cents === 0 ? "Free" : `${formatMoney(p.monthly_fee_cents)}`;
}

function features(p: Plan): string[] {
  const list = [
    `Up to ${p.included_systems} systems`,
    `${p.included_requests} access requests a month`,
    "Records, assessments and findings",
  ];
  list.push(
    p.extra_system_cents > 0
      ? `${formatMoney(p.extra_system_cents)} per extra system, ${formatMoney(p.extra_request_cents)} per extra request`
      : "No overage: move up when you outgrow it",
  );
  return list;
}

export default function Pricing() {
  usePageMeta("Pricing", "Three illustrative plans and a cost calculator. Billing in the demonstration is simulated.");
  const { plans, live } = usePlans();
  return (
    <>
      <PageHero
        eyebrow="Pricing"
        title="Three plans, priced by systems and requests"
        lead="Prices are illustrative. There is no payment processor and no real customer in this demonstration."
      />
      <section className="section">
        <div className="container">
          <ul className="grid gap-6 lg:grid-cols-3">
            {plans.map((p) => {
              const featured = p.code === "professional";
              return (
                <li key={p.code}>
                  <Card className={cn("h-full", featured && "border-primary ring-1 ring-primary")}>
                    <CardContent className="flex h-full flex-col">
                      <div className="flex items-center justify-between">
                        <h2 className="text-2xl">{p.name}</h2>
                        {featured && <Badge tone="blue">Pay for what you use</Badge>}
                      </div>
                      <p className="mt-4 text-4xl font-bold text-navy">
                        {priceOf(p)}
                        {p.monthly_fee_cents > 0 && (
                          <span className="text-base font-normal text-muted-foreground"> a month</span>
                        )}
                      </p>
                      <ul className="mt-6 flex-1 space-y-3">
                        {features(p).map((f) => (
                          <li key={f} className="flex gap-2 text-muted-foreground">
                            <Check aria-hidden="true" className="mt-1 size-4 shrink-0 text-success" />
                            {f}
                          </li>
                        ))}
                      </ul>
                      <Button asChild variant={featured ? "primary" : "secondary"} className="mt-8">
                        <Link to="/contact?tab=demo">Request a demo</Link>
                      </Button>
                    </CardContent>
                  </Card>
                </li>
              );
            })}
          </ul>
          {!live && (
            <div className="mt-6">
              <Notice tone="warn">The live price list could not be loaded, so the default plans are shown.</Notice>
            </div>
          )}
        </div>
      </section>

      <section className="section bg-surface">
        <div className="container">
          <SectionHeading eyebrow="Compare" title="What each plan includes" />
          <div className="overflow-x-auto rounded-lg border border-border bg-background">
            <table className="w-full min-w-[640px] text-left text-sm">
              <caption className="sr-only">Plan comparison</caption>
              <thead className="bg-muted text-navy">
                <tr>
                  <th scope="col" className="px-4 py-3">
                    Feature
                  </th>
                  {plans.map((p) => (
                    <th key={p.code} scope="col" className="px-4 py-3">
                      {p.name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[
                  [
                    "Base fee",
                    (p: Plan) => (p.monthly_fee_cents === 0 ? "Free" : `${formatMoney(p.monthly_fee_cents)} a month`),
                  ],
                  ["Systems included", (p: Plan) => String(p.included_systems)],
                  ["Requests included each month", (p: Plan) => String(p.included_requests)],
                  [
                    "Each extra system",
                    (p: Plan) => (p.extra_system_cents ? formatMoney(p.extra_system_cents) : "Not available"),
                  ],
                  [
                    "Each extra request",
                    (p: Plan) => (p.extra_request_cents ? formatMoney(p.extra_request_cents) : "Not available"),
                  ],
                ].map(([label, fn]) => (
                  <tr key={String(label)} className="border-t border-border">
                    <th scope="row" className="px-4 py-3 font-semibold text-navy">
                      {String(label)}
                    </th>
                    {plans.map((p) => (
                      <td key={p.code} className="px-4 py-3">
                        {(fn as (p: Plan) => string)(p)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section id="calculator" className="section scroll-mt-24">
        <div className="container">
          <SectionHeading
            eyebrow="Cost calculator"
            title="Estimate your monthly cost"
            lead="Move the sliders. The estimate uses the same formula as the invoice run: the base fee plus anything beyond the allowance."
          />
          <CostCalculator plans={plans} />
        </div>
      </section>
      <CtaBand />
    </>
  );
}

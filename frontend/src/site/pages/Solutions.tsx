import { ArrowRight } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { usePageMeta } from "@/lib/queries";
import { IndustryArt } from "../art/IndustryArt";
import { industries } from "../content/site";
import { CtaBand, Notice, PageHero, SectionHeading } from "../sections/Common";
import NotFound from "./NotFound";

export function SolutionsIndex() {
  usePageMeta(
    "Solutions",
    "ProcessLedger scenarios for healthcare, retail, financial services, public sector and technology.",
  );
  return (
    <>
      <PageHero
        eyebrow="Solutions"
        title="The same evidence based approach, five sectors"
        lead="Each page describes the challenge, the approach and a sample outcome drawn from the reference estate, a fictional retailer with a clinic arm."
      />
      <section className="section">
        <div className="container">
          <ul className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {industries.map((industry) => (
              <li key={industry.slug}>
                <Link
                  to={`/solutions/${industry.slug}`}
                  className="group block overflow-hidden rounded-lg border border-border bg-card shadow-card hover:shadow-pop"
                >
                  <IndustryArt industry={industry} className="h-40" />
                  <div className="p-5">
                    <h2 className="text-xl group-hover:text-primary">{industry.name}</h2>
                    <p className="mt-1 text-muted-foreground">{industry.short}</p>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      </section>
    </>
  );
}

export function IndustryPage() {
  const { slug } = useParams();
  const industry = industries.find((i) => i.slug === slug);
  usePageMeta(industry ? industry.name : "Solutions", industry?.short);
  if (!industry) return <NotFound />;
  return (
    <>
      <PageHero eyebrow={`Solutions: ${industry.name}`} title={industry.short} />
      <section className="section">
        <div className="container grid gap-10 lg:grid-cols-[1.4fr_1fr]">
          <div className="space-y-10">
            {[
              ["The challenge", industry.challenge],
              ["The approach", industry.approach],
              ["A sample outcome", industry.outcome],
            ].map(([title, text]) => (
              <div key={title}>
                <SectionHeading title={title ?? ""} />
                <p className="-mt-6 text-lg text-muted-foreground">{text}</p>
              </div>
            ))}
            <Notice>
              This is a sample scenario based on a fictional organization. It is not a customer story and the figures
              are not from real operations.
            </Notice>
          </div>
          <aside className="space-y-6">
            <IndustryArt industry={industry} className="h-56 rounded-lg" />
            <Button asChild className="w-full">
              <Link to="/login">
                Explore the demo scenario <ArrowRight aria-hidden="true" />
              </Link>
            </Button>
            <Button asChild variant="secondary" className="w-full">
              <Link to="/platform">How the platform works</Link>
            </Button>
          </aside>
        </div>
      </section>
      <CtaBand />
    </>
  );
}

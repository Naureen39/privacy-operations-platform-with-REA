import { ArrowRight, Lock, ShieldCheck, ScrollText, Fingerprint } from "lucide-react";
import { lazy, Suspense } from "react";
import { Link } from "react-router-dom";

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { usePageMeta } from "@/lib/queries";
import { IndustryArt } from "../art/IndustryArt";
import { PipelineDiagram } from "../art/PipelineDiagram";
import { ProductMock } from "../art/ProductMock";
import { capabilities, cases, faqs, industries, steps, TAGLINE } from "../content/site";
import { CtaBand, SectionHeading } from "../sections/Common";
import { MetricBand } from "../sections/MetricBand";

const trust = [
  {
    icon: Lock,
    title: "Tenant isolation in the database",
    text: "Row level security separates organizations, tested through the API.",
  },
  {
    icon: Fingerprint,
    title: "Roles and sign in",
    text: "Four roles, argon2 password hashing, short lived sessions, lockout after repeated failures.",
  },
  {
    icon: ScrollText,
    title: "Audit trail",
    text: "Sign ins, approvals, exports and settings changes are logged with the actor.",
  },
  {
    icon: ShieldCheck,
    title: "Evidence handled as data",
    text: "Uploads are encrypted at rest and are never executed.",
  },
];

const Tour = lazy(() => import("../sections/ProductTour"));

export default function Home() {
  usePageMeta(
    "ProcessLedger",
    "Evidence based privacy operations: system inventory, records of processing, impact assessments and access requests. A demonstration project with sample data.",
  );
  return (
    <>
      <section className="relative overflow-hidden bg-gradient-to-b from-surface to-background">
        <div className="container grid gap-12 py-14 md:py-20 lg:grid-cols-[1.05fr_1fr] lg:items-center">
          <div className="animate-fade-up">
            <Badge tone="blue" className="mb-5">
              Demonstration project, sample data
            </Badge>
            <h1 className="text-4xl md:text-5xl lg:text-6xl">{TAGLINE}</h1>
            <p className="lead mt-6 max-w-xl">
              ProcessLedger builds records of processing from technical evidence, compares what organizations say with
              what their systems do, and keeps the proof.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Button asChild size="lg">
                <Link to="/login">
                  Open console <ArrowRight aria-hidden="true" />
                </Link>
              </Button>
              <Button asChild variant="secondary" size="lg">
                <Link to="/platform">See how it works</Link>
              </Button>
            </div>
          </div>
          <ProductMock view="dashboard" className="animate-fade-up" />
        </div>
      </section>

      <section className="section" aria-labelledby="capabilities">
        <div className="container">
          <SectionHeading
            eyebrow="Platform"
            title="Six capabilities, one body of evidence"
            lead="Each one reads from and writes to the same inventory, so a change in one place shows up everywhere it matters."
          />
          <ul className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {capabilities.map(({ title, text, icon: Icon, to }) => (
              <li key={title}>
                <Card className="h-full transition-shadow hover:shadow-pop">
                  <CardContent>
                    <span className="mb-4 inline-flex size-11 items-center justify-center rounded-md bg-primary/10 text-primary">
                      <Icon aria-hidden="true" className="size-6" />
                    </span>
                    <h3 className="text-xl">{title}</h3>
                    <p className="mt-2 text-muted-foreground">{text}</p>
                    <Link
                      to={to}
                      className="mt-4 inline-flex items-center gap-1 text-sm font-semibold text-primary hover:underline"
                    >
                      Learn more<span className="sr-only"> about {title}</span>{" "}
                      <ArrowRight aria-hidden="true" className="size-4" />
                    </Link>
                  </CardContent>
                </Card>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <MetricBand />

      <section className="section" aria-labelledby="how">
        <div className="container">
          <SectionHeading
            eyebrow="How it works"
            title="From evidence to an approved record in four steps"
            lead="Deterministic rules do the extraction and the comparison. A language model is used only where judgment is needed, inside a token budget."
          />
          <ol className="grid gap-6 md:grid-cols-4">
            {steps.map((s, i) => (
              <li key={s.title}>
                <span className="mb-3 inline-flex size-9 items-center justify-center rounded-full bg-navy text-sm font-bold text-white">
                  {i + 1}
                </span>
                <h3 className="text-lg">{s.title}</h3>
                <p className="mt-1 text-muted-foreground">{s.text}</p>
              </li>
            ))}
          </ol>
          <div className="mt-10 overflow-x-auto rounded-lg border border-border bg-surface p-4">
            <PipelineDiagram />
          </div>
        </div>
      </section>

      <section className="section bg-surface" aria-labelledby="industries">
        <div className="container">
          <SectionHeading eyebrow="Solutions" title="Built around the reference estate, applied to five sectors" />
          <ul className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {industries.map((industry) => (
              <li key={industry.slug}>
                <Link
                  to={`/solutions/${industry.slug}`}
                  className="group block overflow-hidden rounded-lg border border-border bg-card shadow-card transition-shadow hover:shadow-pop"
                >
                  <IndustryArt industry={industry} className="h-36" />
                  <div className="p-5">
                    <h3 className="text-lg group-hover:text-primary">{industry.name}</h3>
                    <p className="mt-1 text-sm text-muted-foreground">{industry.short}</p>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="section" aria-labelledby="tour">
        <div className="container">
          <SectionHeading eyebrow="Product tour" title="Look around the console" />
          <Suspense fallback={<div className="h-72" aria-busy="true" />}>
            <Tour />
          </Suspense>
        </div>
      </section>

      <section className="section bg-surface" aria-labelledby="trust">
        <div className="container">
          <SectionHeading
            eyebrow="Trust and security"
            title="Practices that are implemented and tested"
            lead="No certifications are claimed. The security page lists what exists and what is planned."
          />
          <ul className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {trust.map(({ icon: Icon, title, text }) => (
              <li key={title}>
                <Icon aria-hidden="true" className="mb-3 size-7 text-primary" />
                <h3 className="text-lg">{title}</h3>
                <p className="mt-1 text-muted-foreground">{text}</p>
              </li>
            ))}
          </ul>
          <Button asChild variant="secondary" className="mt-8">
            <Link to="/security">Read the security page</Link>
          </Button>
        </div>
      </section>

      <section className="section" aria-labelledby="cases">
        <div className="container">
          <SectionHeading
            eyebrow="Sample scenarios"
            title="What the reference estate shows"
            lead="These are illustrative scenarios from a fictional organization. They are not customer stories."
          />
          <ul className="grid gap-6 md:grid-cols-3">
            {cases.map((c) => (
              <li key={c.title}>
                <Card className="h-full">
                  <CardContent>
                    <div className="mb-3 flex items-center justify-between gap-2">
                      <Badge tone="teal">{c.industry}</Badge>
                      <Badge>Sample scenario</Badge>
                    </div>
                    <h3 className="text-xl">{c.title}</h3>
                    <p className="mt-1 text-sm font-semibold text-primary">{c.figure}</p>
                    <p className="mt-3 text-muted-foreground">{c.text}</p>
                  </CardContent>
                </Card>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="section bg-surface" aria-labelledby="faq">
        <div className="container max-w-3xl">
          <SectionHeading eyebrow="FAQ" title="Questions people ask" />
          <Accordion type="single" collapsible>
            {faqs.map((f, i) => (
              <AccordionItem key={f.q} value={`q${i}`}>
                <AccordionTrigger>{f.q}</AccordionTrigger>
                <AccordionContent>{f.a}</AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        </div>
      </section>

      <CtaBand />
    </>
  );
}

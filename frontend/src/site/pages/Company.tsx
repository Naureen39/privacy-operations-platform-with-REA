import { Link, useSearchParams } from "react-router-dom";

import { LeadForm } from "@/components/LeadForm";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { usePageMeta } from "@/lib/queries";
import { DEMO_NOTICE } from "../content/site";
import { CtaBand, Notice, PageHero, SectionHeading } from "../sections/Common";

export function Company() {
  usePageMeta("Company", "About the ProcessLedger demonstration project.");
  return (
    <>
      <PageHero
        eyebrow="Company"
        title="A demonstration of evidence based privacy operations"
        lead="ProcessLedger is a portfolio project. It shows how technical evidence, deterministic rules and a carefully bounded language model can produce privacy records that stand up to review."
      />
      <section className="section">
        <div className="container grid gap-10 lg:grid-cols-2">
          <div>
            <SectionHeading title="Why it exists" />
            <p className="-mt-6 text-lg text-muted-foreground">
              Records of processing, impact assessments and access requests are usually handled in spreadsheets that
              nobody trusts. The idea here is to start from what systems actually do, to keep the proof next to every
              statement, and to make the review step easy.
            </p>
          </div>
          <div>
            <SectionHeading title="What it is not" />
            <ul className="-mt-6 list-disc space-y-2 pl-5 text-lg text-muted-foreground">
              <li>A product with customers. {DEMO_NOTICE}</li>
              <li>Legal advice. Generated documents are drafts for a qualified professional.</li>
              <li>A certified service. See the security page for exactly what exists.</li>
            </ul>
          </div>
        </div>
      </section>
      <section className="section bg-surface">
        <div className="container">
          <SectionHeading
            title="Built with free and open source tools"
            lead="Python and FastAPI, PostgreSQL with pgvector, Celery and Redis, React and TypeScript, Tailwind CSS and Apache ECharts. Language model usage stays within free tiers."
          />
          <Button asChild variant="secondary">
            <Link to="/resources/docs/architecture">Read the architecture</Link>
          </Button>
        </div>
      </section>
      <CtaBand title="Talk to us" text="Send a message or ask for a walk through of the seeded environment." />
    </>
  );
}

export function Contact() {
  usePageMeta("Contact", "Send a message or request a demonstration of ProcessLedger.");
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "demo" ? "demo" : "contact";
  return (
    <>
      <PageHero
        eyebrow="Contact"
        title="Get in touch"
        lead="Messages are stored for the administrators of the demonstration environment."
      />
      <section className="section">
        <div className="container grid gap-10 lg:grid-cols-[1.3fr_1fr]">
          <Tabs value={tab} onValueChange={(v) => setParams(v === "demo" ? { tab: "demo" } : {})}>
            <TabsList aria-label="Form type" className="mb-6">
              <TabsTrigger value="contact">Contact</TabsTrigger>
              <TabsTrigger value="demo">Request a demo</TabsTrigger>
            </TabsList>
            <TabsContent value="contact">
              <LeadForm kind="contact" idPrefix="contact" submitLabel="Send message" />
            </TabsContent>
            <TabsContent value="demo">
              <LeadForm
                kind="demo_request"
                idPrefix="demo"
                submitLabel="Request a demo"
                messageLabel="What would you like to see?"
              />
            </TabsContent>
          </Tabs>
          <aside className="space-y-4">
            <Notice>
              Do not include personal data in your message. This is a demonstration site and no one will reply.
            </Notice>
          </aside>
        </div>
      </section>
    </>
  );
}

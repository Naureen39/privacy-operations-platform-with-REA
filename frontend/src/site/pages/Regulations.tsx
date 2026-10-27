import { Badge } from "@/components/ui/badge";
import { usePageMeta } from "@/lib/queries";
import { CtaBand, Notice, PageHero } from "../sections/Common";

const supported = [
  {
    id: "article-30",
    article: "Article 30",
    title: "Records of processing activities",
    text: "Records with purposes, categories of data subjects and data, recipients, transfers, retention and security measures. Generated from evidence, versioned, approved by a second person and exported as PDF, spreadsheet or JSON.",
  },
  {
    id: "article-35",
    article: "Article 35",
    title: "Data protection impact assessment",
    text: "Screening against the guidance criteria, a drafted assessment with a risk register that cites articles and evidence, a review workflow and an export. In the reference estate, screening matches the expected result for all eight systems.",
  },
  {
    id: "article-15",
    article: "Article 15",
    title: "Right of access",
    text: "Intake, identity checks, a deadline of one month with a recorded extension, search across systems with hashed identifiers, a drafted response and reminders.",
  },
];

const planned = [
  ["Article 28", "Processor agreement checks beyond a missing agreement finding"],
  ["Articles 16 and 17", "Rectification and erasure requests"],
  ["UK GDPR and other regimes", "Separate rule sets and deadlines"],
  ["Breach notification", "Article 33 register and clock"],
];

export default function Regulations() {
  usePageMeta("Regulations", "What ProcessLedger supports today (GDPR Articles 30, 35 and 15) and what is planned.");
  return (
    <>
      <PageHero
        eyebrow="Regulations"
        title="Three parts of the GDPR, covered end to end"
        lead="The regulation text is indexed so that every drafted statement can cite the article it relies on."
      />
      <section className="section">
        <div className="container space-y-6">
          <h2 className="text-2xl">Supported today</h2>
          {supported.map((s) => (
            <article
              key={s.id}
              id={s.id}
              className="scroll-mt-24 rounded-lg border border-border bg-card p-6 shadow-card"
            >
              <Badge tone="green">Supported</Badge>
              <h3 className="mt-3 text-2xl">
                {s.article}: {s.title}
              </h3>
              <p className="mt-2 text-lg text-muted-foreground">{s.text}</p>
            </article>
          ))}
        </div>
      </section>
      <section className="section bg-surface">
        <div className="container">
          <h2 className="mb-6 text-2xl">Roadmap</h2>
          <ul className="grid gap-4 sm:grid-cols-2">
            {planned.map(([a, b]) => (
              <li key={a} className="rounded-lg border border-dashed border-input bg-background p-5">
                <Badge tone="amber">Planned</Badge>
                <h3 className="mt-2 text-lg">{a}</h3>
                <p className="mt-1 text-muted-foreground">{b}</p>
              </li>
            ))}
          </ul>
          <div className="mt-8">
            <Notice>Draft for review by a qualified privacy professional. Not legal advice.</Notice>
          </div>
        </div>
      </section>
      <CtaBand />
    </>
  );
}

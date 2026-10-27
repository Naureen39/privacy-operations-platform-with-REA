import { usePageMeta } from "@/lib/queries";
import { PipelineDiagram } from "../art/PipelineDiagram";
import { ProductMock, type MockView } from "../art/ProductMock";
import { CtaBand, PageHero, SectionHeading } from "../sections/Common";

const evidence = [
  ["Privacy notice", "Markdown or PDF", "What the organization says it does"],
  ["Questionnaire", "JSON form", "What the system owner says about purpose, retention and recipients"],
  ["Network capture", "HAR file", "Which third parties actually receive requests, and with what identifiers"],
  ["Database schema", "SQLite file", "Which personal data fields exist and whether anything deletes them"],
  ["Scripts", "JavaScript", "Calls to external services found in source"],
  ["Website snapshot", "Saved page", "Forms, trackers and embedded resources"],
];

const sections: { id: string; title: string; text: string[]; view: MockView }[] = [
  {
    id: "inventory",
    title: "System inventory",
    view: "dashboard",
    text: [
      "Every system that processes personal data is registered with an owner, a description and its evidence. System owners see and edit only the systems they own.",
      "Onboarding runs as a background job with a live progress stream, so a system moves from evidence to a drafted record without manual steps in between.",
    ],
  },
  {
    id: "discovery",
    title: "Technical discovery",
    view: "findings",
    text: [
      "Evidence is read as data and never executed. Network captures are reduced to recipients and the identifiers they receive, database schemas to fields with a likely category, and scripts to external calls.",
      "Findings are produced by rules first. Each one lists the sources that disagree, such as a notice that denies sharing and a capture that shows it.",
    ],
  },
  {
    id: "records",
    title: "Records of processing",
    view: "record",
    text: [
      "An Article 30 record is generated from the evidence with purposes, data categories, recipients, transfers and retention. Every statement keeps a pointer to its source.",
      "Records are versioned. A change creates a new version, an approver who is not the author signs it off, and exports are available as PDF, spreadsheet and JSON.",
    ],
  },
  {
    id: "assessments",
    title: "Impact assessments",
    view: "assessment",
    text: [
      "Screening scores a processing activity against the regulator's criteria and explains which were met. For activities that need one, an assessment is drafted with retrieved regulation text and a risk register in which every risk cites an article or an item of evidence.",
    ],
  },
  {
    id: "requests",
    title: "Access requests",
    view: "request",
    text: [
      "A request is logged with its deadline, the identity is checked, and the person is searched across every system using hashed identifiers, so the search does not expose raw values.",
      "A response letter is drafted from the results. Reminders go out before the deadline, and nothing is sent without an approval.",
    ],
  },
  {
    id: "analytics",
    title: "Compliance analytics",
    view: "dashboard",
    text: [
      "Daily snapshots give approved and stale records, open findings by severity and type, assessments by status, and open and overdue requests. Charts support day, week and month views, comparison with the previous period and CSV export.",
    ],
  },
];

export default function Platform() {
  usePageMeta(
    "Platform",
    "The ProcessLedger pipeline in depth: evidence, extraction, classification, comparison and records.",
  );
  return (
    <>
      <PageHero
        eyebrow="Platform"
        title="One pipeline from evidence to an approved record"
        lead="Every record, finding and assessment traces back to the document, capture or schema it came from."
      />
      <section className="section">
        <div className="container">
          <div className="overflow-x-auto rounded-lg border border-border bg-surface p-4">
            <PipelineDiagram />
          </div>
        </div>
      </section>
      {sections.map((s, i) => (
        <section key={s.id} id={s.id} className={`section scroll-mt-24 ${i % 2 === 0 ? "bg-surface" : ""}`}>
          <div className="container grid gap-10 lg:grid-cols-2 lg:items-center">
            <div className={i % 2 === 1 ? "lg:order-2" : ""}>
              <h2 className="text-3xl">{s.title}</h2>
              {s.text.map((t) => (
                <p key={t} className="mt-4 text-lg text-muted-foreground">
                  {t}
                </p>
              ))}
            </div>
            <ProductMock view={s.view} />
          </div>
        </section>
      ))}
      <section className="section" id="evidence">
        <div className="container">
          <SectionHeading eyebrow="Evidence" title="Supported evidence types" />
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Evidence types</caption>
              <thead className="bg-muted text-navy">
                <tr>
                  <th scope="col" className="px-4 py-3">
                    Evidence
                  </th>
                  <th scope="col" className="px-4 py-3">
                    Format
                  </th>
                  <th scope="col" className="px-4 py-3">
                    What it shows
                  </th>
                </tr>
              </thead>
              <tbody>
                {evidence.map(([a, b, c]) => (
                  <tr key={a} className="border-t border-border">
                    <th scope="row" className="px-4 py-3 font-semibold text-navy">
                      {a}
                    </th>
                    <td className="px-4 py-3">{b}</td>
                    <td className="px-4 py-3 text-muted-foreground">{c}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>
      <CtaBand />
    </>
  );
}

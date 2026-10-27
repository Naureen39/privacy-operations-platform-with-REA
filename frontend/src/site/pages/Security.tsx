import { Badge } from "@/components/ui/badge";
import { usePageMeta } from "@/lib/queries";
import { Link } from "react-router-dom";
import { CtaBand, Notice, PageHero } from "../sections/Common";

const implemented = [
  {
    title: "Tenant isolation",
    text: "Every table that holds organization data has row level security in PostgreSQL, forced even for the table owner. The application connects as a restricted role that cannot bypass it. Isolation is tested in the database and again through the API.",
  },
  {
    title: "Encryption at rest for evidence",
    text: "Uploaded evidence is encrypted with AES-256-GCM, with a fresh nonce per file and the evidence identifier bound as associated data, so a file moved to another record fails to decrypt.",
  },
  {
    title: "Role based access",
    text: "Four roles (admin, analyst, system owner, viewer). Every protected route declares its roles, a test fails if one does not, and a role matrix test checks every route for every role. A system owner sees only the systems they own.",
  },
  {
    title: "Sign in",
    text: "Argon2id password hashing, a 15 minute access token and a rotating refresh token in httpOnly cookies, lockout after five failures, and the same response for every failure. Presenting an already rotated refresh token revokes the whole token family.",
  },
  {
    title: "Audit logging",
    text: "Sign ins, approvals, exports, settings changes and request handling are written in the same transaction as the action. The log is append only for the application.",
  },
  {
    title: "Request forgery protection",
    text: "State changing requests must carry a token that matches a cookie. A token from another session is rejected. Cross origin requests are limited to an explicit allowlist.",
  },
  {
    title: "Uploads are data, never code",
    text: "Size limits, an allowlist of file types, content checks and rejection of executable formats. Files are only read as data and no code path executes them. Website observation is limited by an allowlist and a check that refuses internal addresses.",
  },
  {
    title: "Isolated analysis runners",
    text: "Evidence analysis runs in containers with no route to the internet, a read only file system, no capabilities, resource limits and a time limit.",
  },
  {
    title: "Rate limiting and headers",
    text: "Strict limits on sign in and a default limit on every route. Responses carry a content security policy, strict transport security and the usual hardening headers.",
  },
];

const planned = [
  "Dependency and container scanning in continuous integration (pip-audit, npm audit, Trivy)",
  "An external penetration test",
  "Single sign on and multi factor authentication",
  "Database encryption at rest at the storage layer (depends on where it is hosted)",
];

export default function Security() {
  usePageMeta(
    "Security",
    "The security practices that are implemented in ProcessLedger, and what is planned. No certifications are claimed.",
  );
  return (
    <>
      <PageHero
        eyebrow="Security"
        title="What is implemented, and nothing more"
        lead="This page lists practices that exist in the code and are covered by tests. ProcessLedger holds no security certification and none is claimed."
      />
      <section className="section">
        <div className="container">
          <ul className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
            {implemented.map((i) => (
              <li key={i.title} className="rounded-lg border border-border bg-card p-6 shadow-card">
                <Badge tone="green">Implemented</Badge>
                <h2 className="mt-3 text-xl">{i.title}</h2>
                <p className="mt-2 text-muted-foreground">{i.text}</p>
              </li>
            ))}
          </ul>
          <p className="mt-8 text-muted-foreground">
            The full model, including its known limitations, is in the{" "}
            <Link to="/resources/docs/security" className="font-semibold text-primary underline">
              security documentation
            </Link>
            .
          </p>
        </div>
      </section>
      <section className="section bg-surface">
        <div className="container">
          <h2 className="mb-5 text-2xl">Planned, not yet in place</h2>
          <ul className="space-y-3">
            {planned.map((p) => (
              <li key={p} className="flex items-start gap-3">
                <Badge tone="amber">Planned</Badge>
                <span className="text-muted-foreground">{p}</span>
              </li>
            ))}
          </ul>
          <div className="mt-8">
            <Notice>Do not enter real personal data. The demonstration environment is for sample data only.</Notice>
          </div>
        </div>
      </section>
      <CtaBand />
    </>
  );
}

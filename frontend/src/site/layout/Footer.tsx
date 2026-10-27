import { Link } from "react-router-dom";

import { LeadForm } from "@/components/LeadForm";
import { Logo } from "../art/Logo";
import { DEMO_NOTICE, footerColumns } from "../content/site";

export function Footer() {
  return (
    <footer className="bg-navy text-white">
      <div className="container py-14">
        <div className="grid gap-10 lg:grid-cols-[1.1fr_2.4fr]">
          <div>
            <Logo inverse />
            <p className="mt-4 max-w-sm text-sm text-white/80">
              Evidence based privacy operations: inventory, records of processing, impact assessments and access
              requests.
            </p>
            <div className="mt-6 max-w-sm rounded-lg bg-white p-4 text-foreground">
              <h2 className="mb-3 text-base font-semibold text-navy">Contact us</h2>
              <LeadForm
                kind="contact"
                compact
                idPrefix="footer"
                label="Quick message"
                submitLabel="Send message"
                messageLabel="How can we help?"
              />
            </div>
          </div>
          <nav aria-label="Footer" className="grid grid-cols-2 gap-8 sm:grid-cols-3 lg:grid-cols-5">
            {footerColumns.map((col) => (
              <div key={col.title}>
                <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-white">{col.title}</h2>
                <ul className="space-y-2">
                  {col.links.map((l) => (
                    <li key={l.label}>
                      <Link to={l.to} className="text-sm text-white/80 hover:text-white hover:underline">
                        {l.label}
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </nav>
        </div>
        <div className="mt-12 border-t border-white/15 pt-6 text-sm text-white/80">
          <p>{DEMO_NOTICE} Revenue and usage figures are simulated.</p>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs">
            <span>Region: demonstration, English (US)</span>
            <span>Draft for review by a qualified privacy professional. Not legal advice.</span>
          </div>
        </div>
      </div>
    </footer>
  );
}

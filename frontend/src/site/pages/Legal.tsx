import { useParams } from "react-router-dom";

import { usePageMeta } from "@/lib/queries";
import { DEMO_NOTICE, DRAFT_NOTICE } from "../content/site";
import { Notice, PageHero } from "../sections/Common";
import NotFound from "./NotFound";

const documents = {
  privacy: {
    title: "Privacy policy (sample)",
    sections: [
      [
        "What this is",
        "A template for a privacy policy, shown as an example of the kind of document this site would publish. It does not describe a live service.",
      ],
      [
        "Information we would collect",
        "On this demonstration site, the contact and demo forms store the name, email address, company and message that a visitor types. Nothing else is collected through the forms. Sign in uses cookies that are needed for the session.",
      ],
      [
        "How it would be used",
        "To answer a message and to show the lead list to the administrators of the demonstration environment.",
      ],
      ["Retention", "Messages would be kept only as long as needed to answer them."],
      ["Your rights", "A visitor can ask what is held about them, and ask for it to be corrected or removed."],
      ["Contact", "Use the contact form on this site."],
    ],
  },
  terms: {
    title: "Terms of use (sample)",
    sections: [
      ["What this is", "A template for terms of use, shown as an example. It is not a contract."],
      ["Demonstration only", "The service is a demonstration with sample data. Do not enter real personal data."],
      [
        "No warranty",
        "The service is provided as is. Generated records, assessments and letters are drafts for review by a qualified privacy professional.",
      ],
      [
        "Acceptable use",
        "Do not attempt to disrupt the service, to access another organization's data or to upload malicious files.",
      ],
      ["Changes", "These sample terms may change without notice."],
    ],
  },
} as const;

export default function Legal() {
  const { doc } = useParams();
  const item = doc === "privacy" || doc === "terms" ? documents[doc] : undefined;
  usePageMeta(item?.title ?? "Legal");
  if (!item) return <NotFound />;
  return (
    <>
      <PageHero eyebrow="Legal" title={item.title} />
      <section className="section">
        <div className="container max-w-3xl space-y-6">
          <Notice tone="warn">
            This is a sample document. {DEMO_NOTICE} {DRAFT_NOTICE}
          </Notice>
          {item.sections.map(([heading, text]) => (
            <div key={heading}>
              <h2 className="text-2xl">{heading}</h2>
              <p className="mt-2 text-lg text-muted-foreground">{text}</p>
            </div>
          ))}
        </div>
      </section>
    </>
  );
}

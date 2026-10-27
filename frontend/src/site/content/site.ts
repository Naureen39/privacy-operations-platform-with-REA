import { BarChart3, ClipboardCheck, FileText, Inbox, Radar, Server, type LucideIcon } from "lucide-react";

export const PRODUCT = "ProcessLedger";
export const TAGLINE = "Know where personal data lives. Prove it with evidence.";
export const DEMO_NOTICE =
  "ProcessLedger is a demonstration project. Every organization, person and figure shown is sample data.";
export const DRAFT_NOTICE = "Draft for review by a qualified privacy professional. Not legal advice.";

export interface NavLink {
  label: string;
  to: string;
  description?: string;
}

export interface NavGroup {
  label: string;
  to: string;
  intro: string;
  links: NavLink[];
}

export const industries = [
  {
    slug: "healthcare",
    name: "Healthcare",
    short: "Patient and staff data across clinical and administrative systems.",
    challenge:
      "Clinics and hospital groups run appointment, billing, imaging and staff systems that each hold personal data, often including health data that needs a stricter legal basis. Records of processing go stale as soon as a vendor or a form changes.",
    approach:
      "Each system is onboarded from evidence: the privacy notice, a questionnaire, a network capture and a database schema. Health data categories are flagged automatically, and an impact assessment is drafted for the processing that meets two or more screening criteria.",
    outcome:
      "In the reference estate, the clinic appointment portal collects health data. The comparison reports that no Article 9 condition is recorded for it, and screening marks the processing as likely to need an impact assessment. The draft cites the articles it relies on.",
    from: "#0F62FE",
    to: "#00A3A3",
  },
  {
    slug: "retail",
    name: "Retail and Commerce",
    short: "Customer, loyalty and marketing data in shops and online.",
    challenge:
      "Web shops add trackers, payment processors and email tools faster than the privacy notice is updated. The notice says one thing, the browser traffic shows another.",
    approach:
      "A recorded browsing session shows which third parties actually receive data. The comparison engine lines the notice, the questionnaire and the evidence up against each other and reports each contradiction with the evidence that supports it.",
    outcome:
      "In the reference estate, a vendor that receives identifiers in the captured traffic is not declared as a recipient and has no transfer safeguard on record. The finding names the vendor, the gap and the evidence.",
    from: "#0B1F3A",
    to: "#0F62FE",
  },
  {
    slug: "financial-services",
    name: "Financial Services",
    short: "Account, transaction and identity data with long retention periods.",
    challenge:
      "Retention rules, processors and cross-border transfers multiply across lending, onboarding and fraud systems. Auditors ask for evidence, not statements.",
    approach:
      "Every field in the record points back to its source: a database column, a captured request or a questionnaire answer. Versions are kept, approvals are logged and exports are produced for the audit file.",
    outcome:
      "The reference estate is a retailer with a clinic arm, not a bank, but the same check applies: a questionnaire states 12 months of retention while the helpdesk keeps tickets indefinitely. The finding shows both sources side by side.",
    from: "#162E52",
    to: "#00A3A3",
  },
  {
    slug: "public-sector",
    name: "Public Sector",
    short: "Citizen requests, case files and shared services.",
    challenge:
      "Public bodies receive requests from people who want to know what is held about them, with a fixed deadline and many systems to search.",
    approach:
      "An access request is checked for identity, searched across every system with hashed identifiers, and answered with a draft letter, a deadline tracker and reminders. Nothing leaves the case without an approval.",
    outcome:
      "In the reference estate, every location of a sample person's data is found across the seeded systems, and the response lists them with the retention period of each.",
    from: "#0F62FE",
    to: "#162E52",
  },
  {
    slug: "technology",
    name: "Technology",
    short: "Product analytics, support tools and many subprocessors.",
    challenge:
      "Software companies depend on dozens of subprocessors. Customers ask for a current list and for the safeguards behind every international transfer.",
    approach:
      "Vendors are collected from evidence across systems into one list, with the role, the country and the open gaps for each. New findings notify the owner of the system.",
    outcome:
      "In the reference estate, the vendor view shows one entry per vendor with every system that uses it and each open gap, such as a missing agreement or an undeclared recipient.",
    from: "#00A3A3",
    to: "#0B1F3A",
  },
] as const;

export type Industry = (typeof industries)[number];

export const capabilities: { title: string; text: string; icon: LucideIcon; to: string }[] = [
  {
    title: "System Inventory",
    text: "One register of the systems that process personal data, with owners, evidence and status.",
    icon: Server,
    to: "/platform#inventory",
  },
  {
    title: "Technical Discovery",
    text: "Evidence extracted from network captures, database schemas and scripts, not from memory.",
    icon: Radar,
    to: "/platform#discovery",
  },
  {
    title: "Records of Processing",
    text: "Article 30 records generated from evidence, versioned, reviewed and exportable.",
    icon: FileText,
    to: "/platform#records",
  },
  {
    title: "Impact Assessments",
    text: "Screening against the guidance criteria and a drafted assessment with a cited risk register.",
    icon: ClipboardCheck,
    to: "/platform#assessments",
  },
  {
    title: "Access Requests",
    text: "Intake, identity checks, search across systems, deadline tracking and a drafted response.",
    icon: Inbox,
    to: "/platform#requests",
  },
  {
    title: "Compliance Analytics",
    text: "Approved and stale records, open findings, assessments and requests, by day, week or month.",
    icon: BarChart3,
    to: "/platform#analytics",
  },
];

export const steps = [
  { title: "Collect evidence", text: "Upload a notice, a questionnaire, a network capture or a database schema." },
  {
    title: "Extract and classify",
    text: "Data elements, recipients and trackers are extracted and mapped to a personal data taxonomy.",
  },
  {
    title: "Compare and decide",
    text: "Sources are compared. Each contradiction becomes a finding with its evidence.",
  },
  { title: "Review and prove", text: "A person approves the record. Every version, approval and export is logged." },
];

export const faqs = [
  {
    q: "Is this a finished commercial product?",
    a: "No. ProcessLedger is a demonstration project built to show an evidence based approach to privacy operations. The organizations, people and figures are sample data, and revenue figures are simulated.",
  },
  {
    q: "Does it give legal advice?",
    a: "No. Generated records, assessments and response letters are drafts for review by a qualified privacy professional. Each one carries that notice.",
  },
  {
    q: "What does it need as input?",
    a: "A privacy notice, a questionnaire answered by the system owner, and technical evidence: a network capture (HAR), a database schema (SQLite) or scripts. More evidence gives stronger findings.",
  },
  {
    q: "Which regulation does it support?",
    a: "The General Data Protection Regulation: records of processing (Article 30), impact assessments (Article 35) and access requests (Article 15). Other regimes are on the roadmap and are labeled as planned.",
  },
  {
    q: "Where does the language model fit in?",
    a: "Deterministic rules do the extraction and comparison. A model is used only where judgment is needed, such as drafting text, within a token budget, and every statement is tied to evidence or an article.",
  },
  {
    q: "Is my data safe in the demonstration?",
    a: "Do not enter real personal data. The demonstration environment is for sample data only.",
  },
];

export const cases = [
  {
    title: "Clinic appointment portal",
    industry: "Healthcare",
    figure: "Assessment drafted",
    text: "A portal that collects health data is screened as likely to need an impact assessment, and a draft with a cited risk register is produced.",
  },
  {
    title: "Undeclared recipient",
    industry: "Retail and Commerce",
    figure: "Gap found",
    text: "Captured traffic shows identifiers going to a vendor the records never declare. The finding names the vendor and the missing safeguard.",
  },
  {
    title: "Subject access request",
    industry: "Public Sector",
    figure: "Every location found",
    text: "A sample person is found in all of the seeded systems, and the response lists each location with its retention period.",
  },
];

export const navGroups: NavGroup[] = [
  {
    label: "Platform",
    to: "/platform",
    intro: "From evidence to an approved record.",
    links: [
      { label: "How it works", to: "/platform", description: "The pipeline in depth" },
      { label: "Records of processing", to: "/platform#records", description: "Article 30, generated and versioned" },
      { label: "Impact assessments", to: "/platform#assessments", description: "Screening and a cited draft" },
      { label: "Access requests", to: "/platform#requests", description: "Search, deadlines and a response" },
    ],
  },
  {
    label: "Solutions",
    to: "/solutions",
    intro: "Scenarios from the reference estate.",
    links: industries.map((i) => ({ label: i.name, to: `/solutions/${i.slug}`, description: i.short })),
  },
  {
    label: "Regulations",
    to: "/regulations",
    intro: "What is supported and what is planned.",
    links: [
      { label: "Article 30", to: "/regulations#article-30", description: "Records of processing" },
      { label: "Article 35", to: "/regulations#article-35", description: "Impact assessments" },
      { label: "Article 15", to: "/regulations#article-15", description: "Right of access" },
    ],
  },
  {
    label: "Pricing",
    to: "/pricing",
    intro: "Three illustrative plans and a cost calculator.",
    links: [
      { label: "Plans", to: "/pricing", description: "Starter, Professional, Enterprise" },
      { label: "Cost calculator", to: "/pricing#calculator", description: "Systems and requests to a monthly cost" },
    ],
  },
  {
    label: "Resources",
    to: "/resources",
    intro: "Documentation and technical writing.",
    links: [
      { label: "Documentation", to: "/resources#documentation", description: "Architecture, database, security" },
      { label: "Technical articles", to: "/resources#articles", description: "Three articles from the project" },
      { label: "API reference", to: "/resources#api", description: "Interactive OpenAPI documentation" },
      { label: "Security", to: "/security", description: "Practices that are implemented" },
    ],
  },
  {
    label: "Company",
    to: "/company",
    intro: "About the project and how to reach us.",
    links: [
      { label: "About", to: "/company", description: "Why this exists" },
      { label: "Contact", to: "/contact", description: "Send a message" },
      { label: "Request a demo", to: "/contact?tab=demo", description: "See the seeded environment" },
    ],
  },
];

export const footerColumns: { title: string; links: NavLink[] }[] = [
  {
    title: "Platform",
    links: [
      { label: "How it works", to: "/platform" },
      { label: "Records of processing", to: "/platform#records" },
      { label: "Impact assessments", to: "/platform#assessments" },
      { label: "Access requests", to: "/platform#requests" },
    ],
  },
  {
    title: "Solutions",
    links: industries.map((i) => ({ label: i.name, to: `/solutions/${i.slug}` })),
  },
  {
    title: "Resources",
    links: [
      { label: "Documentation", to: "/resources#documentation" },
      { label: "Technical articles", to: "/resources#articles" },
      { label: "Security", to: "/security" },
      { label: "Status", to: "/status" },
    ],
  },
  {
    title: "Company",
    links: [
      { label: "About", to: "/company" },
      { label: "Contact", to: "/contact" },
      { label: "Request a demo", to: "/contact?tab=demo" },
      { label: "Pricing", to: "/pricing" },
    ],
  },
  {
    title: "Legal",
    links: [
      { label: "Privacy policy (sample)", to: "/legal/privacy" },
      { label: "Terms of use (sample)", to: "/legal/terms" },
      { label: "Sign in", to: "/login" },
    ],
  },
];

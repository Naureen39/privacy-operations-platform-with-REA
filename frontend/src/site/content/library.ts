/** Markdown that ships with the site: the project documentation (read from /docs at build time) and
 *  the three technical articles. Each is loaded on demand so the pages stay small. */

type Loader = () => Promise<string>;

const docFiles = import.meta.glob("../../../../docs/*.md", { query: "?raw", import: "default" }) as Record<
  string,
  Loader
>;
const articleFiles = import.meta.glob("./articles/*.md", { query: "?raw", import: "default" }) as Record<
  string,
  Loader
>;

export interface LibraryItem {
  slug: string;
  title: string;
  summary: string;
  load: Loader;
}

const docMeta: Record<string, { title: string; summary: string }> = {
  architecture: {
    title: "Architecture",
    summary: "Pipeline, data model, measured results and limits for every phase.",
  },
  database: { title: "Database", summary: "Tables, migrations, row level security and the application role." },
  security: { title: "Security model", summary: "Authentication, authorization, CSRF, uploads and runner isolation." },
};

const articleMeta: Record<string, { title: string; summary: string }> = {
  "evidence-based-records": {
    title: "Evidence based record generation",
    summary: "Why a record of processing should be generated from evidence, and how contradictions are found.",
  },
  "token-efficient-classification": {
    title: "Token efficient classification",
    summary: "Rules, embeddings and a review queue: how onboarding a system fits inside a free tier budget.",
  },
  "access-request-search": {
    title: "Searching for a person without exposing them",
    summary: "Hashed identifiers, a data map and a deadline for subject access requests.",
  },
};

function slugOf(path: string): string {
  return path.slice(path.lastIndexOf("/") + 1).replace(/\.md$/, "");
}

export const docs: LibraryItem[] = Object.entries(docFiles)
  .map(([path, load]) => {
    const slug = slugOf(path);
    const meta = docMeta[slug];
    return meta ? { slug, ...meta, load } : null;
  })
  .filter((d): d is LibraryItem => d !== null)
  .sort((a, b) => a.title.localeCompare(b.title));

export const articles: LibraryItem[] = Object.entries(articleFiles)
  .map(([path, load]) => {
    const slug = slugOf(path);
    const meta = articleMeta[slug];
    return meta ? { slug, ...meta, load } : null;
  })
  .filter((a): a is LibraryItem => a !== null)
  .sort((a, b) => a.title.localeCompare(b.title));

import { lazy, Suspense, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { usePageMeta } from "@/lib/queries";
import { articles, docs, type LibraryItem } from "../content/library";
import { CtaBand, PageHero, SectionHeading } from "../sections/Common";
import NotFound from "./NotFound";

const Markdown = lazy(() => import("../sections/MarkdownView"));

function ItemGrid({ items, base }: { items: LibraryItem[]; base: string }) {
  return (
    <ul className="grid gap-6 md:grid-cols-3">
      {items.map((item) => (
        <li key={item.slug}>
          <Card className="h-full transition-shadow hover:shadow-pop">
            <CardContent>
              <h3 className="text-xl">
                <Link to={`${base}/${item.slug}`} className="hover:text-primary hover:underline">
                  {item.title}
                </Link>
              </h3>
              <p className="mt-2 text-muted-foreground">{item.summary}</p>
            </CardContent>
          </Card>
        </li>
      ))}
    </ul>
  );
}

export function ResourcesIndex() {
  usePageMeta("Resources", "Project documentation, technical articles and the API reference for ProcessLedger.");
  return (
    <>
      <PageHero
        eyebrow="Resources"
        title="Documentation and technical writing"
        lead="Everything here is written from the project itself, with measured results and their limits."
      />
      <section id="documentation" className="section scroll-mt-24">
        <div className="container">
          <SectionHeading title="Documentation" />
          <ItemGrid items={docs} base="/resources/docs" />
        </div>
      </section>
      <section id="articles" className="section scroll-mt-24 bg-surface">
        <div className="container">
          <SectionHeading title="Technical articles" />
          <ItemGrid items={articles} base="/resources/articles" />
        </div>
      </section>
      <section id="api" className="section scroll-mt-24">
        <div className="container">
          <SectionHeading
            title="API reference"
            lead="The interactive OpenAPI documentation is served by the API itself and lists every route with its request examples."
          />
          <Button asChild variant="secondary">
            <a href="/docs">Open the API reference</a>
          </Button>
          <p className="mt-3 text-sm text-muted-foreground">Available when the API is running.</p>
        </div>
      </section>
      <CtaBand />
    </>
  );
}

export function LibraryPage({ kind }: { kind: "docs" | "articles" }) {
  const { slug } = useParams();
  const items = kind === "docs" ? docs : articles;
  const item = items.find((i) => i.slug === slug);
  const [loaded, setLoaded] = useState<{ slug: string; text: string | null } | null>(null);
  usePageMeta(item?.title ?? "Resources", item?.summary);
  useEffect(() => {
    if (!item) return;
    let cancelled = false;
    item
      .load()
      .then((text) => !cancelled && setLoaded({ slug: item.slug, text }))
      .catch(() => !cancelled && setLoaded({ slug: item.slug, text: null }));
    return () => {
      cancelled = true;
    };
  }, [item]);
  const current = loaded && loaded.slug === item?.slug ? loaded : null;
  const text = current?.text ?? null;
  const failed = current !== null && current.text === null;
  if (!item) return <NotFound />;
  return (
    <section className="section">
      <div className="container grid grid-cols-1 gap-10 lg:grid-cols-[240px_1fr]">
        <aside className="lg:sticky lg:top-28 lg:self-start">
          <p className="eyebrow">{kind === "docs" ? "Documentation" : "Article"}</p>
          <nav aria-label={kind === "docs" ? "Documentation" : "Articles"}>
            <ul className="space-y-1">
              {items.map((i) => (
                <li key={i.slug}>
                  <Link
                    to={`/resources/${kind}/${i.slug}`}
                    aria-current={i.slug === slug ? "page" : undefined}
                    className={`block rounded-md px-3 py-2 text-sm ${i.slug === slug ? "bg-primary/10 font-semibold text-primary-hover" : "text-navy hover:bg-muted"}`}
                  >
                    {i.title}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
          <Button asChild variant="link" className="mt-4 px-0">
            <Link to="/resources">All resources</Link>
          </Button>
        </aside>
        <article className="min-w-0">
          {failed && <p role="alert">This document could not be loaded.</p>}
          {text === null && !failed && (
            <p aria-busy="true" className="text-muted-foreground">
              Loading...
            </p>
          )}
          {text !== null && (
            <Suspense fallback={<p aria-busy="true">Loading...</p>}>
              <Markdown text={text} />
            </Suspense>
          )}
        </article>
      </div>
    </section>
  );
}

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import { usePageMeta } from "@/lib/queries";
import { useAction, useSystems } from "../hooks/data";
import { PageHeader, Panel, Select } from "../ui/parts";
import type { ChatAnswer, Passage } from "../types";

function PassageCard({ p }: { p: Passage }) {
  return (
    <li className="rounded-lg border border-border p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-base">{p.citation}</h3>
        <span className="text-xs text-muted-foreground">{p.source === "regulation" ? "GDPR" : "Your document"}</span>
      </div>
      <p className="mt-1 text-xs text-muted-foreground">{p.label}</p>
      <p className="mt-2 whitespace-pre-wrap text-sm">{p.text}</p>
    </li>
  );
}

function Search() {
  const [query, setQuery] = useState("");
  const [passages, setPassages] = useState<Passage[] | null>(null);
  const search = useAction({
    run: () =>
      api.post<{ passages: Passage[] }>("/api/v1/knowledge/search", {
        query,
        top_k: 8,
        sources: ["regulation", "document"],
      }),
    onDone: (r) => setPassages(r.passages),
  });
  return (
    <div className="space-y-4">
      <form
        className="flex max-w-2xl gap-2"
        role="search"
        aria-label="Search the regulation"
        onSubmit={(e) => {
          e.preventDefault();
          if (query.trim().length >= 3) search.mutate(undefined);
        }}
      >
        <div className="flex-1">
          <Label htmlFor="lib-q" className="sr-only">
            Search the regulation and your documents
          </Label>
          <Input
            id="lib-q"
            placeholder="For example: records of processing, Article 30"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <Button type="submit" disabled={search.isPending || query.trim().length < 3}>
          Search
        </Button>
      </form>
      {passages !== null &&
        (passages.length === 0 ? (
          <p className="text-muted-foreground">No passages matched.</p>
        ) : (
          <ul className="space-y-3">
            {passages.map((p) => (
              <PassageCard key={p.id} p={p} />
            ))}
          </ul>
        ))}
    </div>
  );
}

function Ask() {
  const systems = useSystems();
  const [question, setQuestion] = useState("");
  const [system, setSystem] = useState("");
  const [answer, setAnswer] = useState<ChatAnswer | null>(null);
  const ask = useAction({
    run: () => api.post<ChatAnswer>("/api/v1/chat", { question, system_id: system || null }),
    onDone: setAnswer,
  });
  return (
    <div className="space-y-4">
      <form
        className="max-w-2xl space-y-3"
        aria-label="Ask a question"
        onSubmit={(e) => {
          e.preventDefault();
          if (question.trim().length >= 5) ask.mutate(undefined);
        }}
      >
        <div className="space-y-1.5">
          <Label htmlFor="ask-q">Your question</Label>
          <Input
            id="ask-q"
            placeholder="What must a record of processing contain?"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
          />
        </div>
        <Select
          id="ask-system"
          label="About"
          value={system}
          onChange={setSystem}
          options={[
            { value: "", label: "The regulation and all documents" },
            ...(systems.data ?? []).map((s) => ({ value: s.id, label: s.name })),
          ]}
        />
        <Button type="submit" disabled={ask.isPending || question.trim().length < 5}>
          {ask.isPending ? "Looking it up..." : "Ask"}
        </Button>
      </form>
      {answer && (
        <div className="space-y-3" aria-live="polite">
          <Panel title="Answer">
            <p className="whitespace-pre-wrap">{answer.answer}</p>
            {!answer.supported && (
              <p className="mt-2 text-sm text-muted-foreground">
                No supporting evidence was found, so no model was asked.
              </p>
            )}
            <p className="mt-2 text-xs text-muted-foreground">
              Draft for review by a qualified privacy professional. Not legal advice.
            </p>
          </Panel>
          {answer.citations.length > 0 && (
            <div>
              <h3 className="mb-2 text-base">Sources ({answer.citations.length})</h3>
              <ul className="space-y-3">
                {answer.citations.map((p) => (
                  <PassageCard key={p.id} p={p} />
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function Library() {
  usePageMeta("Regulation library");
  return (
    <>
      <PageHeader
        title="Regulation library"
        description="Search the GDPR and your own documents, or ask a question that is answered only from them, with the sources shown."
      />
      <Tabs defaultValue="search">
        <TabsList aria-label="Library" className="mb-5">
          <TabsTrigger value="search">Search</TabsTrigger>
          <TabsTrigger value="ask">Ask</TabsTrigger>
        </TabsList>
        <TabsContent value="search">
          <Search />
        </TabsContent>
        <TabsContent value="ask">
          <Ask />
        </TabsContent>
      </Tabs>
    </>
  );
}

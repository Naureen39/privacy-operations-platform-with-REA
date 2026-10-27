import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ProductMock, type MockView } from "../art/ProductMock";

const tour: { value: MockView; label: string; text: string }[] = [
  {
    value: "dashboard",
    label: "Overview",
    text: "Approved records, open findings and requests at a glance, by day, week or month.",
  },
  {
    value: "findings",
    label: "Findings",
    text: "Each contradiction between sources, with severity, system and the evidence behind it.",
  },
  { value: "record", label: "Record", text: "A record of processing with versions, an approval trail and exports." },
  {
    value: "assessment",
    label: "Assessment",
    text: "A screened and drafted impact assessment with a cited risk register.",
  },
  {
    value: "request",
    label: "Request",
    text: "A subject access request with its deadline, identity check and search results.",
  },
];

export default function ProductTour() {
  return (
    <Tabs defaultValue="dashboard" className="grid gap-8 lg:grid-cols-[1fr_1.3fr] lg:items-center">
      <div>
        <p className="mb-4 text-sm text-muted-foreground">Choose a screen:</p>
        <TabsList aria-label="Product tour" className="mb-6">
          {tour.map((t) => (
            <TabsTrigger key={t.value} value={t.value}>
              {t.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </div>
      <div>
        {tour.map((t) => (
          <TabsContent key={t.value} value={t.value} className="space-y-4">
            <p className="lead">{t.text}</p>
            <ProductMock view={t.value} />
          </TabsContent>
        ))}
      </div>
    </Tabs>
  );
}

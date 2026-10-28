import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { useAction } from "../../hooks/data";
import type { Activity } from "../../types";

export function RecordEdit({ record, onDone }: { record: Activity; onDone: () => void }) {
  const [purposes, setPurposes] = useState(record.purposes.join("\n"));
  const [basis, setBasis] = useState(record.lawful_basis ?? "");
  const [retention, setRetention] = useState(record.retention ?? "");
  const [security, setSecurity] = useState(record.security_measures ?? "");
  const [condition, setCondition] = useState(record.special_category_condition ?? "");
  const [review, setReview] = useState(record.next_review_date ?? "");
  const patch = useAction({
    run: () =>
      api.patch<Activity>(`/api/v1/activities/${record.id}`, {
        purposes: purposes
          .split("\n")
          .map((p) => p.trim())
          .filter(Boolean),
        lawful_basis: basis || null,
        retention: retention || null,
        security_measures: security || null,
        special_category_condition: condition || null,
        next_review_date: review || null,
      }),
    success: "Saved as a new version",
    invalidate: [["activity", record.id], ["activities"], ["versions", record.id]],
    onDone,
  });
  return (
    <form
      className="space-y-4"
      aria-label="Edit the record"
      onSubmit={(e) => {
        e.preventDefault();
        patch.mutate(undefined);
      }}
    >
      <div className="space-y-1.5">
        <Label htmlFor="rec-purposes">Purposes (one per line)</Label>
        <Textarea id="rec-purposes" value={purposes} onChange={(e) => setPurposes(e.target.value)} />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="rec-basis">Lawful basis</Label>
          <Input id="rec-basis" value={basis} onChange={(e) => setBasis(e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="rec-review">Next review</Label>
          <Input id="rec-review" type="date" value={review} onChange={(e) => setReview(e.target.value)} />
        </div>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="rec-cond">Article 9 condition</Label>
        <Input id="rec-cond" value={condition} onChange={(e) => setCondition(e.target.value)} />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="rec-ret">Retention</Label>
        <Textarea id="rec-ret" className="min-h-20" value={retention} onChange={(e) => setRetention(e.target.value)} />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="rec-sec">Security measures</Label>
        <Textarea id="rec-sec" className="min-h-20" value={security} onChange={(e) => setSecurity(e.target.value)} />
      </div>
      <div className="flex gap-2">
        <Button type="submit" disabled={patch.isPending}>
          Save
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

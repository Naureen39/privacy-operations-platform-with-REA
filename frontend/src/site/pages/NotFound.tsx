import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { usePageMeta } from "@/lib/queries";

export default function NotFound() {
  usePageMeta("Page not found");
  return (
    <section className="container py-24 text-center">
      <p className="eyebrow">Error 404</p>
      <h1 className="text-4xl">This page does not exist</h1>
      <p className="lead mx-auto mt-4 max-w-xl">The address may have changed, or it may have been typed incorrectly.</p>
      <Button asChild className="mt-8">
        <Link to="/">Back to the home page</Link>
      </Button>
    </section>
  );
}

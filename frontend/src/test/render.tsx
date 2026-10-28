import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import axe from "axe-core";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

export function renderAt(ui: ReactElement, path = "/", pattern = "*") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path={pattern} element={ui} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** Structural accessibility rules from axe-core. Colour contrast needs a real browser, so it is checked
 *  in the end to end run instead. */
export async function a11yViolations(container: HTMLElement): Promise<string[]> {
  const result = await axe.run(container, {
    rules: { "color-contrast": { enabled: false }, region: { enabled: false } },
  });
  return result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
}

/** A fetch that answers by path. Anything not listed is a network failure. */
export function mockFetch(routes: Record<string, { status?: number; body?: unknown }>) {
  const fn = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const hit = routes[url] ?? routes[url.split("?")[0] ?? url];
    if (!hit) throw new TypeError("network down");
    return new Response(hit.status === 204 ? null : JSON.stringify(hit.body ?? {}), {
      status: hit.status ?? 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

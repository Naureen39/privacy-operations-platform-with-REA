import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router-dom";

import { SiteLayout } from "./site/layout/SiteLayout";
import Home from "./site/pages/Home";

// Every page except the home page is its own chunk.
const Platform = lazy(() => import("./site/pages/Platform"));
const Regulations = lazy(() => import("./site/pages/Regulations"));
const Pricing = lazy(() => import("./site/pages/Pricing"));
const Security = lazy(() => import("./site/pages/Security"));
const Legal = lazy(() => import("./site/pages/Legal"));
const Status = lazy(() => import("./site/pages/Status"));
const Login = lazy(() => import("./site/pages/Login"));
const NotFound = lazy(() => import("./site/pages/NotFound"));
const Console = lazy(() => import("./app/ConsolePlaceholder"));
const SolutionsIndex = lazy(() => import("./site/pages/Solutions").then((m) => ({ default: m.SolutionsIndex })));
const IndustryPage = lazy(() => import("./site/pages/Solutions").then((m) => ({ default: m.IndustryPage })));
const ResourcesIndex = lazy(() => import("./site/pages/Resources").then((m) => ({ default: m.ResourcesIndex })));
const Docs = lazy(() =>
  import("./site/pages/Resources").then((m) => ({ default: () => <m.LibraryPage kind="docs" /> })),
);
const Articles = lazy(() =>
  import("./site/pages/Resources").then((m) => ({ default: () => <m.LibraryPage kind="articles" /> })),
);
const Company = lazy(() => import("./site/pages/Company").then((m) => ({ default: m.Company })));
const Contact = lazy(() => import("./site/pages/Company").then((m) => ({ default: m.Contact })));

function Loading() {
  return <div className="min-h-[60vh]" role="status" aria-label="Loading" aria-busy="true" />;
}

export default function App() {
  return (
    <Suspense fallback={<Loading />}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/app/*" element={<Console />} />
        <Route element={<SiteLayout />}>
          <Route index element={<Home />} />
          <Route path="platform" element={<Platform />} />
          <Route path="solutions" element={<SolutionsIndex />} />
          <Route path="solutions/:slug" element={<IndustryPage />} />
          <Route path="regulations" element={<Regulations />} />
          <Route path="pricing" element={<Pricing />} />
          <Route path="security" element={<Security />} />
          <Route path="resources" element={<ResourcesIndex />} />
          <Route path="resources/docs/:slug" element={<Docs />} />
          <Route path="resources/articles/:slug" element={<Articles />} />
          <Route path="company" element={<Company />} />
          <Route path="contact" element={<Contact />} />
          <Route path="legal/:doc" element={<Legal />} />
          <Route path="status" element={<Status />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </Suspense>
  );
}

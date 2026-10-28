import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router-dom";

import { RequireRole } from "./app/session";
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
const ConsoleShell = lazy(() => import("./app/ConsoleShell"));
const Overview = lazy(() => import("./app/pages/Overview"));
const Systems = lazy(() => import("./app/pages/Systems"));
const SystemDetail = lazy(() => import("./app/pages/SystemDetail"));
const AddSystem = lazy(() => import("./app/pages/AddSystem"));
const RecordsList = lazy(() => import("./app/pages/Records").then((m) => ({ default: m.RecordsList })));
const RecordDetail = lazy(() => import("./app/pages/Records").then((m) => ({ default: m.RecordDetail })));
const AssessmentsList = lazy(() => import("./app/pages/Assessments").then((m) => ({ default: m.AssessmentsList })));
const AssessmentEditor = lazy(() => import("./app/pages/Assessments").then((m) => ({ default: m.AssessmentEditor })));
const Findings = lazy(() => import("./app/pages/Findings"));
const RequestsList = lazy(() => import("./app/pages/Requests").then((m) => ({ default: m.RequestsList })));
const RequestDetail = lazy(() => import("./app/pages/Requests").then((m) => ({ default: m.RequestDetail })));
const Vendors = lazy(() => import("./app/pages/Vendors"));
const Library = lazy(() => import("./app/pages/Library"));
const Analytics = lazy(() => import("./app/pages/Analytics"));
const Revenue = lazy(() => import("./app/pages/Revenue"));
const Billing = lazy(() => import("./app/pages/Admin").then((m) => ({ default: m.Billing })));
const Team = lazy(() => import("./app/pages/Admin").then((m) => ({ default: m.Team })));
const AuditLog = lazy(() => import("./app/pages/Admin").then((m) => ({ default: m.AuditLog })));
const Settings = lazy(() => import("./app/pages/Admin").then((m) => ({ default: m.Settings })));
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
        <Route path="/app" element={<ConsoleShell />}>
          <Route index element={<Overview />} />
          <Route path="systems" element={<Systems />} />
          <Route
            path="systems/new"
            element={
              <RequireRole roles={["admin", "analyst"]}>
                <AddSystem />
              </RequireRole>
            }
          />
          <Route path="systems/:id" element={<SystemDetail />} />
          <Route path="findings" element={<Findings />} />
          <Route path="records" element={<RecordsList />} />
          <Route path="records/:id" element={<RecordDetail />} />
          <Route
            path="assessments"
            element={
              <RequireRole roles={["admin", "analyst", "viewer"]}>
                <AssessmentsList />
              </RequireRole>
            }
          />
          <Route
            path="assessments/:id"
            element={
              <RequireRole roles={["admin", "analyst", "viewer"]}>
                <AssessmentEditor />
              </RequireRole>
            }
          />
          <Route
            path="requests"
            element={
              <RequireRole roles={["admin", "analyst", "viewer"]}>
                <RequestsList />
              </RequireRole>
            }
          />
          <Route
            path="requests/:id"
            element={
              <RequireRole roles={["admin", "analyst", "viewer"]}>
                <RequestDetail />
              </RequireRole>
            }
          />
          <Route path="vendors" element={<Vendors />} />
          <Route path="library" element={<Library />} />
          <Route
            path="analytics"
            element={
              <RequireRole roles={["admin", "analyst", "viewer"]}>
                <Analytics />
              </RequireRole>
            }
          />
          <Route
            path="revenue"
            element={
              <RequireRole roles={["admin"]} host>
                <Revenue />
              </RequireRole>
            }
          />
          <Route
            path="billing"
            element={
              <RequireRole roles={["admin"]}>
                <Billing />
              </RequireRole>
            }
          />
          <Route
            path="team"
            element={
              <RequireRole roles={["admin"]}>
                <Team />
              </RequireRole>
            }
          />
          <Route
            path="audit"
            element={
              <RequireRole roles={["admin", "viewer"]}>
                <AuditLog />
              </RequireRole>
            }
          />
          <Route
            path="settings"
            element={
              <RequireRole roles={["admin"]}>
                <Settings />
              </RequireRole>
            }
          />
          <Route path="*" element={<NotFound />} />
        </Route>
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

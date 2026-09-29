import { lazy, Suspense, useEffect, useState } from "react";
import { Navigate, Route, Routes, useParams } from "react-router-dom";
import NavBar from "./components/NavBar.jsx";
import ErrorBoundary from "./components/ErrorBoundary.jsx";
import Sidebar from "./components/Sidebar.jsx";
import ChatPanel from "./components/ChatPanel.jsx";
const BillingPage = lazy(() => import("./views/BillingPage.jsx"));
const ModellingDashboard = lazy(() => import("./views/ModellingDashboard.jsx"));
const ModellingHome = lazy(() => import("./views/ModellingHome.jsx"));
const AllModelsPage = lazy(() => import("./views/AllModelsPage.jsx"));
const NewModelPage = lazy(() => import("./views/NewModelPage.jsx"));
const ModelPage = lazy(() => import("./views/ModelPage.jsx"));
const DegradationHome = lazy(() => import("./views/DegradationHome.jsx"));
const DegradationModelPage = lazy(() => import("./views/DegradationModelPage.jsx"));
const RecurrentHome = lazy(() => import("./views/RecurrentHome.jsx"));
const RecurrentNewPage = lazy(() => import("./views/RecurrentNewPage.jsx"));
const RecurrentModelPage = lazy(() => import("./views/RecurrentModelPage.jsx"));
const AltHome = lazy(() => import("./views/AltHome.jsx"));
const AltNewPage = lazy(() => import("./views/AltNewPage.jsx"));
const AltModelPage = lazy(() => import("./views/AltModelPage.jsx"));
const RbdDashboard = lazy(() => import("./views/RbdDashboard.jsx"));
const RbdHome = lazy(() => import("./views/RbdHome.jsx"));
const RbdBuilder = lazy(() => import("./views/RbdBuilder.jsx"));
const DatasetsDashboard = lazy(() => import("./views/DatasetsDashboard.jsx"));
const DatasetsHome = lazy(() => import("./views/DatasetsHome.jsx"));
const DatasetPage = lazy(() => import("./views/DatasetPage.jsx"));
const StrategyDashboard = lazy(() => import("./views/StrategyDashboard.jsx"));
const StrategyReplacement = lazy(() => import("./views/StrategyReplacement.jsx"));
const StrategyCompare = lazy(() => import("./views/StrategyCompare.jsx"));
const StrategyFailureFinding = lazy(() => import("./views/StrategyFailureFinding.jsx"));
const StrategyAnalyses = lazy(() => import("./views/StrategyAnalyses.jsx"));
const StrategyTracking = lazy(() => import("./views/StrategyTracking.jsx"));
const FleetDashboard = lazy(() => import("./views/FleetDashboard.jsx"));
const FleetForecasts = lazy(() => import("./views/FleetForecasts.jsx"));
const FleetTrackingHome = lazy(() => import("./views/FleetTrackingHome.jsx"));
const FleetForecastPage = lazy(() => import("./views/FleetForecastPage.jsx"));
const StrategyAnalysisPage = lazy(() => import("./views/StrategyAnalysisPage.jsx"));
const RcmDashboard = lazy(() => import("./views/RcmDashboard.jsx"));
const RcmHome = lazy(() => import("./views/RcmHome.jsx"));
const RcmStudyPage = lazy(() => import("./views/RcmStudyPage.jsx"));
const TeamSettingsPage = lazy(() => import("./views/TeamSettingsPage.jsx"));
const SettingsPage = lazy(() => import("./views/SettingsPage.jsx"));
const ApiDocsPage = lazy(() => import("./views/ApiDocsPage.jsx"));
const ReliabilityAgent = lazy(() => import("./views/ReliabilityAgent.jsx"));
const AdminPage = lazy(() => import("./views/AdminPage.jsx"));
import { useAppConfig } from "./ConfigProvider.jsx";
import { useWorkspace } from "./WorkspaceProvider.jsx";

// The authenticated app shell. This module is code-split: App.jsx
// lazy-imports it, so the public/marketing pages ship without the app bundle.
// Each view is lazy too, so opening the app downloads only the shell and the
// page being viewed — the chart library (Plotly) and the diagram canvas (React
// Flow) arrive with the pages that use them. The chart module is prefetched
// once the browser is idle so the first chart page doesn't wait for it.

// Old bookmarks carried MODEL ids; fleets are their own ids now, so the
// safest landing is the tracking index.
function TrackingRedirect() {
  useParams();
  return <Navigate to="/fleet/tracking" replace />;
}

export default function AppShell() {
  const [collapsed, setCollapsed] = useState(false);
  // Deployment capabilities: hide the assistant and billing entirely when this
  // deployment can't offer them (e.g. an open-source self-hosted instance).
  const { ai, billing, reliability_agent: agentEnabled } = useAppConfig();
  // Keying the routed content on the workspace remounts every view on switch,
  // so all lists refetch under the new X-Workspace-Id without any per-view code.
  const { workspace } = useWorkspace();
  useEffect(() => {
    const prefetch = () => import("./components/Plot.jsx").catch(() => {});
    if ("requestIdleCallback" in window) {
      const id = window.requestIdleCallback(prefetch, { timeout: 4000 });
      return () => window.cancelIdleCallback(id);
    }
    const id = window.setTimeout(prefetch, 2000);
    return () => window.clearTimeout(id);
  }, []);
  return (
    <>
      <NavBar />
      <div className="layout">
        <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)} />
        <main className="content" key={workspace}>
          <ErrorBoundary>
          <Suspense fallback={<div className="card empty view-loading">Loading…</div>}>
          <Routes>
            <Route path="/" element={<Navigate to="/modelling" replace />} />
            <Route path="/modelling" element={<ModellingDashboard />} />
            <Route path="/modelling/models" element={<AllModelsPage />} />
            <Route path="/modelling/life" element={<ModellingHome />} />
            <Route path="/modelling/new" element={<NewModelPage />} />
            <Route path="/modelling/degradation" element={<DegradationHome />} />
            <Route path="/modelling/degradation/:id" element={<DegradationModelPage />} />
            <Route path="/modelling/recurrent" element={<RecurrentHome />} />
            <Route path="/modelling/recurrent/new" element={<RecurrentNewPage />} />
            <Route path="/modelling/recurrent/:id" element={<RecurrentModelPage />} />
            <Route path="/modelling/alt" element={<AltHome />} />
            <Route path="/modelling/alt/new" element={<AltNewPage />} />
            <Route path="/modelling/alt/:id" element={<AltModelPage />} />
            <Route path="/modelling/m/:id" element={<ModelPage />} />
            <Route path="/rbds" element={<RbdDashboard />} />
            <Route path="/rbds/list" element={<RbdHome />} />
            <Route path="/rbds/b" element={<RbdBuilder />} />
            <Route path="/rbds/b/:id" element={<RbdBuilder />} />
            <Route path="/datasets" element={<DatasetsDashboard />} />
            <Route path="/datasets/list" element={<DatasetsHome />} />
            <Route path="/datasets/d/:id" element={<DatasetPage />} />
            <Route path="/strategy" element={<StrategyDashboard />} />
            <Route path="/strategy/replacement" element={<StrategyReplacement />} />
            <Route path="/strategy/compare" element={<StrategyCompare />} />
            <Route path="/strategy/failure-finding" element={<StrategyFailureFinding />} />
            <Route path="/strategy/tracking" element={<Navigate to="/fleet/tracking" replace />} />
            <Route path="/strategy/tracking/:modelId" element={<TrackingRedirect />} />
            <Route path="/fleet" element={<FleetDashboard />} />
            <Route path="/fleet/tracking" element={<FleetTrackingHome />} />
            <Route path="/fleet/tracking/:fleetId" element={<StrategyTracking />} />
            <Route path="/fleet/forecasts" element={<FleetForecasts />} />
            <Route path="/fleet/forecasts/:id" element={<FleetForecastPage />} />
            <Route path="/strategy/analyses" element={<StrategyAnalyses />} />
            <Route path="/strategy/analyses/:id" element={<StrategyAnalysisPage />} />
            {agentEnabled && <Route path="/agent" element={<ReliabilityAgent />} />}
            <Route path="/rcm" element={<RcmDashboard />} />
            <Route path="/rcm/studies" element={<RcmHome />} />
            <Route path="/rcm/studies/:id" element={<RcmStudyPage />} />
            <Route path="/team" element={<TeamSettingsPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/api-docs" element={<ApiDocsPage />} />
            {/* API tokens moved into Settings; keep old links working. */}
            <Route path="/tokens" element={<Navigate to="/settings?tab=api" replace />} />
            <Route path="/admin" element={<AdminPage />} />
            {billing && <Route path="/billing" element={<BillingPage />} />}
            <Route path="*" element={<Navigate to="/modelling" replace />} />
          </Routes>
          </Suspense>
          </ErrorBoundary>
        </main>
        {ai && <ChatPanel />}
      </div>
    </>
  );
}

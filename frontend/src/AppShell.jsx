import { useState } from "react";
import { Navigate, Route, Routes, useParams } from "react-router-dom";
import NavBar from "./components/NavBar.jsx";
import ErrorBoundary from "./components/ErrorBoundary.jsx";
import Sidebar from "./components/Sidebar.jsx";
import ChatPanel from "./components/ChatPanel.jsx";
import BillingPage from "./views/BillingPage.jsx";
import ModellingDashboard from "./views/ModellingDashboard.jsx";
import ModellingHome from "./views/ModellingHome.jsx";
import ModelPage from "./views/ModelPage.jsx";
import ModellingCompare from "./views/ModellingCompare.jsx";
import DegradationHome from "./views/DegradationHome.jsx";
import DegradationModelPage from "./views/DegradationModelPage.jsx";
import RbdDashboard from "./views/RbdDashboard.jsx";
import RbdHome from "./views/RbdHome.jsx";
import RbdBuilder from "./views/RbdBuilder.jsx";
import DatasetsDashboard from "./views/DatasetsDashboard.jsx";
import DatasetsHome from "./views/DatasetsHome.jsx";
import DatasetPage from "./views/DatasetPage.jsx";
import StrategyDashboard from "./views/StrategyDashboard.jsx";
import StrategyReplacement from "./views/StrategyReplacement.jsx";
import StrategyCompare from "./views/StrategyCompare.jsx";
import StrategyFailureFinding from "./views/StrategyFailureFinding.jsx";
import StrategyAnalyses from "./views/StrategyAnalyses.jsx";
import StrategyTracking from "./views/StrategyTracking.jsx";
import FleetDashboard from "./views/FleetDashboard.jsx";
import FleetForecasts from "./views/FleetForecasts.jsx";
import FleetTrackingHome from "./views/FleetTrackingHome.jsx";
import FleetForecastPage from "./views/FleetForecastPage.jsx";
import StrategyAnalysisPage from "./views/StrategyAnalysisPage.jsx";
import RcmDashboard from "./views/RcmDashboard.jsx";
import RcmHome from "./views/RcmHome.jsx";
import RcmStudyPage from "./views/RcmStudyPage.jsx";
import TeamSettingsPage from "./views/TeamSettingsPage.jsx";
import SettingsPage from "./views/SettingsPage.jsx";
import AdminPage from "./views/AdminPage.jsx";
import { useAppConfig } from "./ConfigProvider.jsx";
import { useWorkspace } from "./WorkspaceProvider.jsx";

// The authenticated app shell and every view inside it. This module is
// code-split: App.jsx lazy-imports it, so the public/marketing pages ship
// without the app bundle (Plotly, the RBD canvas, etc.) — that JavaScript
// only downloads once someone is actually entering the app.

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
  const { ai, billing } = useAppConfig();
  // Keying the routed content on the workspace remounts every view on switch,
  // so all lists refetch under the new X-Workspace-Id without any per-view code.
  const { workspace } = useWorkspace();
  return (
    <>
      <NavBar />
      <div className="layout">
        <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)} />
        <main className="content" key={workspace}>
          <ErrorBoundary>
          <Routes>
            <Route path="/" element={<Navigate to="/modelling" replace />} />
            <Route path="/modelling" element={<ModellingDashboard />} />
            <Route path="/modelling/models" element={<ModellingHome />} />
            <Route path="/modelling/compare" element={<ModellingCompare />} />
            <Route path="/modelling/degradation" element={<DegradationHome />} />
            <Route path="/modelling/degradation/:id" element={<DegradationModelPage />} />
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
            <Route path="/rcm" element={<RcmDashboard />} />
            <Route path="/rcm/studies" element={<RcmHome />} />
            <Route path="/rcm/studies/:id" element={<RcmStudyPage />} />
            <Route path="/team" element={<TeamSettingsPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            {/* API tokens moved into Settings; keep old links working. */}
            <Route path="/tokens" element={<Navigate to="/settings?tab=api" replace />} />
            <Route path="/admin" element={<AdminPage />} />
            {billing && <Route path="/billing" element={<BillingPage />} />}
            <Route path="*" element={<Navigate to="/modelling" replace />} />
          </Routes>
          </ErrorBoundary>
        </main>
        {ai && <ChatPanel />}
      </div>
    </>
  );
}

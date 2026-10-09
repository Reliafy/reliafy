import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { Navigate, Route, Routes, useLocation, useParams } from "react-router-dom";
import NavBar from "./components/NavBar.jsx";
import ErrorBoundary from "./components/ErrorBoundary.jsx";
import Sidebar from "./components/Sidebar.jsx";
import ChatPanel from "./components/ChatPanel.jsx";
import VerifyEmailBanner from "./components/VerifyEmailBanner.jsx";
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
const RbdHome = lazy(() => import("./views/RbdHome.jsx"));
const RbdBuilder = lazy(() => import("./views/RbdBuilder.jsx"));
const DatasetsHome = lazy(() => import("./views/DatasetsHome.jsx"));
const DatasetPage = lazy(() => import("./views/DatasetPage.jsx"));
const StrategyReplacement = lazy(() => import("./views/StrategyReplacement.jsx"));
const StrategyCompare = lazy(() => import("./views/StrategyCompare.jsx"));
const StrategyFailureFinding = lazy(() => import("./views/StrategyFailureFinding.jsx"));
const StrategyDemonstration = lazy(() => import("./views/StrategyDemonstration.jsx"));
const StrategyAnalyses = lazy(() => import("./views/StrategyAnalyses.jsx"));
const StrategyTracking = lazy(() => import("./views/StrategyTracking.jsx"));
const FleetForecasts = lazy(() => import("./views/FleetForecasts.jsx"));
const FleetTrackingHome = lazy(() => import("./views/FleetTrackingHome.jsx"));
const FleetForecastPage = lazy(() => import("./views/FleetForecastPage.jsx"));
const StrategyAnalysisPage = lazy(() => import("./views/StrategyAnalysisPage.jsx"));
const RcmHome = lazy(() => import("./views/RcmHome.jsx"));
const RcmStudyPage = lazy(() => import("./views/RcmStudyPage.jsx"));
const TeamSettingsPage = lazy(() => import("./views/TeamSettingsPage.jsx"));
const SettingsPage = lazy(() => import("./views/SettingsPage.jsx"));
const ApiDocsPage = lazy(() => import("./views/ApiDocsPage.jsx"));
const ReliabilityAgent = lazy(() => import("./views/ReliabilityAgent.jsx"));
const AdminPage = lazy(() => import("./views/AdminPage.jsx"));
import { useAppConfig } from "./ConfigProvider.jsx";
import { unmatchedRoute } from "./appConfig.js";
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

// The desktop rail's collapsed/expanded choice is remembered per device.
// Storage can throw (private mode, blocked site data), so access is guarded.
const COLLAPSED_KEY = "reliafy.sidebarCollapsed";
function readCollapsed() {
  try {
    return localStorage.getItem(COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}

// Below this width the sidebar leaves the layout and becomes an off-canvas
// drawer, opened from the menu button in the top bar. Keep in step with the
// `max-width: 720px` sidebar rules in index.css.
const PHONE_QUERY = "(max-width: 720px)";
function usePhone() {
  const [phone, setPhone] = useState(() => window.matchMedia(PHONE_QUERY).matches);
  useEffect(() => {
    const mq = window.matchMedia(PHONE_QUERY);
    const onChange = () => setPhone(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return phone;
}

export default function AppShell() {
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const phone = usePhone();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuButtonRef = useRef(null);
  const { pathname } = useLocation();
  const toggleCollapsed = () => {
    const next = !collapsed;
    setCollapsed(next);
    try {
      localStorage.setItem(COLLAPSED_KEY, next ? "1" : "0");
    } catch {
      // Not remembered on this device; the toggle still applies.
    }
  };
  // The drawer closes on navigation, and whenever the window grows wide
  // enough for the rail.
  useEffect(() => {
    setMenuOpen(false);
  }, [pathname, phone]);
  // Backdrop tap, Escape or the close button: focus returns to the menu button.
  const closeMenu = useCallback(() => {
    setMenuOpen(false);
    menuButtonRef.current?.focus();
  }, []);
  // Deployment capabilities: hide the assistant and billing entirely when this
  // deployment can't offer them (e.g. an open-source self-hosted instance).
  const config = useAppConfig();
  const { ai, billing, reliability_agent: agentEnabled } = config;
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
      <NavBar
        menuOpen={phone && menuOpen}
        onMenu={() => setMenuOpen((o) => !o)}
        menuButtonRef={menuButtonRef}
      />
      <VerifyEmailBanner />
      <div className="layout">
        <Sidebar
          collapsed={!phone && collapsed}
          onToggle={toggleCollapsed}
          phone={phone}
          open={phone && menuOpen}
          onClose={closeMenu}
        />
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
            {/* Each section opens on its list (#312); the old list URLs redirect. */}
            <Route path="/rbds" element={<RbdHome />} />
            <Route path="/rbds/list" element={<Navigate to="/rbds" replace />} />
            <Route path="/rbds/b" element={<RbdBuilder />} />
            <Route path="/rbds/b/:id" element={<RbdBuilder />} />
            <Route path="/datasets" element={<DatasetsHome />} />
            <Route path="/datasets/list" element={<Navigate to="/datasets" replace />} />
            <Route path="/datasets/d/:id" element={<DatasetPage />} />
            <Route path="/strategy" element={<StrategyAnalyses />} />
            <Route path="/strategy/replacement" element={<StrategyReplacement />} />
            <Route path="/strategy/compare" element={<StrategyCompare />} />
            <Route path="/strategy/failure-finding" element={<StrategyFailureFinding />} />
            <Route path="/strategy/demonstration-test" element={<StrategyDemonstration />} />
            <Route path="/strategy/tracking" element={<Navigate to="/fleet/tracking" replace />} />
            <Route path="/strategy/tracking/:modelId" element={<TrackingRedirect />} />
            <Route path="/fleet" element={<FleetForecasts />} />
            <Route path="/fleet/tracking" element={<FleetTrackingHome />} />
            <Route path="/fleet/tracking/:fleetId" element={<StrategyTracking />} />
            <Route path="/fleet/forecasts" element={<Navigate to="/fleet" replace />} />
            <Route path="/fleet/forecasts/:id" element={<FleetForecastPage />} />
            <Route path="/strategy/analyses" element={<Navigate to="/strategy" replace />} />
            <Route path="/strategy/analyses/:id" element={<StrategyAnalysisPage />} />
            {agentEnabled && <Route path="/agent" element={<ReliabilityAgent />} />}
            <Route path="/rcm" element={<RcmHome />} />
            <Route path="/rcm/studies" element={<Navigate to="/rcm" replace />} />
            <Route path="/rcm/studies/:id" element={<RcmStudyPage />} />
            <Route path="/team" element={<TeamSettingsPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/api-docs" element={<ApiDocsPage />} />
            {/* API tokens moved into Settings; keep old links working. */}
            <Route path="/tokens" element={<Navigate to="/settings?tab=api" replace />} />
            <Route path="/admin" element={<AdminPage />} />
            {billing && <Route path="/billing" element={<BillingPage />} />}
            {/* Until the config loads, /billing and /agent aren't registered:
                wait rather than redirect a direct load of them. */}
            <Route
              path="*"
              element={unmatchedRoute(config) === "redirect"
                ? <Navigate to="/modelling" replace />
                : <div className="card empty view-loading">Loading…</div>}
            />
          </Routes>
          </Suspense>
          </ErrorBoundary>
        </main>
        {ai && <ChatPanel />}
      </div>
    </>
  );
}

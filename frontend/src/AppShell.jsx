import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { Navigate, Route, Routes, useLocation, useParams } from "react-router-dom";
import NavBar from "./components/NavBar.jsx";
import ErrorBoundary from "./components/ErrorBoundary.jsx";
import Sidebar from "./components/Sidebar.jsx";
import ChatPanel from "./components/ChatPanel.jsx";
import VerifyEmailBanner from "./components/VerifyEmailBanner.jsx";
import { WalkthroughProvider } from "./components/Walkthrough.jsx";
const BillingPage = lazy(() => import("./views/BillingPage.jsx"));
const HomePage = lazy(() => import("./views/HomePage.jsx"));
const ReportsPage = lazy(() => import("./views/ReportsPage.jsx"));
const PlannedPage = lazy(() => import("./views/PlannedPage.jsx"));
const ModellingHome = lazy(() => import("./views/ModellingHome.jsx"));
const AllModelsPage = lazy(() => import("./views/AllModelsPage.jsx"));
const NewModelPage = lazy(() => import("./views/NewModelPage.jsx"));
const ModelPage = lazy(() => import("./views/ModelPage.jsx"));
const JointHome = lazy(() => import("./views/JointHome.jsx"));
const JointNewPage = lazy(() => import("./views/JointNewPage.jsx"));
const JointModelPage = lazy(() => import("./views/JointModelPage.jsx"));
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
// Simulation run history (#112).
const RbdRuns = lazy(() => import("./views/RbdRuns.jsx"));
const RbdRunsDetail = lazy(() => import("./views/RbdRunsDetail.jsx"));
const RbdRunsCompare = lazy(() => import("./views/RbdRunsCompare.jsx"));
const DatasetsHome = lazy(() => import("./views/DatasetsHome.jsx"));
const DatasetPage = lazy(() => import("./views/DatasetPage.jsx"));
const StrategyReplacement = lazy(() => import("./views/StrategyReplacement.jsx"));
const StrategyCompare = lazy(() => import("./views/StrategyCompare.jsx"));
const StrategyFailureFinding = lazy(() => import("./views/StrategyFailureFinding.jsx"));
const StrategyTestPlanning = lazy(() => import("./views/StrategyTestPlanning.jsx"));
const StrategyAnalyses = lazy(() => import("./views/StrategyAnalyses.jsx"));
const StrategyTracking = lazy(() => import("./views/StrategyTracking.jsx"));
const FleetForecasts = lazy(() => import("./views/FleetForecasts.jsx"));
const FleetTrackingHome = lazy(() => import("./views/FleetTrackingHome.jsx"));
const FleetForecastPage = lazy(() => import("./views/FleetForecastPage.jsx"));
const StrategyAnalysisPage = lazy(() => import("./views/StrategyAnalysisPage.jsx"));
const RcmHome = lazy(() => import("./views/RcmHome.jsx"));
const RcmStudyPage = lazy(() => import("./views/RcmStudyPage.jsx"));
const MaintenanceHome = lazy(() => import("./views/MaintenanceHome.jsx"));
const MaintenanceAssets = lazy(() => import("./views/MaintenanceAssets.jsx"));
const MaintenancePosition = lazy(() => import("./views/MaintenancePosition.jsx"));
const MaintenanceWorkOrder = lazy(() => import("./views/MaintenanceWorkOrder.jsx"));
const MaintenanceItem = lazy(() => import("./views/MaintenanceItem.jsx"));
const MaintenanceItems = lazy(() => import("./views/MaintenanceLists.jsx").then((m) => ({ default: m.MaintenanceItems })));
const MaintenanceLocations = lazy(() => import("./views/MaintenanceLists.jsx").then((m) => ({ default: m.MaintenanceLocations })));
const MaintenanceLocation = lazy(() => import("./views/MaintenanceLists.jsx").then((m) => ({ default: m.MaintenanceLocation })));
const MaintenanceClasses = lazy(() => import("./views/MaintenanceLists.jsx").then((m) => ({ default: m.MaintenanceClasses })));
const MaintenancePartsPage = lazy(() => import("./views/MaintenanceLists.jsx").then((m) => ({ default: m.MaintenanceParts })));
const MaintenancePart = lazy(() => import("./views/MaintenancePart.jsx"));
const TeamSettingsPage = lazy(() => import("./views/TeamSettingsPage.jsx"));
const SettingsPage = lazy(() => import("./views/SettingsPage.jsx"));
const ApiDocsPage = lazy(() => import("./views/ApiDocsPage.jsx"));
const ReliabilityAgent = lazy(() => import("./views/ReliabilityAgent.jsx"));
const AdminPage = lazy(() => import("./views/AdminPage.jsx"));
// What changed in the workspace (#41).
const ChangesPage = lazy(() => import("./views/ChangesPage.jsx"));
import { useAppConfig } from "./ConfigProvider.jsx";
import { unmatchedRoute } from "./appConfig.js";
import { useWorkspace } from "./WorkspaceProvider.jsx";
import { RolesProvider } from "./RolesProvider.jsx";
import { MOVED, fillMoved } from "./redirects.js";

// The authenticated app shell. This module is code-split: App.jsx
// lazy-imports it, so the public/marketing pages ship without the app bundle.
// Each view is lazy too, so opening the app downloads only the shell and the
// page being viewed — the chart library (Plotly) and the diagram canvas (React
// Flow) arrive with the pages that use them. The chart module is prefetched
// once the browser is idle so the first chart page doesn't wait for it.

// An earlier address (redirects.js): to the page's new place, with the same
// ids, query, #hash and navigation state.
function Moved({ to }) {
  const params = useParams();
  const { search, hash, state } = useLocation();
  const encoded = Object.fromEntries(Object.entries(params).map(([k, v]) => [k, encodeURIComponent(v ?? "")]));
  return <Navigate to={fillMoved(to, encoded) + search + hash} state={state} replace />;
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
  const { ai, billing, reliability_agent: agentEnabled, maintenance: maintenanceEnabled } = config;
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
    <RolesProvider>
    <WalkthroughProvider>
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
            <Route path="/" element={<Navigate to="/home" replace />} />
            <Route path="/home" element={<HomePage />} />

            {/* Design: systems as designed. */}
            <Route path="/systems" element={<RbdHome />} />
            <Route path="/systems/b" element={<RbdBuilder />} />
            <Route path="/systems/b/:id" element={<RbdBuilder />} />
            <Route path="/systems/runs" element={<RbdRuns />} />
            <Route path="/systems/runs/compare" element={<RbdRunsCompare />} />
            <Route path="/systems/runs/:runId" element={<RbdRunsDetail />} />
            {maintenanceEnabled && <Route path="/systems/structure" element={<MaintenancePartsPage view="structure" />} />}

            {/* Operate: the assets as maintained (Reliafy Maintenance), and
                their maintenance. ("/assets" is where the server keeps the
                build's files, so the register lives at /asset-register.) */}
            {maintenanceEnabled && <Route path="/asset-register" element={<MaintenanceAssets />} />}
            {maintenanceEnabled && <Route path="/asset-register/positions" element={<MaintenanceHome part="positions" />} />}
            {maintenanceEnabled && <Route path="/asset-register/positions/:id" element={<MaintenancePosition />} />}
            {maintenanceEnabled && <Route path="/asset-register/items" element={<MaintenanceItems />} />}
            {maintenanceEnabled && <Route path="/asset-register/items/:id" element={<MaintenanceItem />} />}
            {maintenanceEnabled && <Route path="/asset-register/locations" element={<MaintenanceLocations />} />}
            {maintenanceEnabled && <Route path="/asset-register/locations/:id" element={<MaintenanceLocation />} />}
            {maintenanceEnabled && <Route path="/asset-register/classes" element={<MaintenanceClasses />} />}
            {maintenanceEnabled && <Route path="/asset-register/classes/:name" element={<MaintenanceClasses />} />}
            {maintenanceEnabled && <Route path="/asset-register/parts" element={<MaintenancePartsPage />} />}
            {maintenanceEnabled && <Route path="/asset-register/parts/:id" element={<MaintenancePart />} />}
            {maintenanceEnabled && <Route path="/maintenance" element={<MaintenanceHome part="work" />} />}
            {maintenanceEnabled && <Route path="/maintenance/work-orders/:id" element={<MaintenanceWorkOrder />} />}
            <Route path="/maintenance/rcm" element={<RcmHome />} />
            <Route path="/maintenance/rcm/:id" element={<RcmStudyPage />} />

            {/* Analyse: the calculations. */}
            <Route path="/data" element={<DatasetsHome />} />
            <Route path="/data/:id" element={<DatasetPage />} />
            {/* Models opens on every model; its children are the types. */}
            <Route path="/models" element={<AllModelsPage />} />
            <Route path="/models/life" element={<ModellingHome />} />
            <Route path="/models/new" element={<NewModelPage />} />
            <Route path="/models/m/:id" element={<ModelPage />} />
            <Route path="/models/degradation" element={<DegradationHome />} />
            <Route path="/models/degradation/:id" element={<DegradationModelPage />} />
            <Route path="/models/recurrent" element={<RecurrentHome />} />
            <Route path="/models/recurrent/new" element={<RecurrentNewPage />} />
            <Route path="/models/recurrent/:id" element={<RecurrentModelPage />} />
            <Route path="/models/alt" element={<AltHome />} />
            <Route path="/models/alt/new" element={<AltNewPage />} />
            <Route path="/models/alt/:id" element={<AltModelPage />} />
            <Route path="/models/joint" element={<JointHome />} />
            <Route path="/models/joint/new" element={<JointNewPage />} />
            <Route path="/models/joint/:id" element={<JointModelPage />} />
            <Route path="/models/tracking" element={<FleetTrackingHome />} />
            <Route path="/models/tracking/:fleetId" element={<StrategyTracking />} />
            <Route path="/strategy" element={<StrategyAnalyses />} />
            <Route path="/strategy/replacement" element={<StrategyReplacement />} />
            <Route path="/strategy/compare" element={<StrategyCompare />} />
            <Route path="/strategy/failure-finding" element={<StrategyFailureFinding />} />
            <Route path="/strategy/test-planning" element={<StrategyTestPlanning />} />
            <Route path="/strategy/test-planning/sequential" element={<StrategyTestPlanning />} />
            <Route path="/strategy/test-planning/life" element={<StrategyTestPlanning />} />
            <Route path="/strategy/test-planning/accelerated" element={<StrategyTestPlanning />} />
            <Route path="/strategy/test-planning/comparison" element={<StrategyTestPlanning />} />
            <Route path="/strategy/analyses/:id" element={<StrategyAnalysisPage />} />
            {/* The fleets' forecasts and (Reliafy Maintenance) the position classes'. */}
            <Route path="/forecasts" element={<FleetForecasts />} />
            <Route path="/forecasts/:id" element={<FleetForecastPage />} />

            {/* Blank pages for menu entries not built yet (plannedPages.js). */}
            <Route path="/requirements" element={<PlannedPage id="requirements" />} />
            <Route path="/failures" element={<PlannedPage id="failures" />} />
            <Route path="/risk" element={<PlannedPage id="risk" />} />
            <Route path="/asset-register/fleets" element={<PlannedPage id="fleets" />} />
            <Route path="/maintenance/inbox" element={<PlannedPage id="inbox" />} />
            <Route path="/data/library" element={<PlannedPage id="library" />} />
            <Route path="/systems/fault-trees" element={<PlannedPage id="fault-trees" />} />
            <Route path="/systems/fmeca" element={<PlannedPage id="fmeca" />} />

            <Route path="/reports" element={<ReportsPage />} />
            {agentEnabled && <Route path="/agent" element={<ReliabilityAgent />} />}

            {/* Account. */}
            <Route path="/team" element={<TeamSettingsPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/api-docs" element={<ApiDocsPage page="" />} />
            <Route path="/api-docs/authentication" element={<ApiDocsPage page="authentication" />} />
            <Route path="/api-docs/tools" element={<ApiDocsPage page="tools" />} />
            <Route path="/api-docs/examples" element={<ApiDocsPage page="examples" />} />
            <Route path="/api-docs/cli" element={<ApiDocsPage page="cli" />} />
            <Route path="/api-docs/python" element={<ApiDocsPage page="python" />} />
            <Route path="/api-docs/files" element={<ApiDocsPage page="files" />} />
            <Route path="/api-docs/mcp" element={<ApiDocsPage page="mcp" />} />
            <Route path="/api-docs/v1-routes" element={<ApiDocsPage page="v1-routes" />} />
            <Route path="/admin" element={<AdminPage />} />
            <Route path="/changes" element={<ChangesPage />} />
            {billing && <Route path="/billing" element={<BillingPage />} />}

            {/* Earlier addresses, each to its page's new place (redirects.js). */}
            {MOVED.map((m) => <Route key={m.path} path={m.path} element={<Moved to={m.to} />} />)}
            {/* API tokens moved into Settings; keep old links working. */}
            <Route path="/tokens" element={<Navigate to="/settings?tab=api" replace />} />
            {/* Until the config loads, /billing and /agent aren't registered:
                wait rather than redirect a direct load of them. */}
            <Route
              path="*"
              element={unmatchedRoute(config) === "redirect"
                ? <Navigate to="/home" replace />
                : <div className="card empty view-loading">Loading…</div>}
            />
          </Routes>
          </Suspense>
          </ErrorBoundary>
        </main>
        {ai && <ChatPanel />}
      </div>
    </WalkthroughProvider>
    </RolesProvider>
  );
}

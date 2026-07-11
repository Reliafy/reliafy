import { useState } from "react";
import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
} from "react-router-dom";
import NavBar from "./components/NavBar.jsx";
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
import StrategyAnalysisPage from "./views/StrategyAnalysisPage.jsx";
import RcmDashboard from "./views/RcmDashboard.jsx";
import RcmHome from "./views/RcmHome.jsx";
import RcmStudyPage from "./views/RcmStudyPage.jsx";
import Login from "./views/Login.jsx";
import Landing from "./views/Landing.jsx";
import Blog from "./views/Blog.jsx";
import BlogPost from "./views/BlogPost.jsx";
import TermsPage from "./views/TermsPage.jsx";
import PrivacyPage from "./views/PrivacyPage.jsx";
import { AuthProvider, useAuth } from "./AuthProvider.jsx";
import { ConfigProvider, useAppConfig } from "./ConfigProvider.jsx";
import { AUTH_DISABLED } from "./firebase.js";

// Gate the app shell behind authentication: while auth initialises show a
// spinner; if signed out, redirect to /login.
function RequireAuth({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="auth-loading">Loading…</div>;
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

function AppShell() {
  const [collapsed, setCollapsed] = useState(false);
  // Deployment capabilities: hide the assistant and billing entirely when this
  // deployment can't offer them (e.g. an open-source self-hosted instance).
  const { ai, billing } = useAppConfig();
  return (
    <>
      <NavBar />
      <div className="layout">
        <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)} />
        <main className="content">
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
            <Route path="/strategy/analyses" element={<StrategyAnalyses />} />
            <Route path="/strategy/analyses/:id" element={<StrategyAnalysisPage />} />
            <Route path="/rcm" element={<RcmDashboard />} />
            <Route path="/rcm/studies" element={<RcmHome />} />
            <Route path="/rcm/studies/:id" element={<RcmStudyPage />} />
            {billing && <Route path="/billing" element={<BillingPage />} />}
            <Route path="*" element={<Navigate to="/modelling" replace />} />
          </Routes>
        </main>
        {ai && <ChatPanel />}
      </div>
    </>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <ConfigProvider>
        <AuthProvider>
          <Routes>
            {/* Marketing storefront (landing, blog) and login only exist on
                multi-user (cloud) builds. Single-user self-host builds go
                straight into the app: these routes fall through to the shell,
                whose catch-all redirects to /modelling. */}
            {!AUTH_DISABLED && <Route path="/" element={<Landing />} />}
            {!AUTH_DISABLED && <Route path="/blog" element={<Blog />} />}
            {!AUTH_DISABLED && <Route path="/blog/:slug" element={<BlogPost />} />}
            {!AUTH_DISABLED && <Route path="/terms" element={<TermsPage />} />}
            {!AUTH_DISABLED && <Route path="/privacy" element={<PrivacyPage />} />}
            {!AUTH_DISABLED && <Route path="/login" element={<Login />} />}
            <Route path="/*" element={<RequireAuth><AppShell /></RequireAuth>} />
          </Routes>
        </AuthProvider>
      </ConfigProvider>
    </BrowserRouter>
  );
}

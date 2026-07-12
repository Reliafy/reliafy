import { lazy, Suspense, useEffect } from "react";
import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import Login from "./views/Login.jsx";
import Landing from "./views/Landing.jsx";
import Blog from "./views/Blog.jsx";
import BlogPost from "./views/BlogPost.jsx";
import TermsPage from "./views/TermsPage.jsx";
import PrivacyPage from "./views/PrivacyPage.jsx";
import LearnIndex from "./views/LearnIndex.jsx";
import LearnArticle from "./views/LearnArticle.jsx";
import ProductPage from "./views/ProductPage.jsx";
import { PRODUCT_PAGES } from "./productPages.jsx";
import { AuthProvider, useAuth } from "./AuthProvider.jsx";
import { ConfigProvider } from "./ConfigProvider.jsx";
import { WorkspaceProvider } from "./WorkspaceProvider.jsx";
import { AUTH_DISABLED } from "./firebase.js";
import { installTelemetry, trackEvent } from "./telemetry.js";

// The authenticated app (and its heavyweight dependencies — Plotly, the RBD
// canvas) is a separate chunk: marketing/blog/learn visitors never download
// it, and it only loads when someone signed-in actually enters the app.
// The public pages above stay statically imported because they hydrate
// prerendered HTML — lazy-loading them would flash a fallback on first paint.
const AppShell = lazy(() => import("./AppShell.jsx"));

// Public read-only artifact viewer (/p/:token). Lazy for the same reason:
// it pulls in the charting components, which marketing pages don't need.
const PublicArtifact = lazy(() => import("./views/PublicArtifact.jsx"));

// Gate the app shell behind authentication: while auth initialises show a
// spinner; if signed out, redirect to /login.
function RequireAuth({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="auth-loading">Loading…</div>;
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

function PageViews() {
  const { pathname } = useLocation();
  useEffect(() => {
    trackEvent("pageview");
  }, [pathname]);
  return null;
}

export default function App() {
  useEffect(() => installTelemetry(), []);
  return (
    <BrowserRouter>
      <PageViews />
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
            {!AUTH_DISABLED && <Route path="/learn" element={<LearnIndex />} />}
            {!AUTH_DISABLED && <Route path="/learn/:slug" element={<LearnArticle />} />}
            {!AUTH_DISABLED &&
              PRODUCT_PAGES.map((p) => (
                <Route key={p.path} path={p.path} element={<ProductPage page={p} />} />
              ))}
            {!AUTH_DISABLED && (
              <Route
                path="/p/:token"
                element={
                  <Suspense fallback={<div className="auth-loading">Loading…</div>}>
                    <PublicArtifact />
                  </Suspense>
                }
              />
            )}
            {!AUTH_DISABLED && <Route path="/terms" element={<TermsPage />} />}
            {!AUTH_DISABLED && <Route path="/privacy" element={<PrivacyPage />} />}
            {!AUTH_DISABLED && <Route path="/login" element={<Login />} />}
            <Route
              path="/*"
              element={
                <RequireAuth>
                  <WorkspaceProvider>
                    <Suspense fallback={<div className="auth-loading">Loading…</div>}>
                      <AppShell />
                    </Suspense>
                  </WorkspaceProvider>
                </RequireAuth>
              }
            />
          </Routes>
        </AuthProvider>
      </ConfigProvider>
    </BrowserRouter>
  );
}

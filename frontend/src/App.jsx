import { lazy, Suspense, useEffect } from "react";
import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigationType,
} from "react-router-dom";
import Login from "./views/Login.jsx";
import Landing from "./views/Landing.jsx";
import Blog from "./views/Blog.jsx";
import BlogPost from "./views/BlogPost.jsx";
import WhatsNew from "./views/WhatsNew.jsx";
import WhatsNewPost from "./views/WhatsNewPost.jsx";
import Unsubscribe from "./views/Unsubscribe.jsx";
import TermsPage from "./views/TermsPage.jsx";
import PrivacyPage from "./views/PrivacyPage.jsx";
import LearnArticle from "./views/LearnArticle.jsx";
import GuidesIndex from "./views/GuidesIndex.jsx";
import GuidePage from "./views/GuidePage.jsx";
import ReferenceIndex from "./views/ReferenceIndex.jsx";
import ReferenceFamily from "./views/ReferenceFamily.jsx";
import ApiDocsPublicPage from "./views/ApiDocsPublicPage.jsx";
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
const OAuthConsent = lazy(() => import("./views/OAuthConsent.jsx"));

// Gate the app shell behind authentication: while auth initialises show a
// spinner; if signed out, redirect to /login.
function RequireAuth({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="auth-loading">Loading…</div>;
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

// A new page opens at the top (#309): the router keeps the window's scroll
// across a link, so a page could open part-way down with its title under the
// bar. Back and forward (POP) leave the browser's own restoration alone, and
// an in-page #anchor keeps its target.
function ScrollToTop() {
  const { pathname, hash } = useLocation();
  const navType = useNavigationType();
  useEffect(() => {
    if (navType !== "POP" && !hash) window.scrollTo(0, 0);
  }, [pathname]);
  return null;
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
      <ScrollToTop />
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
            {!AUTH_DISABLED && <Route path="/whats-new" element={<WhatsNew />} />}
            {!AUTH_DISABLED && <Route path="/whats-new/:slug" element={<WhatsNewPost />} />}
            {/* The Learn index is consolidated into /blog; articles keep their
                own /learn/:slug URLs (those are the indexed pages). */}
            {!AUTH_DISABLED && <Route path="/learn" element={<Navigate to="/blog" replace />} />}
            {!AUTH_DISABLED && <Route path="/learn/:slug" element={<LearnArticle />} />}
            {!AUTH_DISABLED && <Route path="/guides" element={<GuidesIndex />} />}
            {!AUTH_DISABLED && <Route path="/guides/:slug" element={<GuidePage />} />}
            {!AUTH_DISABLED && <Route path="/reference" element={<ReferenceIndex />} />}
            {!AUTH_DISABLED && <Route path="/reference/:family" element={<ReferenceFamily />} />}
            {!AUTH_DISABLED && <Route path="/api-docs" element={<ApiDocsPublicPage />} />}
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
            {/* Signed-token unsubscribe from product-update emails: public,
                client-rendered only (not prerendered, not in the sitemap). */}
            {!AUTH_DISABLED && <Route path="/unsubscribe" element={<Unsubscribe />} />}
            {!AUTH_DISABLED && <Route path="/login" element={<Login />} />}
            {/* OAuth consent for Claude connectors / MCP clients. Public so a
                signed-out user can sign in and come straight back; noindex,
                not prerendered, not in the sitemap. Lazy: rarely visited. */}
            <Route
              path="/oauth/consent"
              element={
                <Suspense fallback={<div className="auth-loading">Loading…</div>}>
                  <OAuthConsent />
                </Suspense>
              }
            />
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

// Build-time prerender entry (SSG for the marketing pages). Bundled with
// `vite build --ssr` and executed by scripts/prerender.mjs in plain Node —
// no browser involved. Only the public pages are rendered; the app itself
// stays a client-side SPA.
import { renderToString } from "react-dom/server";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./AuthProvider.jsx";
import { ConfigProvider } from "./ConfigProvider.jsx";
import Landing from "./views/Landing.jsx";
import Blog from "./views/Blog.jsx";
import BlogPost from "./views/BlogPost.jsx";
import TermsPage from "./views/TermsPage.jsx";
import PrivacyPage from "./views/PrivacyPage.jsx";
import { posts } from "./blog.js";

const SITE = "https://reliafy.com";

// Every prerendered route with its head metadata (title, description).
export function routes() {
  const base = [
    {
      path: "/",
      title: "Reliafy — open-source reliability engineering",
      description:
        "Fit Weibull and other life distributions, build reliability block diagrams, and turn failure data into maintenance decisions. Open source and self-hostable, or ready in seconds in the cloud.",
    },
    {
      path: "/blog",
      title: "Blog — Reliafy",
      description: "Product updates and practical notes on reliability engineering from the Reliafy team.",
    },
    {
      path: "/terms",
      title: "Terms of Service — Reliafy",
      description: "The terms that govern Reliafy Cloud accounts, plans, and AI credits.",
    },
    {
      path: "/privacy",
      title: "Privacy Policy — Reliafy",
      description: "What Reliafy Cloud collects, who processes it, and how to get your data deleted.",
    },
  ];
  const blog = posts.map((p) => ({
    path: `/blog/${p.slug}`,
    title: `${p.title} — Reliafy Blog`,
    description: p.summary || "",
    lastmod: p.date || null,
  }));
  return [...base, ...blog];
}

export function render(path) {
  return renderToString(
    <MemoryRouter initialEntries={[path]}>
      <ConfigProvider>
        <AuthProvider>
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/blog" element={<Blog />} />
            <Route path="/blog/:slug" element={<BlogPost />} />
            <Route path="/terms" element={<TermsPage />} />
            <Route path="/privacy" element={<PrivacyPage />} />
          </Routes>
        </AuthProvider>
      </ConfigProvider>
    </MemoryRouter>
  );
}

export { SITE };

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
import WhatsNew from "./views/WhatsNew.jsx";
import WhatsNewPost from "./views/WhatsNewPost.jsx";
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
import { posts } from "./blog.js";
import { updates } from "./updates.js";
import { articles } from "./learn.js";
import { guides } from "./guides.js";
import { families as refFamilies, totalEntries } from "./reference.js";

const SITE = "https://reliafy.com";

// Every prerendered route with its head metadata (title, description, and
// optional JSON-LD structured data). Future-dated blog posts and updates are
// already filtered out by blog.js / updates.js, so they're absent from static HTML and the
// sitemap until the first build after their date.
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
      title: "Reliability Engineering Articles & Product Updates | Reliafy",
      description:
        "Practical explainers of reliability engineering methods — Weibull analysis, censored data, MTBF vs MTTF, B10 life, availability and more — plus product updates from the Reliafy team.",
    },
    {
      path: "/whats-new",
      title: "What's new in Reliafy — Product Updates",
      description:
        "What's changed in Reliafy: new analyses, improvements and fixes to the open-source reliability engineering platform, roughly monthly.",
    },
    {
      path: "/guides",
      title: "Guides — How to use Reliafy | Step-by-step",
      description:
        "Task-oriented walkthroughs for Reliafy: build repairable RBDs and read availability, model common-cause failures and load-sharing, fit accelerated-life models, and more — a screenshot for every step.",
    },
    {
      path: "/reference",
      title: "Model Reference — every reliability model Reliafy fits",
      description:
        `Reference for all ${totalEntries} models Reliafy fits: life distributions, discrete and non-parametric estimators, survival regression, accelerated-life relationships and recurrent-event models — parameters, functional forms and when to use each.`,
    },
    {
      path: "/api-docs",
      title: "API Reference — Reliafy Reliability API",
      description:
        "The Reliafy HTTP API and reliafy-client Python package: read fitted models and reliability, create datasets and fit distributions, read fleet forecasts, run strategy calculators, and push operational data.",
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
  const product = PRODUCT_PAGES.map((p) => ({
    path: p.path,
    title: p.title,
    description: p.description,
    jsonld: p.jsonld ? [p.jsonld(p)] : [],
  }));
  const learn = articles.map((a) => ({
    path: `/learn/${a.slug}`,
    title: a.title.length > 45 ? `${a.title} | Reliafy` : `${a.title} — Reliafy Learn`,
    description: a.description,
    jsonld: [
      {
        "@context": "https://schema.org",
        "@type": "Article",
        headline: a.title,
        description: a.description,
        url: `${SITE}/learn/${a.slug}`,
        author: { "@type": "Organization", name: "Reliafy" },
        publisher: { "@type": "Organization", name: "Reliafy", url: SITE },
      },
      ...(a.faq.length
        ? [
            {
              "@context": "https://schema.org",
              "@type": "FAQPage",
              mainEntity: a.faq.map((f) => ({
                "@type": "Question",
                name: f.q,
                acceptedAnswer: { "@type": "Answer", text: f.a },
              })),
            },
          ]
        : []),
    ],
  }));
  const blog = posts.map((p) => ({
    path: `/blog/${p.slug}`,
    title: `${p.title} — Reliafy Blog`,
    description: p.summary || "",
    lastmod: p.date || null,
    image: p.image || null,
  }));
  // Future-dated updates are filtered out by updates.js, same as the blog.
  const updatePages = updates.map((u) => ({
    path: `/whats-new/${u.slug}`,
    title: `${u.title} — What's new in Reliafy`,
    description: u.summary || "",
    lastmod: u.date || null,
  }));
  const guidePages = guides.map((g) => ({
    path: `/guides/${g.slug}`,
    title: `${g.title} — Reliafy Guide`,
    description: g.task,
    jsonld: [
      {
        "@context": "https://schema.org",
        "@type": "HowTo",
        name: g.title,
        description: g.task,
        totalTime: `PT${g.minutes}M`,
        url: `${SITE}/guides/${g.slug}`,
      },
    ],
  }));
  const referencePages = refFamilies.map((f) => ({
    path: `/reference/${f.id}`,
    title: `${f.title} — Reliafy Model Reference`,
    description: f.description,
  }));
  return [...base, ...product, ...learn, ...blog, ...updatePages, ...guidePages, ...referencePages];
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
            <Route path="/whats-new" element={<WhatsNew />} />
            <Route path="/whats-new/:slug" element={<WhatsNewPost />} />
            <Route path="/learn/:slug" element={<LearnArticle />} />
            <Route path="/guides" element={<GuidesIndex />} />
            <Route path="/guides/:slug" element={<GuidePage />} />
            <Route path="/reference" element={<ReferenceIndex />} />
            <Route path="/reference/:family" element={<ReferenceFamily />} />
            <Route path="/api-docs" element={<ApiDocsPublicPage />} />
            {PRODUCT_PAGES.map((p) => (
              <Route key={p.path} path={p.path} element={<ProductPage page={p} />} />
            ))}
            <Route path="/terms" element={<TermsPage />} />
            <Route path="/privacy" element={<PrivacyPage />} />
          </Routes>
        </AuthProvider>
      </ConfigProvider>
    </MemoryRouter>
  );
}

// RSS feeds, written next to the sitemap by scripts/prerender.mjs. Built from
// the same date-gated lists as the pages, so a queued (future-dated) item
// appears in its feed on the first build on or after its date — which is what
// lets Zapier/Buffer auto-post it the day it goes live.
export function feeds() {
  const item = (base) => (x) => ({
    title: x.title,
    link: `${SITE}${base}/${x.slug}`,
    guid: `${SITE}${base}/${x.slug}`,
    date: x.date,
    summary: x.summary,
  });
  return [
    {
      path: "/whats-new/feed.xml",
      title: "Reliafy — What's new",
      link: `${SITE}/whats-new`,
      description: "Product updates from Reliafy: new features, improvements and fixes.",
      items: updates.map(item("/whats-new")),
    },
    {
      path: "/blog/feed.xml",
      title: "Reliafy blog",
      link: `${SITE}/blog`,
      description: "Reliability engineering, maintenance strategy and Reliafy in practice.",
      items: posts.map(item("/blog")),
    },
  ];
}

export { SITE };

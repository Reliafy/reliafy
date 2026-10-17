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
import { allPosts } from "./blog.js";
import { allUpdates } from "./updates.js";
import { articles } from "./learn.js";
import { guides } from "./guides.js";
import { families as refFamilies, totalEntries } from "./reference.js";
import { linkedinFeed, socialPost } from "./contentFeed.js";

// Short LinkedIn posts (#367). Globbed here, in the build-time bundle only:
// they're never part of the website's own bundle or pages.
const socialFiles = import.meta.glob("./content/social/*.md", {
  query: "?raw",
  import: "default",
  eager: true,
});

const SITE = "https://reliafy.com";

// Every prerendered route with its head metadata (title, description, and
// optional JSON-LD structured data). Future-dated blog posts and updates are
// rendered too: the server serves each page, and lists it in the sitemap,
// only from its (UTC) date — see gatedPages() and
// backend/services/content_gate.py — so search engines can read a post on
// its day without a rebuild.
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
        "The Reliafy API, the reliafy command line and the reliafy-client Python package: every tool of the Claude connector over HTTPS (fit, analyse RBDs, plan tests, strategy), an OpenAPI spec, data ingest, and file and photo uploads.",
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
  const blog = allPosts.map((p) => ({
    path: `/blog/${p.slug}`,
    title: `${p.title} — Reliafy Blog`,
    description: p.summary || "",
    lastmod: p.date || null,
    image: p.image || null,
  }));
  const updatePages = allUpdates.map((u) => ({
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

// Dated pages the server holds back until their date (UTC): path -> date.
// scripts/prerender.mjs writes them to dist/content.json; the backend skips
// a held page's prerendered HTML (answering as for any unknown path) and
// drops it from /sitemap.xml until the day.
export function gatedPages() {
  const pages = {};
  for (const p of allPosts) if (p.date) pages[`/blog/${p.slug}`] = p.date;
  for (const u of allUpdates) if (u.date) pages[`/whats-new/${u.slug}`] = u.date;
  return pages;
}

// Titles of the blog posts and updates, for the operators' monthly content
// report (backend/services/content_report.py).
export function pageTitles() {
  const titles = {};
  for (const p of allPosts) titles[`/blog/${p.slug}`] = p.title;
  for (const u of allUpdates) titles[`/whats-new/${u.slug}`] = u.title;
  return titles;
}

// Every blog post as the admin page's publishing calendar needs it
// (backend/services/content_calendar.py): the image has no source files.
export function calendarPosts() {
  return allPosts.map((p) => ({
    slug: p.slug,
    title: p.title,
    date: p.date,
    summary: p.summary,
    image: p.image,
    type: p.type,
  }));
}

// Every What's new update as the email needs it. The runtime image has no
// source files, so the scheduled send (backend/services/content_jobs.py)
// reads updates — `send: auto` ones included — from dist/content.json.
export function emailUpdates() {
  return allUpdates.map((u) => ({
    slug: u.slug,
    title: u.title,
    date: u.date,
    summary: u.summary,
    email_subject: u.emailSubject,
    send: u.send,
    body: u.body,
  }));
}

export function render(path) {
  return renderToString(
    <MemoryRouter initialEntries={[path]}>
      <ConfigProvider>
        <AuthProvider>
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/blog" element={<Blog />} />
            <Route path="/blog/:slug" element={<BlogPost includeFuture />} />
            <Route path="/whats-new" element={<WhatsNew />} />
            <Route path="/whats-new/:slug" element={<WhatsNewPost includeFuture />} />
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

// RSS feed definitions. scripts/prerender.mjs writes them — INCLUDING
// future-dated items — to dist/feeds.json; the backend (backend/routers/feeds.py)
// serves /whats-new/feed.xml, /blog/feed.xml and /social/feed.xml from it,
// filtering by the current UTC date on every request. So a queued item enters
// its feed on its date with no rebuild. /social/feed.xml is the one the
// Zapier → LinkedIn Zap watches (contentFeed.js).
export function feeds() {
  // Links in the RSS feeds carry utm_source=rss&utm_medium=feed&
  // utm_campaign=<slug>, added by the server; the guid stays the bare URL.
  const item = (base) => (x) => ({
    title: x.title,
    link: `${SITE}${base}/${x.slug}`,
    guid: `${SITE}${base}/${x.slug}`,
    date: x.date,
    summary: x.summary,
    campaign: x.slug,
  });
  const rss = { source: "rss", medium: "feed" };
  return [
    {
      path: "/whats-new/feed.xml",
      title: "Reliafy — What's new",
      link: `${SITE}/whats-new`,
      description: "Product updates from Reliafy: new features, improvements and fixes.",
      utm: rss,
      items: allUpdates.map(item("/whats-new")),
    },
    {
      path: "/blog/feed.xml",
      title: "Reliafy blog",
      link: `${SITE}/blog`,
      description: "Reliability engineering, maintenance strategy and Reliafy in practice.",
      utm: rss,
      items: allPosts.map(item("/blog")),
    },
    linkedinFeed({
      posts: allPosts,
      updates: allUpdates,
      social: Object.entries(socialFiles).map(([path, raw]) => socialPost(path, raw, SITE)),
      site: SITE,
    }),
  ];
}

export { SITE };

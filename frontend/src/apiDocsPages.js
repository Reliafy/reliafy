// The API docs' pages, in reading order. The routers (App.jsx, AppShell.jsx,
// prerender-entry.jsx) register one route per page; the sub-navigation, the
// previous / next links and the prerendered titles and descriptions read this.

export const API_DOCS_PAGES = [
  {
    slug: "",
    label: "Overview",
    heading: "API reference",
    blurb: "What the API is and a three-step quick start.",
    title: "API Reference — Reliafy Reliability API",
    description:
      "The Reliafy API, the reliafy command line and the reliafy-client Python package: every tool of the Claude connector over HTTPS (fit, analyse RBDs, plan tests, strategy), with a three-step quick start.",
  },
  {
    slug: "authentication",
    label: "Tokens and errors",
    heading: "Tokens, scopes, limits and errors",
    blurb: "Create a token, choose its scopes, and read the rate limit and error codes.",
    title: "API Tokens, Scopes and Errors — Reliafy API",
    description:
      "How to authenticate to the Reliafy API: personal tokens, the read, write and ingest scopes, the rate limit, and what each error code means.",
  },
  {
    slug: "tools",
    label: "Tools API",
    heading: "The tools API",
    blurb: "Every tool and action as a REST call, the live list, and long-running jobs.",
    title: "The Tools API — every Reliafy tool over REST",
    description:
      "Every action of every tool in Reliafy's Claude connector as a REST call (POST /api/v1/{tool}/{action}), the OpenAPI spec, the live list of tools and actions, and polling long-running jobs.",
  },
  {
    slug: "examples",
    label: "Examples",
    heading: "Worked examples",
    blurb: "Fit a distribution, analyse an RBD and plan a test, in Python or curl.",
    title: "API Examples — fit, analyse an RBD, plan a test | Reliafy",
    description:
      "Worked Reliafy API examples in Python and curl: fit a Weibull to censored failure times, analyse a reliability block diagram, and plan a reliability demonstration test.",
  },
  {
    slug: "cli",
    label: "Command line",
    heading: "The command line",
    blurb: "The reliafy command: sign in, call any tool, and the shortcuts.",
    title: "The reliafy Command Line — Reliafy API",
    description:
      "The reliafy command line, installed with pip install reliafy-client: sign in, call any tool action, fit a CSV, upload files, import RBDs and push data from a shell.",
  },
  {
    slug: "python",
    label: "Python client",
    heading: "The Python client",
    blurb: "reliafy-client: Client.call, files and data, and the 0.2 functions.",
    title: "reliafy-client — the Python Client for the Reliafy API",
    description:
      "The reliafy-client Python package: call any Reliafy tool from Python, upload datasets (and their measurements) and diagrams, push usage and failures, and the original 0.2 functions.",
  },
  {
    slug: "files",
    label: "Files and photos",
    heading: "Files and photos",
    blurb: "Uploads and photos: the calls that send bytes, on the API and CLI only.",
    title: "Uploading Files and Photos — Reliafy API",
    description:
      "Send files to Reliafy over the API: single-use upload links for datasets, RBD files and worksheets, their limits and errors, and photo uploads.",
  },
  {
    slug: "mcp",
    label: "Claude (MCP)",
    heading: "Use Reliafy from Claude (MCP)",
    blurb: "Connect Claude or another MCP client, and what every tool does.",
    title: "Use Reliafy from Claude (MCP) — Reliafy",
    description:
      "Connect Claude (claude.ai, the desktop and mobile apps, Claude Code) or any MCP client to Reliafy's remote MCP server: plans, setup, sending files, and what every tool does.",
  },
  {
    slug: "v1-routes",
    label: "Original routes",
    heading: "Original routes and ingest",
    blurb: "The first nine routes, data ingest and model import: still supported.",
    title: "Original API Routes and Ingest — Reliafy API",
    description:
      "Reliafy's original API routes (models, reliability, datasets, fitting, fleet forecasts, strategy calculators), the ingest routes for usage, measurements and failures, and model import.",
  },
];

/** A page's path: "" → "/api-docs", "cli" → "/api-docs/cli". */
export const apiDocsPath = (slug) => (slug ? `/api-docs/${slug}` : "/api-docs");

export function apiDocsPage(slug) {
  return API_DOCS_PAGES.find((p) => p.slug === (slug || "")) || API_DOCS_PAGES[0];
}

/** The pages before and after ``slug`` (null at either end). */
export function apiDocsNeighbours(slug) {
  const i = API_DOCS_PAGES.findIndex((p) => p.slug === (slug || ""));
  return {
    prev: i > 0 ? API_DOCS_PAGES[i - 1] : null,
    next: i >= 0 && i < API_DOCS_PAGES.length - 1 ? API_DOCS_PAGES[i + 1] : null,
  };
}

// Anchors on the old single page (/api-docs#mcp and so on), and where each
// now lives. Emails and posts already sent link to these.
const LEGACY_ANCHORS = {
  "getting-started": "/api-docs/authentication",
  tools: "/api-docs/tools",
  "tool-list": "/api-docs/tools#tool-list",
  cli: "/api-docs/cli",
  client: "/api-docs/python",
  http: "/api-docs/v1-routes",
  mcp: "/api-docs/mcp",
};

/** Where an old /api-docs#<hash> link goes now (hash with or without "#"), or null. */
export function legacyApiDocsTarget(hash) {
  const id = decodeURIComponent(String(hash || "").replace(/^#/, ""));
  return Object.prototype.hasOwnProperty.call(LEGACY_ANCHORS, id) ? LEGACY_ANCHORS[id] : null;
}

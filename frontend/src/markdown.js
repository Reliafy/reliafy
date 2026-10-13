// Markdown to HTML for the content pages (guides, reference, blog, learn,
// what's new), which reach the page through dangerouslySetInnerHTML. The
// bodies are repo files today; the HTML still goes through DOMPurify (as the
// Reliability Agent's does, agentMarkdown.js) so only plain document markup
// ever renders, wherever a body comes from in future.
//
// DOMPurify needs a DOM. The build-time prerender (Node, no DOM: see
// scripts/prerender.mjs) renders the bundled repo markdown unchanged; the
// browser then renders the sanitized HTML into #root (createRoot, not
// hydration), so what a visitor's page runs is always the sanitized form.
import { marked } from "marked";
import DOMPurify from "dompurify";

// `purify` is DOMPurify; a test passes a stand-in.
export function renderMarkdown(body, purify = DOMPurify) {
  const html = marked.parse(body || "", { breaks: false, gfm: true });
  return purify.isSupported ? purify.sanitize(html, { USE_PROFILES: { html: true } }) : html;
}

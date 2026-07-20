import { marked } from "marked";
import DOMPurify from "dompurify";

// Render the Reliability Agent's markdown output to sanitized HTML. Unlike the
// learn/blog markdown (trusted, authored), agent text is LLM-generated, so it is
// sanitized with DOMPurify before it ever reaches dangerouslySetInnerHTML — a
// prompt-injected <script>/<img onerror> must never run in the user's session.
// `breaks: true` so the model's single newlines render as line breaks.
export function renderAgentMarkdown(text) {
  const html = marked.parse(text || "", { gfm: true, breaks: true });
  return DOMPurify.sanitize(html, { USE_PROFILES: { html: true } });
}

import { Marked } from "marked";
import DOMPurify from "dompurify";

// The working behind a performance standard, written in Markdown and shown to
// everyone who can open the function. It is typed or uploaded by a person, so
// it is treated as untrusted: raw HTML in it is dropped before it is turned
// into markup, then the markup is cleaned against a short list of tags (no
// images, styles, forms or scripts) and a link may only be http, https or
// mailto. The preview in the editor uses the same function, so what is
// previewed is what is read. Tables and code sit in blocks that scroll
// inside the panel (CSS), never widening it.

export const BASIS_TAGS = [
  "p", "br", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "strong", "em", "del", "code", "pre", "blockquote",
  "hr", "table", "thead", "tbody", "tr", "th", "td", "a", "sup", "sub",
];
export const BASIS_ATTRS = ["href", "title", "align", "colspan", "rowspan", "start"];
export const BASIS_URI = /^(https?:|mailto:)/i;
export const BASIS_PURIFY = {
  ALLOWED_TAGS: BASIS_TAGS,
  ALLOWED_ATTR: BASIS_ATTRS,
  ALLOW_DATA_ATTR: false,
  ALLOWED_URI_REGEXP: BASIS_URI,
};

const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

// A marked of its own, so nothing here changes how the guides or the agent render.
const md = new Marked({ gfm: true, breaks: true });
md.use({
  renderer: {
    html: () => "", // raw HTML in the text is dropped, not cleaned
    image: ({ text }) => esc(text || ""), // no images: their alt text stays
    link({ href, title, tokens }) {
      const inner = this.parser.parseInline(tokens);
      if (!BASIS_URI.test(String(href || ""))) return inner; // the words without the link
      const t = title ? ` title="${esc(title)}"` : "";
      return `<a href="${esc(href)}"${t}>${inner}</a>`;
    },
  },
});

// Every link that survives opens in a new tab and tells the browser not to pass
// anything on (an afterSanitizeAttributes hook, on this module's own cleaner so
// the guides' and the agent's are untouched).
export function openLinksApart(node) {
  if (node?.tagName === "A" && node.hasAttribute?.("href")) {
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noopener noreferrer nofollow");
  }
}

let own;
function ownPurify() {
  if (own === undefined) {
    own = typeof window !== "undefined" ? DOMPurify(window) : DOMPurify;
    own.addHook?.("afterSanitizeAttributes", openLinksApart);
  }
  return own;
}

// The Markdown as clean HTML for dangerouslySetInnerHTML. Without a DOM (a
// build-time render) nothing is returned rather than markup that wasn't cleaned.
export function renderBasisMarkdown(text, purify = null) {
  const source = String(text || "");
  if (!source.trim()) return "";
  purify = purify || ownPurify();
  if (!purify?.isSupported) return "";
  return purify.sanitize(md.parse(source), BASIS_PURIFY);
}

// The first words as one plain line (for tooltips and the collapsed section),
// from the server's preview when the full text isn't there yet.
export function plainFirstLine(text, limit = 80) {
  const line = String(text || "")
    .split("\n").map((l) => l.trim())
    .find((l) => l && !l.startsWith("```") && !/^[-*_=|:\s]{3,}$/.test(l)) || "";
  const plain = line.replace(/^(#{1,6}\s+|>\s*|[-*+]\s+|\d+[.)]\s+)+/, "")
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1").replace(/\*\*|__|~~|[*`]/g, "").replace(/\s+/g, " ").trim();
  return plain.length > limit ? `${plain.slice(0, limit - 1).trimEnd()}…` : plain;
}

// The Admin page's Plan tab (AdminPlanTab.jsx): split a markdown document into
// its prose and its fenced ```mermaid blocks, so the prose goes through the
// app's markdown renderer (markdown.js) and each block through mermaid.
//
// Fences follow CommonMark: ``` or ~~~ (three or more), indented at most three
// spaces, closed by a fence of the same character at least as long; an
// unclosed fence runs to the end. A ```mermaid inside another fenced block
// (a ````markdown example, say) is that block's text, not a chart.
const OPEN = /^ {0,3}(`{3,}|~{3,})(.*)$/;

// [{ type: "markdown", text } | { type: "mermaid", code }], in order; empty
// prose between blocks is dropped.
export function splitMermaid(markdown) {
  const lines = (markdown || "").replace(/\r\n?/g, "\n").split("\n");
  const parts = [];
  let prose = [];
  const flush = () => {
    const text = prose.join("\n");
    if (text.trim()) parts.push({ type: "markdown", text });
    prose = [];
  };

  for (let i = 0; i < lines.length; i++) {
    const open = OPEN.exec(lines[i]);
    // A backtick fence's info string can't contain a backtick (CommonMark).
    if (!open || (open[1][0] === "`" && open[2].includes("`"))) {
      prose.push(lines[i]);
      continue;
    }
    const fence = open[1];
    const lang = open[2].trim().split(/\s+/)[0].toLowerCase();
    const close = new RegExp(`^ {0,3}${fence[0] === "`" ? "`" : "~"}{${fence.length},}\\s*$`);
    let end = i + 1;
    while (end < lines.length && !close.test(lines[end])) end++;
    const body = lines.slice(i + 1, end);
    if (lang === "mermaid") {
      flush();
      parts.push({ type: "mermaid", code: body.join("\n") });
    } else {
      prose.push(...lines.slice(i, end + 1));
    }
    i = end;
  }
  flush();
  return parts;
}

// The plan's own repository and commit from its stored `source`
// ("Owner/repo@<sha or ref>"), or null.
export function sourceRepo(source) {
  const m = /^([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+)@([A-Za-z0-9_.\/-]+)$/.exec((source || "").trim());
  if (!m || m[3].includes("..")) return null;
  return { owner: m[1], repo: m[2], ref: m[3] };
}

const SCHEME = /^[a-z][a-z0-9+.-]*:/i;

// A relative link's path inside the repo (the plan sits at its root):
// "./", "../" and a leading "/" resolved, the #fragment / ?query kept.
function repoPath(href) {
  const at = href.search(/[?#]/);
  const [path, rest] = at < 0 ? [href, ""] : [href.slice(0, at), href.slice(at)];
  const out = [];
  for (const seg of path.split("/")) {
    if (seg === "" || seg === ".") continue;
    if (seg === "..") out.pop();
    else out.push(seg);
  }
  return out.join("/") + rest;
}

// Links in the plan's rendered (sanitized) HTML. Absolute links (a scheme,
// "//host") and in-page "#anchors" are left alone. A relative link
// ("README.md", "docs/x.md") points into the plan's repository, which the app
// doesn't serve: with a GitHub source it goes to that file at that commit,
// in a new tab; without one it becomes plain text.
export function rewritePlanLinks(html, source) {
  const repo = sourceRepo(source);
  return (html || "").replace(/<a\b([^>]*)>([\s\S]*?)<\/a>/gi, (whole, attrs, text) => {
    const m = /\shref="([^"]*)"/i.exec(attrs);
    if (!m) return whole;
    const href = m[1];
    if (SCHEME.test(href) || href.startsWith("//") || href.startsWith("#")) return whole;
    const path = repoPath(href);
    if (!repo || !path || /^[?#]/.test(path)) return `<span class="plan-link-local">${text}</span>`;
    const url = `https://github.com/${repo.owner}/${repo.repo}/blob/${repo.ref}/${path}`;
    const rest = attrs.replace(m[0], "").replace(/\s(target|rel)="[^"]*"/gi, "");
    return `<a href="${url}"${rest} target="_blank" rel="noreferrer">${text}</a>`;
  });
}

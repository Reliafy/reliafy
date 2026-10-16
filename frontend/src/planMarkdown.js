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

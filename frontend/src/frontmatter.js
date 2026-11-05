// The content files' frontmatter, shared by every content layer (blog,
// updates, learn, guides, reference) and the build-time feeds. Pure: no
// import.meta.glob here, so `node --test` can import it.

// Minimal frontmatter parser: a leading `--- ... ---` block of `key: value`
// lines (values may be quoted). Enough for our fixed set of fields; we control
// the files, so we don't need a full YAML engine.
//
// One YAML form beyond that: a block scalar, for multi-line text such as a
// LinkedIn post (`linkedin:`). `key: |` takes the indented lines below it,
// with their common indentation removed and line breaks kept:
//
//   linkedin: |
//     First paragraph.
//
//     Second paragraph.
export function parseFrontmatter(raw) {
  const match = /^---\s*\r?\n([\s\S]*?)\r?\n---\s*\r?\n?([\s\S]*)$/.exec(raw);
  if (!match) return { meta: {}, body: raw };
  const meta = {};
  const lines = match[1].split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (/^\s/.test(line)) continue; // an indented line outside a block
    if (line.startsWith("#")) continue; // a comment for whoever edits the file
    const idx = line.indexOf(":");
    if (idx === -1) continue;
    const key = line.slice(0, idx).trim();
    let value = line.slice(idx + 1).trim();
    if (/^\|[-+]?$/.test(value)) {
      const block = [];
      while (i + 1 < lines.length && (lines[i + 1].trim() === "" || /^\s/.test(lines[i + 1]))) {
        block.push(lines[++i]);
      }
      const indents = block.filter((l) => l.trim()).map((l) => /^\s*/.exec(l)[0].length);
      const cut = indents.length ? Math.min(...indents) : 0;
      value = block.map((l) => l.slice(cut)).join("\n").replace(/\s+$/, "");
    } else {
      value = value.replace(/^["']|["']$/g, "");
    }
    if (key) meta[key] = value;
  }
  return { meta, body: match[2] };
}

// URL slug from the filename, dropping any leading YYYY-MM-DD- / YYYY-MM- date.
export function slugFromPath(path) {
  const name = path.split("/").pop().replace(/\.md$/, "");
  return name.replace(/^\d{4}-\d{2}(-\d{2})?-/, "");
}

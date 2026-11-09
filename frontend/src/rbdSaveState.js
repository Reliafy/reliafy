// Whether the diagram on the canvas differs from the one last saved (or
// opened): the full-screen editor shows it, since the page's title bar is out
// of sight there.

const round = (v) => (Number.isFinite(v) ? Math.round(v * 2) / 2 : v);

// What a save keeps, as a string to compare: blocks (place and settings),
// connections and the diagram's own settings. Selection, sizes and drag state
// are left out: they change without changing the diagram.
export function rbdSaveSnapshot({ nodes = [], edges = [], ...rest } = {}) {
  const ns = nodes.map((n) => ({
    id: n.id,
    type: n.type,
    x: round(n.position?.x),
    y: round(n.position?.y),
    parent: n.parentNode ?? n.parentId ?? null,
    data: n.data ?? null,
  }));
  const es = edges.map((e) => ({
    s: e.source,
    t: e.target,
    sh: e.sourceHandle ?? null,
    th: e.targetHandle ?? null,
    data: e.data ?? null,
  }));
  const settings = Object.keys(rest).sort().map((k) => [k, rest[k] ?? null]);
  try {
    return JSON.stringify({ ns, es, settings });
  } catch {
    // Something that can't be written as JSON: treat the diagram as changed.
    return String(Math.random());
  }
}

// The words for the status: { text, tone, title }. Tone is a hint for the
// styling only; the text says it.
export function rbdSaveStatus({ savedId, readOnly, dirty }) {
  if (!savedId) {
    return { text: "Not saved yet", tone: "todo", title: "This diagram hasn't been saved. Save keeps it." };
  }
  if (readOnly) {
    return dirty
      ? { text: "Unsaved changes", tone: "todo", title: "A sample or shared diagram: save a copy to keep your changes." }
      : { text: "Read only", tone: "plain", title: "A sample or shared diagram: save a copy to change it." };
  }
  return dirty
    ? { text: "Unsaved changes", tone: "todo", title: "Changed since the last save." }
    : { text: "Saved", tone: "ok", title: "No changes since the last save." };
}

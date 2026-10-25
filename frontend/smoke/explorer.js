// Shared by the Explorer's smoke specs (Operate › Assets › Explorer).

// The panel about the row picked. On a wide screen its heading (the way up,
// the name, the actions) and its tabs sit in the slim rows over the tree, the
// same on both tabs, and its page (the Summary) is the "Details" region beside
// the tree; on a phone the whole panel is that region.
export const details = (page) =>
  page.getByRole("region", { name: "Details" }).or(page.locator(".tt-headslot, .tt-tabslot"));

// Where the parts of the Explorer's frame are on screen, rounded to 0.1 px:
// the pane, the tree's title row (title, +, ⋯), the search box, the counts,
// the pinned branch's note in the column header (if any), the tree's column header, the tree's
// scroll area (its top, its scroll and the place of each row drawn on screen,
// by key), and the panel's heading and tabs.
export function frameOf(page) {
  return page.evaluate(() => {
    const r = (el) => {
      if (!el) return null;
      const b = el.getBoundingClientRect();
      const f = (v) => Math.round(v * 10) / 10;
      return { x: f(b.x), y: f(b.y), w: f(b.width), h: f(b.height) };
    };
    const q = (s) => document.querySelector(s);
    const sc = q(".tp-scroll");
    const top = sc ? sc.getBoundingClientRect().y : 0;
    const rows = {};
    for (const el of document.querySelectorAll(".tp-body > .tp-row")) {
      const b = el.getBoundingClientRect();
      if (b.y + 2 < top || b.y > innerHeight) continue;
      const tree = el.querySelector(".tt-tree") || el;
      const nm = el.querySelector(".tp-nm");
      rows[el.dataset.key] = { y: Math.round(b.y * 10) / 10, h: Math.round(b.height * 10) / 10, name: r(nm), w: r(tree).w, text: nm?.textContent || el.dataset.key };
    }
    return {
      boxes: {
        pane: r(q("aside.tp")),
        title: r(q(".tp-title")),
        add: r(q(".tp-add")),
        menu: r(q(".tm-trigger")),
        search: r(q(".tp-filter")),
        counts: r(q(".tp-status")),
        pinned: r(q(".tt-pinned")),
        column: r(q(".tt-head .tt-h-tree")),
        tree: sc ? { ...r(sc), w: null } : null, // its width grows to the table's on the RCM tab
        heading: r(q(".tt-headslot")),
        tabs: r(q(".tt-tabslot")),
        name: r(q(".tt-h1")) && { ...r(q(".tt-h1")), w: null }, // the name's own width follows the actions beside it
      },
      scrollTop: sc ? sc.scrollTop : null,
      selected: q(".tp-body [aria-selected=true]")?.dataset.key || null,
      rows,
      pageScroll: [scrollX, scrollY, document.documentElement.clientWidth],
    };
  });
}

// What moved between two frames, beyond `tol` px: each box (or "gone" /
// "appeared"), the tree's scroll, the window's scroll and layout width, the
// row picked, and the rows on screen just above it in both (up to the first
// row only one tab has). The RCM tab adds rows under positions: rows below the
// one picked may go down, and rows above RCM rows that come or go may shift,
// but the row picked stays exactly where it was, and so does every row with
// nothing added or taken away between it and the row picked. The one
// exception: with the tree scrolled to its top there's no room to keep them
// there, so they move by exactly the rows that came or went above them.
export function movedBetween(a, b, { tol = 1, sameScroll = false } = {}) {
  const out = [];
  for (const [k, A] of Object.entries(a.boxes)) {
    const B = b.boxes[k];
    if (!A && !B) continue;
    if (!A || !B) {
      out.push(`${k} ${A ? "gone" : "appeared"}`);
      continue;
    }
    for (const p of ["x", "y", "w", "h"]) {
      if (A[p] == null || B[p] == null) continue;
      if (Math.abs(A[p] - B[p]) > tol) out.push(`${k}.${p} ${A[p]} → ${B[p]}`);
    }
  }
  // The tree's scroll is the same on both tabs unless RCM rows come or go
  // above the row picked (then it moves by just those rows, keeping the row
  // picked in place: checked above and below). `sameScroll` asks for it exactly.
  if (sameScroll && Math.abs((a.scrollTop ?? 0) - (b.scrollTop ?? 0)) > tol) out.push(`tree scroll ${a.scrollTop} → ${b.scrollTop}`);
  if (a.pageScroll.join() !== b.pageScroll.join()) out.push(`page scroll/width ${a.pageScroll} → ${b.pageScroll}`);
  if (a.selected !== b.selected) out.push(`row picked ${a.selected} → ${b.selected}`);
  const upFrom = (f) => {
    const keys = Object.keys(f.rows).sort((x, y) => f.rows[x].y - f.rows[y].y);
    const i = keys.indexOf(f.selected);
    return i < 0 ? [] : keys.slice(0, i + 1).reverse();
  };
  const upA = upFrom(a);
  const upB = upFrom(b);
  let shift = 0;
  if ((b.scrollTop ?? 0) <= tol && a.rows[a.selected] && b.rows[b.selected]) {
    const onlyIn = (f, g, up) => up.filter((k) => !(k in g.rows)).length;
    shift = (onlyIn(b, a, upB) - onlyIn(a, b, upA)) * a.rows[a.selected].h;
  }
  if (a.selected && a.rows[a.selected] && !b.rows[a.selected]) out.push(`row picked “${a.rows[a.selected].text}” gone from view`);
  if (out.length || upA[0] !== upB[0]) out.push(`(rows above the one picked: ${upA.slice(0, 6).map((k) => a.rows[k].text).join(" ‹ ")} | ${upB.slice(0, 6).map((k) => b.rows[k].text).join(" ‹ ")})`);
  for (let i = 0; i < upA.length && upA[i] === upB[i]; i += 1) {
    const A = a.rows[upA[i]];
    const B = b.rows[upA[i]];
    const key = `“${A.text}”`;
    if (Math.abs(A.y + shift - B.y) > tol) out.push(`row ${key} y ${A.y} → ${B.y}${shift ? ` (${shift} expected)` : ""}`);
    if (Math.abs(A.h - B.h) > tol) out.push(`row ${key} h ${A.h} → ${B.h}`);
    if (Math.abs(A.w - B.w) > tol) out.push(`row ${key} tree width ${A.w} → ${B.w}`);
    if (A.name && B.name && (Math.abs(A.name.x - B.name.x) > tol || Math.abs(A.name.y + shift - B.name.y) > tol)) {
      out.push(`row ${key} name at ${A.name.x},${A.name.y} → ${B.name.x},${B.name.y}`);
    }
  }
  return out;
}

// Watch the frame on every animation frame for `ms` after a switch: the
// positions of the title, the search box, the tabs and the row picked, and how
// many rows are drawn. Returns a stop() that gives each one's values in order
// (a flash shows as a value that comes and goes).
export async function watchFrames(page, ms = 600) {
  await page.evaluate((ms) => {
    window.__steady = [];
    const t0 = performance.now();
    const y = (s) => {
      const e = document.querySelector(s);
      return e ? Math.round(e.getBoundingClientRect().y) : null;
    };
    const tick = () => {
      window.__steady.push({
        title: y(".tp-title"), search: y(".tp-filter"), tabs: y(".tt-tabslot"), tree: y(".tp-scroll"),
        picked: y(".tp-body [aria-selected=true] .tp-nm"),
        blank: document.querySelectorAll(".tp-body > .tp-row").length === 0,
      });
      if (performance.now() - t0 < ms) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }, ms);
  return async () => {
    await page.waitForTimeout(ms + 50);
    return page.evaluate(() => window.__steady);
  };
}

// The values each part of the frame took, frame by frame, with repeats left
// out: one value is steady, two is the switch itself, more is a flash.
export function flashes(frames, { tol = 1 } = {}) {
  const out = [];
  const same = (x, y) => x === y || (x != null && y != null && Math.abs(x - y) <= tol);
  for (const k of ["title", "search", "tabs", "tree", "picked"]) {
    const seen = [];
    for (const f of frames) if (!seen.length || !same(seen[seen.length - 1], f[k])) seen.push(f[k]);
    if (seen.length > 2) out.push(`${k}: ${seen.join(" → ")}`);
  }
  if (frames.some((f) => f.blank)) out.push("a frame with no rows drawn");
  return out;
}

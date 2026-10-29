import { useCallback, useEffect, useRef, useState } from "react";
import { dragSource, dropZones, planDrop, sourceWords, zoneAt } from "../rcmDrag.js";

// Dragging rows of the RCM tab's tree (a wide screen, a mouse or pen; never on
// a phone, where the row menus' Move to… does every move). Pointer events, not
// the browser's own drag and drop, so the page draws the cursor, the drop line
// and the tooltip itself and nothing on the page moves while dragging: the
// marks are outlines and inset lines (no row grows), the dragged count and the
// tooltip float over the page.
//
// A press on a row's tree cell (or a mode's Task cell, for its task) that
// moves 5 px starts a drag; Escape cancels it. Over a row the drop is worked
// out at once (rcmDrag.planDrop): what the tree knows is said at once; the
// rest is asked of the server with a dry run once the pointer rests on the
// row (150 ms), remembered per batch, so passing over rows sends nothing and
// coming back asks once. A drop the server hasn't answered yet goes ahead:
// the server checks it again and nothing is written if it refuses.
//
// `check(ops)` → {ok, notes} | {ok: false, reason}; `drop(src, plan, key)`
// does it; `say(text)` announces to screen readers.

const START = 5; // px moved before a press becomes a drag
const REST = 150; // ms the pointer rests on a row before the server is asked
const EDGE = 36; // px from the scroll area's top or bottom that scrolls it

export default function useRcmDrag({ whole, picked, enabled, check, drop, say, headH = 30 }) {
  const [drag, setDrag] = useState(null);
  const env = useRef({});
  env.current = { whole, picked, check, drop, say };
  const verdicts = useRef(new Map());
  // A new read of the RCM: what the server said may have changed.
  useEffect(() => { verdicts.current = new Map(); }, [whole]);
  const live = useRef(null);
  const cleanup = useRef(null);
  useEffect(() => () => cleanup.current?.(), []);

  const begin = useCallback((e, key, task = null) => {
    if (!enabled || e.button !== 0 || e.pointerType === "touch") return;
    if (e.target.closest("input, textarea, select, button, a, .tp-chev, .rw-info, [contenteditable='true']")) return;
    const src = dragSource(env.current.whole, key, { picked: env.current.picked, task });
    if (!src) return;
    const scroller = e.currentTarget.closest(".tp-scroll");
    const sx = e.clientX;
    const sy = e.clientY;
    const root = document.documentElement;
    let started = false;
    let at = { x: sx, y: sy };
    let rest = 0;
    let scroll = 0;
    let state = null;

    const verdictFor = (plan) => {
      const id = JSON.stringify(plan.ops);
      return { id, known: verdicts.current.get(id) };
    };
    const show = (next) => {
      state = next;
      live.current = next;
      root.classList.toggle("rcm-nodrop", !!next && next.verdict?.state === "no");
      setDrag(next);
    };
    const hit = () => {
      const el = document.elementFromPoint(at.x, at.y)?.closest(".tp-row[data-key]");
      const base = { src, x: at.x, y: at.y, words: sourceWords(env.current.whole, src) };
      if (!el || !scroller?.contains(el)) return show({ ...base, key: null });
      const key2 = el.dataset.key;
      const b = el.getBoundingClientRect();
      // The zone under the pointer, from what the row offers.
      const zone = zoneAt(dropZones(env.current.whole, src, key2).zones, (at.y - b.top) / Math.max(1, b.height));
      const plan = planDrop(env.current.whole, src, key2, zone || "into");
      if (plan.none) return show({ ...base, key: null });
      if (plan.refuse) return show({ ...base, key: key2, zone: "into", plan, verdict: { state: "no", text: plan.refuse } });
      const { id, known } = verdictFor(plan);
      const verdict = known ? (known.ok ? { state: "ok", text: plan.text, notes: known.notes } : { state: "no", text: known.reason })
        : { state: "checking", text: plan.text };
      show({ ...base, key: key2, zone, plan, verdict });
      if (!known) {
        clearTimeout(rest);
        rest = setTimeout(() => {
          Promise.resolve(env.current.check(plan.ops)).then((v) => {
            verdicts.current.set(id, v);
            if (state && state.plan && JSON.stringify(state.plan.ops) === id) {
              show({ ...state, verdict: v.ok ? { state: "ok", text: plan.text, notes: v.notes } : { state: "no", text: v.reason } });
            }
          }, () => {});
        }, REST);
      }
      return null;
    };
    // Near the scroll area's top or bottom edge, it scrolls (the rows under
    // the pointer change, so the drop is worked out again).
    const edgeScroll = () => {
      if (!scroller) return;
      const b = scroller.getBoundingClientRect();
      const top = b.top + headH;
      const dy = at.y < top + EDGE ? -Math.ceil((top + EDGE - at.y) / 4) : at.y > b.bottom - EDGE ? Math.ceil((at.y - b.bottom + EDGE) / 4) : 0;
      if (dy) {
        const was = scroller.scrollTop;
        scroller.scrollTop += dy;
        if (scroller.scrollTop !== was) hit();
      }
    };
    const move = (ev) => {
      at = { x: ev.clientX, y: ev.clientY };
      if (!started) {
        if (Math.hypot(at.x - sx, at.y - sy) < START) return;
        started = true;
        root.classList.add("rcm-dragging");
        window.getSelection?.()?.removeAllRanges?.();
        scroll = setInterval(edgeScroll, 30);
        env.current.say(`Dragging ${sourceWords(env.current.whole, src)}. Drop it on a row, or press Escape to cancel.`);
      }
      ev.preventDefault();
      hit();
    };
    const stop = () => {
      window.removeEventListener("pointermove", move, true);
      window.removeEventListener("pointerup", up, true);
      window.removeEventListener("pointercancel", cancel, true);
      window.removeEventListener("keydown", onKey, true);
      clearTimeout(rest);
      clearInterval(scroll);
      root.classList.remove("rcm-dragging", "rcm-nodrop");
      live.current = null;
      cleanup.current = null;
      setDrag(null);
    };
    // The click that ends a drag doesn't pick the row it ended on.
    const swallowClick = () => {
      const eat = (ev) => { ev.stopPropagation(); ev.preventDefault(); };
      window.addEventListener("click", eat, { capture: true, once: true });
      setTimeout(() => window.removeEventListener("click", eat, { capture: true }), 0);
    };
    const up = () => {
      const s = state;
      const was = started;
      stop();
      if (!was) return;
      swallowClick();
      if (!s?.key || !s.plan) return env.current.say("Not moved.");
      if (s.verdict?.state === "no") return env.current.drop(s.src, { refuse: s.verdict.text }, s.key);
      return env.current.drop(s.src, s.plan, s.key);
    };
    const cancel = () => {
      const was = started;
      stop();
      if (was) env.current.say("Not moved.");
    };
    const onKey = (ev) => {
      if (ev.key !== "Escape") return;
      ev.preventDefault();
      ev.stopPropagation();
      cancel();
    };
    window.addEventListener("pointermove", move, true);
    window.addEventListener("pointerup", up, true);
    window.addEventListener("pointercancel", cancel, true);
    window.addEventListener("keydown", onKey, true);
    cleanup.current = stop;
  }, [enabled, headH]);

  return { drag, begin };
}


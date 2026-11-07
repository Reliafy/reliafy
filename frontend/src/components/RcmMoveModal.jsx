import { useEffect, useMemo, useRef, useState } from "react";
import { dragSource, keptMoveTarget, moveOpenAtStart, moveSourceKey, moveTree, planMoveTo, sourceWords, visibleNodes } from "../rcmDrag.js";
import { tasksOf } from "../rcmWorksheet.js";
import { Field, FormModal } from "./MaintenanceParts.jsx";
import { Chevron, Highlight } from "./OutlineBits.jsx";
import { RowIcon } from "./TreePane.jsx";

// "Move to…" on the RCM tab, for every kind of row (a function, a performance
// standard, a functional failure, failure modes, a task): from a row's ⋯ menu
// or the details panel's ⋯. The way to move without dragging (the keyboard, a
// phone) and the easy way to move a long way.
//
// One picker: the asset tree with the RCM in it, as the Explorer shows it
// (the same names and icons), searchable and opened and closed as the tree
// is. Only the places that kind can go can be picked; the others are greyed,
// each with a short reason (its tooltip, and said under the tree when it's
// tapped or reached from the keyboard). Picking a place says what will
// happen, and the server is asked first (a dry run), so a move it would
// refuse says why before Move is pressed. Move runs the same batch a drop
// there does (the same checks, the same "what should its tasks count" choice,
// the same Undo).
//
// `src`: what moves (rcmDrag.dragSource), or `taskFrom`: a failure mode whose
// task moves (the task picked here when it has several). `check(ops)` →
// {ok, notes} | {ok: false, reason}; `onApply(src, plan, key)` does it (and
// throws with the reason when the server refuses).
export default function RcmMoveModal({ whole, src: given = null, taskFrom = null, check, onApply, onClose }) {
  const fromRow = taskFrom ? whole.rows.get(taskFrom) : null;
  const tasks = useMemo(() => (fromRow ? tasksOf(fromRow.ref).filter((t) => t.id) : []), [fromRow]);
  const [taskId, setTaskId] = useState(tasks[0]?.id || "");
  const src = useMemo(() => {
    if (!taskFrom) return given;
    const t = tasks.find((x) => x.id === taskId);
    return t ? dragSource(whole, taskFrom, { task: t }) : null;
  }, [given, taskFrom, tasks, taskId, whole]);
  const tree = useMemo(() => moveTree(whole, src), [whole, src]);
  const [open, setOpen] = useState(() => moveOpenAtStart(tree));
  const [query, setQuery] = useState("");
  const [to, setTo] = useState("");
  const [active, setActive] = useState(null); // the row with the keyboard focus (roving)
  const [note, setNote] = useState(null); // why a greyed row can't be picked (tapped or reached)
  // Another thing to move (another task picked): start afresh. The same thing
  // with the tree read again (a reload after the dialog opened): keep what's
  // open and the place picked while it's still there.
  const srcKey = moveSourceKey(src);
  const started = useRef(srcKey);
  useEffect(() => {
    if (started.current !== srcKey) {
      started.current = srcKey;
      setOpen(moveOpenAtStart(tree));
      setTo("");
      setNote(null);
    } else {
      setTo((t) => keptMoveTarget(tree, t));
    }
  }, [tree, srcKey]);
  const list = useMemo(() => visibleNodes(tree, { query, open }), [tree, query, open]);
  const at = list.find((n) => n.key === active) ? active : (list.find((n) => n.key === to) || list.find((n) => n.ok) || list[0])?.key;
  const plan = to && src ? planMoveTo(whole, src, to) : null;
  const [verdict, setVerdict] = useState(null);
  useEffect(() => {
    setVerdict(null);
    if (!plan?.ops) return undefined;
    let live = true;
    Promise.resolve(check(plan.ops)).then((v) => live && setVerdict(v), () => {});
    return () => {
      live = false;
    };
  }, [to, src]); // eslint-disable-line react-hooks/exhaustive-deps
  const box = useRef(null);
  // Opened (or another task picked): the list scrolled to where it is now, the
  // places around it in view. Only the list scrolls, never the page.
  useEffect(() => {
    const el = tree.here && box.current?.querySelector(`[data-key="${CSS.escape(tree.here)}"]`);
    if (el) box.current.scrollTop = Math.max(0, el.offsetTop - box.current.clientHeight / 3);
  }, [srcKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const focusRow = (key) => {
    setActive(key);
    requestAnimationFrame(() => box.current?.querySelector(`[data-key="${CSS.escape(key)}"]`)?.focus());
  };
  if (!src && !taskFrom) return null;
  const what = src ? sourceWords(whole, src) : "the task";
  const refused = plan?.refuse || (verdict && !verdict.ok ? verdict.reason : null);
  const toggle = (n, want = !open.has(n.key)) => setOpen((o) => {
    const next = new Set(o);
    if (want) next.add(n.key);
    else next.delete(n.key);
    return next;
  });
  const choose = (n) => {
    if (n.ok) {
      setTo(n.key);
      setNote(null);
    } else {
      setNote(`${n.name}: ${n.reason}`);
    }
  };
  const onKey = (e, n) => {
    const i = list.findIndex((x) => x.key === n.key);
    const go = (j) => { if (list[j]) { e.preventDefault(); focusRow(list[j].key); if (!list[j].ok) setNote(`${list[j].name}: ${list[j].reason}`); else setNote(null); } };
    if (e.key === "ArrowDown") go(i + 1);
    else if (e.key === "ArrowUp") go(i - 1);
    else if (e.key === "Home") go(0);
    else if (e.key === "End") go(list.length - 1);
    else if (e.key === "ArrowRight" && n.kids.length) {
      e.preventDefault();
      if (!n.open && !query.trim()) toggle(n, true);
      else go(i + 1);
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      if (n.open && n.kids.length && !query.trim()) toggle(n, false);
      else if (n.parent) focusRow(n.parent);
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      choose(n);
    }
  };
  return (
    <FormModal title={`Move ${what}`} submitLabel="Move" pendingLabel="Moving…" onClose={onClose}
               canSubmit={!!plan?.ops && !refused}
               onSubmit={async () => {
                 await onApply(src, plan, to);
                 onClose();
               }}>
      {taskFrom && tasks.length > 1 && (
        <Field label="Which task?">
          <select value={taskId} onChange={(e) => setTaskId(e.target.value)}>
            {tasks.map((t) => <option key={t.id} value={t.id}>{t.name || t.text}</option>)}
          </select>
        </Field>
      )}
      <Field label="Find a place">
        <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Position, function or failure"
               aria-label="Find a place" />
      </Field>
      <ul ref={box} className="rcm-move-tree" role="tree" aria-label="Where it goes">
        {list.map((n) => {
          const picked = n.key === to;
          return (
            <li key={n.key} data-key={n.key} role="treeitem" aria-level={n.depth + 1} aria-selected={picked}
                aria-expanded={n.kids.length ? n.open : undefined} aria-disabled={n.ok ? undefined : "true"}
                aria-description={n.ok ? undefined : n.reason} title={n.ok ? undefined : n.reason}
                tabIndex={n.key === at ? 0 : -1}
                className={"rcm-mt-row" + (n.ok ? "" : " no") + (picked ? " picked" : "")}
                style={{ paddingLeft: 4 + Math.min(n.depth, 12) * 16 }}
                onKeyDown={(e) => onKey(e, n)}
                onFocus={() => setActive(n.key)}
                onClick={() => { setActive(n.key); choose(n); }}>
              {n.kids.length ? (
                <button type="button" tabIndex={-1} className={"rcm-mt-arrow" + (n.open ? " open" : "")} aria-hidden="true"
                        disabled={!!query.trim()}
                        onClick={(e) => { e.stopPropagation(); toggle(n); }}><Chevron /></button>
              ) : <span className="rcm-mt-arrow" aria-hidden="true" />}
              <RowIcon r={{ type: n.type, ref: { item: n.fitted } }} />
              <span className="rcm-mt-name"><Highlight text={n.name} query={query} /></span>
              {n.here && <span className="rcm-mt-here">here now</span>}
            </li>
          );
        })}
      </ul>
      {!list.length && <p className="lib-date">{tree.roots.length ? "Nothing matches that." : "There's nowhere else for it to go yet."}</p>}
      <p className={"rcm-move-say" + (refused || note ? " no" : "")} role="status" aria-live="polite">
        {note ? `It can't go there. ${note}`
          : !to ? "Pick where it goes. Greyed places say why they can't be picked. You can undo the move afterwards."
            : refused ? `It can't go there: ${refused}`
              : `${String(plan?.text || "").replace(/\.?$/, ".")}${verdict?.notes?.length ? ` ${verdict.notes.join(" ")}` : ""}${verdict ? "" : " (checking…)"}`}
      </p>
    </FormModal>
  );
}

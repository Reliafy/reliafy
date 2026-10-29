import { useEffect, useMemo, useState } from "react";
import { dragSource, moveChoices, planDrop, sourceWords } from "../rcmDrag.js";
import { tasksOf } from "../rcmWorksheet.js";
import { Field, FormModal } from "./MaintenanceParts.jsx";

// "Move to…" from a row's menu on the RCM tab: every move a drag can make,
// for the keyboard and a phone (where there's no dragging). A list of the
// places it can go, by position (filtered as you type); picking one says
// what will happen, and the server is asked first (a dry run), so a move it
// would refuse says why before Move is pressed. The move is one batch, as a
// drop is, and can be undone the same way.
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
  const groups = useMemo(() => moveChoices(whole, src), [whole, src]);
  const [query, setQuery] = useState("");
  const [to, setTo] = useState("");
  const shown = useMemo(() => {
    const t = query.trim().toLowerCase();
    if (!t) return groups;
    return groups.map((g) => (g.name.toLowerCase().includes(t) ? g : { ...g, items: g.items.filter((i) => i.label.toLowerCase().includes(t)) }))
      .filter((g) => g.items.length);
  }, [groups, query]);
  const plan = to && src ? planDrop(whole, src, to, "into") : null;
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
  if (!src && !taskFrom) return null;
  const what = src ? sourceWords(whole, src) : "the task";
  const refused = plan?.refuse || (verdict && !verdict.ok ? verdict.reason : null);
  return (
    <FormModal title={`Move ${what}`} submitLabel="Move" pendingLabel="Moving…" onClose={onClose}
               canSubmit={!!plan?.ops && !refused}
               onSubmit={async () => {
                 await onApply(src, plan, to);
                 onClose();
               }}>
      {taskFrom && tasks.length > 1 && (
        <Field label="Which task?">
          <select value={taskId} onChange={(e) => { setTaskId(e.target.value); setTo(""); }}>
            {tasks.map((t) => <option key={t.id} value={t.id}>{t.name || t.text}</option>)}
          </select>
        </Field>
      )}
      <Field label="Find a place">
        <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Position, function or failure"
               aria-label="Filter the places it can go" />
      </Field>
      <Field label="Move it to">
        <select className="rcm-move-list" size={Math.min(12, Math.max(4, shown.reduce((n, g) => n + g.items.length + (src?.kind === "fn" ? 0 : 1), 0)))}
                value={to} onChange={(e) => setTo(e.target.value)} aria-label="Where it goes">
          {/* A function goes on a position: the positions, indented as in the tree. */}
          {src?.kind === "fn" ? shown.map((g) => (
            <option key={g.id} value={g.items[0].key}>{"\u00a0\u00a0".repeat(g.depth)}{g.name}</option>
          )) : shown.map((g) => (
            <optgroup key={g.id} label={`${"\u00a0\u00a0".repeat(g.depth)}${g.name}`}>
              {g.items.map((i) => <option key={i.key} value={i.key}>{i.label}</option>)}
            </optgroup>
          ))}
        </select>
      </Field>
      {!shown.length && <p className="lib-date">{groups.length ? "Nothing matches that." : "There's nowhere else for it to go yet."}</p>}
      <p className={"rcm-move-say" + (refused ? " no" : "")} role="status" aria-live="polite">
        {!to ? "Pick where it goes. You can undo the move afterwards."
          : refused ? `It can't go there: ${refused}`
          : `${String(plan?.text || "").replace(/\.?$/, ".")}${verdict?.notes?.length ? ` ${verdict.notes.join(" ")}` : ""}${verdict ? "" : " (checking…)"}`}
      </p>
    </FormModal>
  );
}

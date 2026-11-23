import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { addPackageTask, getTaskTable, listPackages } from "../api.js";
import Chip from "./ui/Chip.jsx";
import Select from "./Select.jsx";
import TablePane from "./TablePane.jsx";
import MaintenanceTask, { TradeRates } from "./MaintenanceTask.jsx";
import RbdTaskUses from "./RbdTaskUses.jsx";
import { CloseIcon, ExpandIcon, ShrinkIcon } from "./icons.jsx";
import { useSendOnce } from "./MaintenanceParts.jsx";
import { AddPackageDialog, PackageTasks, PackageView, overdueNote } from "./LsaPanel.jsx";
import { latestOnly } from "../explorerMissions.js";
import { PKG_REF_TYPE, PKG_TYPE, levelDueCell, packageCell, packageWhere, rankPackages, taskCell, visitFor } from "../explorerTasks.js";
import { cadenceWords, ordinal, packageScope, taskOnText } from "../lsaTab.js";
import "./LsaPanel.css";
import "./TaskTreeTable.css";

// The Explorer's Maintenance tab is the tree with each position's tasks in it (explorerTasks.js),
// like the Modelling and Missions tabs: the read of every task in the asset opened, each task
// row's cells and its phone line, and a task's details beside the table. No forecasts here (Derryn,
// 23 Nov 2026): the quick one is Decisions › Forecasts › Spares forecast.

export { TASK_COLUMNS, TASK_TREE_HEAD } from "../explorerTasks.js";

// Every task in the asset opened (`within`: its top row's id), read when the tab is on (and again
// on `load`): one read, the server's roll-up. The last read asked for is the one shown.
// `kind`: the top row's type ("pos" or "loc"), so the read names it as a position or a place too.
// `packages`: the work packages on that asset too (listPackages: the ones there or holding a task
// there), each drawn at the meeting point of its tasks; read again with the tasks.
export function useTreeTasks({ on, within = null, kind = "pos", packages = false }) {
  const [state, setState] = useState({ tasks: null, packages: null, truncated: false, total: 0, error: null });
  const asked = useRef(null);
  if (!asked.current) asked.current = latestOnly();
  const load = useCallback(() => {
    if (!within) {
      setState({ tasks: [], packages: [], truncated: false, total: 0, error: "Open one asset to see its tasks." });
      return Promise.resolve();
    }
    const latest = asked.current();
    const scope = { [kind === "loc" ? "location_id" : "position_id"]: within };
    // A package list that won't load leaves the tasks shown (their Packaged cells still say).
    const pkgs = packages ? listPackages(scope).then((d) => d.packages || []).catch(() => null) : Promise.resolve(null);
    return Promise.all([getTaskTable({ ...scope, within }), pkgs])
      .then(([d, p]) => latest() && setState({ tasks: d.tasks || [], packages: p, truncated: !!d.truncated, total: d.total || 0, error: null }))
      .catch((e) => latest() && setState((s) => ({ ...s, error: e.message })));
  }, [within, kind, packages]);
  useEffect(() => { if (on) load(); }, [on, load]);
  return { ...state, load };
}

// A Next due cell: a date ("5 Dec 2026", overdue in red), the reading it falls due at ("at
// 1,250 h"), or a dash with why in its tooltip (never a date worked out from today).
function DueCell({ c }) {
  if (c.blank || !c.words) return <span className="rw-blank" title={c.title || undefined}>—</span>;
  return <span className={"ml-num" + (c.overdue ? " pk-overdue" : "")} title={c.title || undefined}>{c.words}{c.overdue ? " · overdue" : ""}</span>;
}

// A level's Next due: the soonest at and below it (rollupLead: its cell, before the roll-up).
export const levelDue = (r) => <DueCell c={levelDueCell(r)} />;

// One cell of a task row (r.ref.task: a task-table row). The Packaged cell is a link to the
// package (`onPackage`), opened in Maintenance › Packages.
export function TaskCell({ r, col, onPackage = null }) {
  const t = r.ref.task;
  const c = taskCell(t, col.id);
  if (col.id === "package" && t.package && onPackage) {
    return (
      <button type="button" className="link mt-pkg-link" title={c.title} onDoubleClick={(e) => e.stopPropagation()}
              onClick={(e) => { e.stopPropagation(); onPackage(t.package); }}>{c.text}</button>
    );
  }
  if (col.id === "due") return <DueCell c={c} />;
  if (col.id === "kind") {
    return c.text ? <Chip tone={t.on_event ? "neutral" : "accent"} className="pk-kind" title={c.text}>{c.text}</Chip> : null;
  }
  if (!c.text) return c.blank ? <span className="rw-blank" title={c.title || undefined}>{c.blank}</span> : null;
  return <span className={col.num ? "ml-num" : "ml-src"} title={c.title || c.text}>{c.text}</span>;
}

// A package's row (at the meeting point of its tasks): how often, its next visit, what a visit
// costs, its trade, how many tasks; a reference to one of its tasks: the task's own cells, and
// where it is in the Packaged column (it's under its own position too).
export function PackageCell({ r, col }) {
  if (r.type === PKG_REF_TYPE) {
    if (col.id === "package") return <span className="ml-src" title={`${r.ref.name} is on ${r.ref.on}: it shows there too`}>On {r.ref.on}</span>;
    if (col.id === "trade" || col.id === "from" || col.id === "kind") return null;
    return <TaskCell r={r} col={col} />;
  }
  const c = packageCell(r, col.id);
  if (col.id === "due") return <DueCell c={c} />;
  if (col.id === "kind") return c.text ? <Chip tone="warning" className="pk-kind">{c.text}</Chip> : <Chip tone="neutral" className="pk-kind" title="Tasks done together on one visit">Package</Chip>;
  if (!c.text) return c.blank ? <span className="rw-blank" title={c.title || undefined}>{c.blank}</span> : null;
  return <span className={col.num ? "ml-num" : "ml-src"} title={c.title || c.text}>{c.text}</span>;
}

// A row's second line on a phone: a task's interval, next due and cost; a level's roll-up.
export function taskPhoneRow(r, rollup) {
  if (r.type === PKG_TYPE) {
    const due = packageCell(r, "due");
    return { line: [packageCell(r, "interval").text, packageCell(r, "package").text, packageCell(r, "cost").text].filter(Boolean).join(" · "),
      status: <Chip tone="neutral" title={due.title || undefined}>{due.words ? `Next ${due.words}` : "Package"}</Chip> };
  }
  if (r.type === PKG_REF_TYPE) return { line: `On ${r.ref.on}`, status: null };
  if (r.type !== "mtask") {
    const due = levelDueCell(r);
    return { line: [rollup, due.words ? `next ${due.words}` : null].filter(Boolean).join(" · "), status: null };
  }
  const t = r.ref.task;
  const due = taskCell(t, "due");
  const cost = taskCell(t, "cost");
  return {
    line: [taskCell(t, "interval").text, cost.text ? `${cost.text} each time` : null, t.package?.name].filter(Boolean).join(" · "),
    status: due.words ? <Chip tone={due.overdue ? "danger" : "neutral"} title={due.title || undefined}>{due.overdue ? "Overdue " : "Due "}{due.words}</Chip> : null,
  };
}

// Beside the table: a task opened (its form, MaintenanceTask.jsx), a new task on a level, or the
// trade rates. `holder`: the position or place row the task is on (or is being added to);
// `taskName`: the opened task's name from its row, the panel's title until the task has loaded.
// The head (where it is, Expand or Back to table, Close) is the same as the Models and RCM panels';
// the task's form draws its own title, body and footer under it, so its Save sits in the footer.
// `needs`: open the form's What it needs section (?needs=1: an old address, or a link to it).
export function TaskSide({ holder, taskId = null, taskName = "", rates = false, needs = false, phone, expanded = false, onExpand, onCollapse, headingRef, onClose, onDone, onChanged, onOptimise = null }) {
  const title = rates ? "Trade rates" : taskId ? (taskName || "Maintenance task") : "Add a task";
  const head = (
    <div className="rw-panel-head">
      <div className="rw-panel-kind">{rates || taskId ? (holder?.ref?.name || "Maintenance task") : "New maintenance task"}</div>
      <div className="rw-panel-btns">
        {!phone && taskId && onExpand && (expanded ? (
          <button type="button" className="ghost sm rw-x" onClick={onCollapse} title="Show the table again, with these details beside it (Esc)" aria-label="Back to table"><ShrinkIcon /></button>
        ) : (
          <button type="button" className="ghost sm rw-x" onClick={onExpand} title="Show these details across the table, the tree kept beside them" aria-label="Expand the details"><ExpandIcon /></button>
        ))}
        <button type="button" className="ghost sm rw-x" onClick={onClose} aria-label={`Close ${rates ? "trade rates" : taskId ? "the task" : "add a task"}`} title="Close (Esc)"><CloseIcon /></button>
      </div>
    </div>
  );
  return (
    <aside className={"rw-panel mt-panel mt-task-panel" + (phone ? " sheet" : "") + (expanded ? " is-expanded" : "")} aria-label={title}
           onKeyDown={(e) => {
             if (e.key !== "Escape" || e.defaultPrevented || e.target.closest("input, textarea, select")) return;
             e.stopPropagation();
             if (expanded && onCollapse) onCollapse(); else onClose();
           }}>
      {rates ? (
        <>
          <div className="rw-panel-top">
            {head}
            <h2 className="rw-panel-title" tabIndex={-1} ref={headingRef}>{title}</h2>
          </div>
          <div className="rw-pbody pk-panel">
            <TradeRates onChanged={onChanged} />
          </div>
        </>
      ) : holder && (
        <MaintenanceTask key={`${holder.key}:${taskId || "new"}`} row={holder} taskId={taskId} taskName={taskName}
                         head={head} headingRef={headingRef} onBack={onClose} onDone={onDone} onOptimise={taskId ? onOptimise : null} needsOpen={needs}
                         uses={taskId ? <RbdTaskUses taskIds={[taskId]} /> : null} />
      )}
    </aside>
  );
}

// A package opened (its row, or a task's Packaged cell): its tasks, visits, what each visit needs
// and the parts for its next visit, beside the table (?mpkg=). The head is the other panels'.
export function PackageSide({ id, name = "", where = "", at = null, today, phone, headingRef, onClose, onOpen, onChanged }) {
  return (
    <aside className={"rw-panel mt-panel mt-task-panel" + (phone ? " sheet" : "")} aria-label={name || "Work package"}
           onKeyDown={(e) => {
             if (e.key !== "Escape" || e.defaultPrevented || e.target.closest("input, textarea, select")) return;
             e.stopPropagation();
             onClose();
           }}>
      <div className="rw-panel-top">
        <div className="rw-panel-head">
          <div className="rw-panel-kind" title={where || undefined}>Work package</div>
          <div className="rw-panel-btns">
            <button type="button" className="ghost sm rw-x" onClick={onClose} aria-label="Close the package" title="Close (Esc)"><CloseIcon /></button>
          </div>
        </div>
      </div>
      <div className="rw-pbody pk-panel">
        <PackageView key={id} id={id} today={today} onOpen={onOpen} onChanged={onChanged} headingRef={headingRef} at={at} where={where} />
      </div>
    </aside>
  );
}

// Package the tasks… on a level: drafts packages from every task there and below in none, by how
// often and by trade (what was the LSA tab's), in the table area.
export function DraftPackagesPane({ holder, phone, headingRef, onClose, onDone }) {
  return (
    <TablePane title="Package the tasks" subject={holder.ref?.name || ""} phone={phone} headingRef={headingRef} onClose={onClose}
               closeLabel="Close package the tasks">
      <div className="td-tab-page pk-panel rw mt-pkg-pane">
        <PackageTasks scope={packageScope(holder)} where={`at ${holder.ref?.name || "this level"} and below`} onBack={onClose} onDone={onDone} />
      </div>
    </TablePane>
  );
}

// A form in the table pane (Package…, Add to package…): the same props as FormModal, its buttons at
// the foot of the pane rather than a dialog's. Sent once; a refusal shows over the form.
export function PaneForm({ submitLabel, pendingLabel = "Saving…", onClose, onSubmit, canSubmit = true, children }) {
  const { busy, error, submit } = useSendOnce(onSubmit, canSubmit);
  return (
    <form className="mt-pane-form" onSubmit={(e) => { e.preventDefault(); submit(); }}>
      {error && <div className="card error" role="alert">{error}</div>}
      <div className="rcm-form">{children}</div>
      <div className="mt-pane-foot">
        <button type="button" className="secondary" onClick={onClose} disabled={busy}>Cancel</button>
        <button type="submit" disabled={busy || !canSubmit} aria-busy={busy || undefined}>{busy ? pendingLabel : submitLabel}</button>
      </div>
    </form>
  );
}

const plural = (n, one, many = `${one}s`) => `${n.toLocaleString("en-AU")} ${n === 1 ? one : many}`;

// Package… and Add to package… on the tasks selected (Derryn, 22 Nov 2026: "select multiple rows
// in the table and right click and 'package'"; "right click a task and 'add to package'"), in the
// table area with the tree kept beside it. `kind`: "new" or "add"; `tasks`: their task-table rows
// (the ones already in a package or that can't join one are left out and said so); `holder`: the
// lowest position or place over them all, where a new package goes; `asset`: the asset's top row,
// whose packages Add to package… offers.
export function PackagePane({ kind, tasks, holder, asset, display, phone, headingRef, onClose, onDone }) {
  const free = tasks.filter((t) => !t.package && !t.why_not);
  const left = tasks.length - free.length;
  const title = kind === "new" ? "Package" : "Add to package";
  const where = holder?.ref?.name ? `on ${holder.ref.name}` : "here";
  return (
    <TablePane title={title} subject={`${plural(free.length, "task")}${holder?.ref?.name ? ` · ${holder.ref.name}` : ""}`} phone={phone}
               headingRef={headingRef} onClose={onClose} closeLabel={`Close ${title.toLowerCase()}`}>
      <div className="td-tab-page pk-panel rw mt-pkg-pane">
        {left > 0 && (
          <p className="lib-date" role="note">
            {plural(left, "task")} selected {left === 1 ? "isn't" : "aren't"} included: {tasks.filter((t) => t.package || t.why_not)
              .map((t) => `${t.name} (${t.package ? `in ${t.package.name}` : t.why_not})`).join("; ")}.
          </p>
        )}
        {!free.length ? <p className="lib-date">None of the tasks selected can go in a package.</p>
          : kind === "new" ? (
            <AddPackageDialog key={free.map((t) => t.id).join(",")} scope={packageScope(holder)} where={where} tasks={free} named
                              Frame={PaneForm} onClose={onClose} onDone={(text, id) => onDone(text, id)} />
          ) : (
            <AddToPackage key={free.map((t) => t.id).join(",")} asset={asset} tasks={free} display={display} onClose={onClose} onDone={onDone} />
          )}
      </div>
    </TablePane>
  );
}

const RULES = [1, 2, 3, 4, 5, 6, 8, 10, 12];

// The packages on this asset, the ones that can take every task first (the same interval before
// the others); one that can't says why, greyed. Each task comes on every visit, or on every Nth
// when its interval is a whole multiple of the package's; each can be changed.
function AddToPackage({ asset, tasks, display, onClose, onDone }) {
  const [list, setList] = useState(null);
  const [error, setError] = useState(null);
  const [pick, setPick] = useState(null);
  const [rules, setRules] = useState({});
  const scope = useMemo(() => packageScope(asset), [asset]);
  useEffect(() => {
    let live = true;
    listPackages(scope || {}).then((d) => live && setList(d.packages || [])).catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [scope]);
  const ranked = useMemo(() => (list ? rankPackages(list, tasks, display) : null), [list, tasks, display]);
  const chosen = ranked?.find((x) => x.pkg.id === pick && !x.why) || null;
  // The first that fits is picked to start with.
  useEffect(() => {
    if (ranked && pick == null) {
      const first = ranked.find((x) => !x.why);
      if (first) setPick(first.pkg.id);
    }
  }, [ranked]); // eslint-disable-line react-hooks/exhaustive-deps
  // A package picked: each task's visits from its interval against the package's.
  useEffect(() => {
    if (chosen) setRules(Object.fromEntries(tasks.map((t) => [t.id, visitFor(chosen.pkg, t).every_nth || 1])));
  }, [chosen?.pkg.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const submit = async () => {
    for (const t of tasks) {
      const n = Number(rules[t.id]) || 1;
      await addPackageTask(chosen.pkg.id, { task_id: t.id, ...(n > 1 ? { visit_rule: "nth", every_nth: n } : { visit_rule: "every" }) });
    }
    onDone(`Added ${plural(tasks.length, "task")} to ${chosen.pkg.name}.`, chosen.pkg.id);
  };
  const fits = ranked ? ranked.filter((x) => !x.why).length : 0;
  return (
    <PaneForm submitLabel="Add" pendingLabel="Adding…" canSubmit={!!chosen} onClose={onClose} onSubmit={submit}>
      <p className="lib-date">{tasks.map(taskOnText).join(", ")}.</p>
      {tasks.some((t) => t.overdue) && <p className="maint-overdue" role="status">{overdueNote(tasks.filter((t) => t.overdue).length)}</p>}
      {error && <div className="card error">Couldn&apos;t load the packages: {error}</div>}
      {!ranked && !error && <p className="lib-date">Loading…</p>}
      {ranked && ranked.length === 0 && <p className="lib-date">No packages on this asset yet: use Package… to make one.</p>}
      {ranked && ranked.length > 0 && (
        <>
          {!fits && <p className="lib-date" role="note">None of the packages here can take {tasks.length === 1 ? "this task" : "these tasks"}: each says why. Use Package… to make one that can.</p>}
          <ul className="pk-pick mt-pk-pick" role="radiogroup" aria-label="Packages">
            {ranked.map(({ pkg, why }) => (
              <li key={pkg.id} className={why ? "is-off" : undefined}>
                <label className="pk-check">
                  <input type="radio" name="mt-pk-target" checked={pick === pkg.id} disabled={!!why} onChange={() => setPick(pkg.id)}
                         aria-describedby={why ? `mt-pk-why-${pkg.id}` : undefined} />
                  <span>
                    {pkg.parent ? "↳ " : ""}{pkg.name}{" "}
                    <span className="lib-date">· {cadenceWords(pkg)}{pkg.trade ? ` · ${pkg.trade}` : ""}{pkg.subject?.name ? ` · on ${pkg.subject.name}` : ""} · {plural(pkg.task_count || 0, "task")}</span>
                    {why && <span className="mt-pk-why" id={`mt-pk-why-${pkg.id}`}>{why}</span>}
                  </span>
                </label>
              </li>
            ))}
          </ul>
        </>
      )}
      {chosen && (
        <fieldset className="mt-pk-rules">
          <legend>On its visits</legend>
          {tasks.map((t) => (
            <label key={t.id} className="mt-pk-rule">
              <span>{t.name} <span className="lib-date">· {taskCell(t, "interval").text || "no interval"}</span></span>
              <Select value={String(rules[t.id] || 1)} onChange={(v) => setRules((r) => ({ ...r, [t.id]: Number(v) }))}
                      ariaLabel={`${t.name}: on which visits`}
                      options={[...new Set([...RULES, rules[t.id] || 1])].sort((a, b) => a - b)
                        .map((n) => ({ value: String(n), label: n === 1 ? "Every visit" : `Every ${ordinal(n)} visit` }))} />
            </label>
          ))}
        </fieldset>
      )}
    </PaneForm>
  );
}

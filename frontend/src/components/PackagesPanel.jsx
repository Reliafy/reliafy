import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import {
  addPackageTask, changePackage, createPackage, createPackages, getPackage, listPackages, proposePackages, removePackageTask,
} from "../api.js";
import { Field, FormModal, fmtDate } from "./MaintenanceParts.jsx";
import Chip from "./ui/Chip.jsx";
import MoreMenu from "./ui/MoreMenu.jsx";
import { ShowMe } from "./SectionPage.jsx";
import { useConfirm } from "./ConfirmProvider.jsx";
import { usePanelMenu } from "../panelMenu.js";
import {
  WEEKDAYS, cadenceWords, dayName, daysLate, freeTasks, lateText, packageRows, packageScope, packageSubline,
  proposalBatch, proposalProblem, proposalRows, renameRow, toggleRow, visitRuleText,
} from "../packagesTab.js";
import "../views/Maintenance.css";
import "./PackagesPanel.css";

// The Packages tab of the Explorer's panel (Assets › Explorer, ?tab=packages):
// the work packages planned at the picked position or place and inside it, or
// holding a task there. A package bundles tasks done on one visit (the weekly
// check of an area), so each visit raises one work order; a layer adds lines
// on some of its visits (the first Saturday of the month). Worst first: late,
// then the soonest visit. A package opens in the same tab (?package=, with a
// back link): its tasks, its layers, and its ⋯ (Pause…, Resume, Retire…, Add
// tasks…). The heading's "…" has Package the tasks… (drafts from the tasks
// here that are in no package, grouped by how often and by trade, the longer
// ones as layers on the weekly visit) and Add a package… (by hand).

const HELP = { guide: "work-packages" };

function usePackageQuery() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();
  const set = (value) => {
    const next = new URLSearchParams(location.search);
    if (value) next.set("package", value);
    else next.delete("package");
    navigate(`${location.pathname}?${next}${location.hash}`, { replace: true, state: location.state });
  };
  return { open: params.get("package") || null, setOpen: set };
}

const plural = (n, one, many = `${one}s`) => `${n.toLocaleString("en-AU")} ${n === 1 ? one : many}`;

function StatusChips({ pkg, today }) {
  const late = daysLate(pkg, today);
  return (
    <>
      {late > 0 && <Chip tone="danger" className="pk-late">{lateText(late)}</Chip>}
      {pkg.status === "paused" && (
        <Chip tone="warning" title={pkg.pause?.reason || undefined}>
          {pkg.pause?.until ? `Paused until ${fmtDate(pkg.pause.until)}` : "Paused, no return date"}
        </Chip>
      )}
      {pkg.status === "retired" && <Chip>Retired</Chip>}
      {pkg.flags?.includes("past_return_date") && <Chip tone="warning" title="Back by itself on its return date: Resume to acknowledge it">Back from pause</Chip>}
      {pkg.season && !pkg.in_season && <Chip title={pkg.season.text}>Out of season</Chip>}
    </>
  );
}

function WhenCell({ pkg }) {
  const wo = pkg.open_work_order;
  return (
    <span className="pk-when">
      {wo ? (
        <Link to={`/maintenance/work-orders/${wo.id}`} onClick={(e) => e.stopPropagation()}
              title={`Work order #${wo.number} is open for the visit on ${fmtDate(wo.visit_on)}`}>
          #{wo.number} · {fmtDate(wo.visit_on)}
        </Link>
      ) : pkg.next_visit ? (
        <span title="The next visit">Next {fmtDate(pkg.next_visit)}</span>
      ) : <span className="lib-date">No visit due</span>}
    </span>
  );
}

// ---- dialogs ----------------------------------------------------------------------------

// Package the tasks…: drafts from the tasks here and below in no package, the
// longer cadences as layers on the shortest, visiting on the weekday picked.
export function PackageTasksDialog({ scope, where, onClose, onDone }) {
  const [weekday, setWeekday] = useState("saturday");
  const [tolerance, setTolerance] = useState("1");
  const [state, setState] = useState({ weekday: null, data: null, error: null });
  const [rows, setRows] = useState([]);
  useEffect(() => {
    let live = true;
    proposePackages(scope, weekday)
      .then((data) => { if (live) { setState({ weekday, data, error: null }); setRows(proposalRows(data.drafts)); } })
      .catch((e) => live && setState({ weekday, data: null, error: e.message }));
    return () => { live = false; };
  }, [scope, weekday]);
  const data = state.weekday === weekday ? state.data : null;
  const problem = data ? proposalProblem(rows) : "Loading…";
  const leftOut = data?.left_out || [];
  const submit = async () => {
    const out = await createPackages(proposalBatch(rows, { tolerance }));
    onDone(`Made ${plural(out.created.length, "package")}.`);
  };
  return (
    <FormModal title="Package the tasks" submitLabel={data && rows.some((r) => r.ticked) ? `Make ${plural(rows.filter((r) => r.ticked).length, "package")}` : "Make packages"}
               pendingLabel="Making…" canSubmit={!!data && !proposalProblem(rows)} onClose={onClose} onSubmit={submit}>
      <p className="lib-date">
        Groups the tasks {where} that aren&apos;t in a package by how often they&apos;re due and by trade, so each visit raises
        one work order. The longer ones go on some of the visits (the first {dayName(weekday)} of the month for a monthly task).
      </p>
      <div className="pk-dialog-row">
        <Field label="Visit day">
          <select value={weekday} onChange={(e) => setWeekday(e.target.value)}>
            {WEEKDAYS.map((d) => <option key={d} value={d}>{dayName(d)}</option>)}
          </select>
        </Field>
        <Field label="On time up to (days after)">
          <input type="number" min="0" max="366" step="1" inputMode="numeric" value={tolerance} onChange={(e) => setTolerance(e.target.value)} />
        </Field>
      </div>
      {state.error && <div className="card error">{state.error}</div>}
      {!data && !state.error && <p className="lib-date">Loading…</p>}
      {data && rows.length === 0 && (
        <p className="lib-date">Nothing to package {where}: every task on the calendar here is in a package already{data.already_in_packages ? ` (${plural(data.already_in_packages, "task")})` : ""}.</p>
      )}
      {data && rows.length > 0 && (
        <ul className="pk-proposal" aria-label="Packages to make">
          {rows.map((r) => (
            <li key={r.ref} className={"pk-prow" + (r.layerOf ? " pk-layer-row" : "")}>
              <input type="checkbox" checked={r.ticked} aria-label={`Make ${r.name || r.draft.name}`}
                     onChange={(e) => setRows(toggleRow(rows, r.ref, e.target.checked))} />
              <div className="pk-prow-main">
                <input type="text" className="pk-name-input" value={r.name} aria-label={`Name of ${r.draft.name}`} maxLength={200}
                       onChange={(e) => setRows(renameRow(rows, r.ref, e.target.value))} />
                <span className="lib-date pk-sub" title={r.draft.tasks.map((t) => t.name).join(", ")}>
                  {[cadenceWords(r.draft), plural(r.draft.tasks.length, "task"), r.draft.trade || null,
                    r.layerOf ? `adds to ${rows.find((x) => x.ref === r.layerOf)?.name || "the visit above"}` : `at ${r.draft.area?.name}`]
                    .filter(Boolean).join(" · ")}
                </span>
                {r.draft.warnings?.map((w) => <span key={w} className="lib-date pk-warn">{w}</span>)}
              </div>
            </li>
          ))}
        </ul>
      )}
      {leftOut.length > 0 && (
        <details className="pk-left-out">
          <summary>{plural(leftOut.length, "task")} stay on their own</summary>
          <ul>{leftOut.map((t) => <li key={t.id}>{t.name} ({t.subject?.name}): {t.why}</li>)}</ul>
        </details>
      )}
      {data && rows.length > 0 && problem && <p className="lib-date" role="alert">{problem}</p>}
    </FormModal>
  );
}

const UNITS = ["days", "weeks", "months", "years"];
const NTH = [[1, "first"], [2, "second"], [3, "third"], [4, "fourth"], [-1, "last"]];

// Add a package…: by hand, on the picked position or place.
export function AddPackageDialog({ scope, where, onClose, onDone }) {
  const [name, setName] = useState("");
  const [timing, setTiming] = useState("fixed");
  const [every, setEvery] = useState("1");
  const [unit, setUnit] = useState("weeks");
  const [weekday, setWeekday] = useState("saturday");
  const [nth, setNth] = useState("1");
  const [trade, setTrade] = useState("");
  const [tolerance, setTolerance] = useState("1");
  const patterned = timing === "fixed" && (unit === "weeks" || unit === "months");
  const n = Number(every);
  const ok = name.trim() && Number.isInteger(n) && n >= 1;
  const submit = async () => {
    const body = {
      ...scope, name: name.trim(), timing, every: n, unit, trade: trade.trim(),
      ...(patterned ? { weekday, ...(unit === "months" ? { nth: Number(nth) } : {}) } : {}),
      ...(tolerance !== "" && Number(tolerance) > 0 ? { tolerance: Math.round(Number(tolerance)), tolerance_unit: "days" } : {}),
    };
    const made = await createPackage(body);
    onDone(`Made ${made.name}. Add its tasks from its ⋯.`, made.id);
  };
  return (
    <FormModal title="Add a package" submitLabel="Add package" canSubmit={!!ok} onClose={onClose} onSubmit={submit}>
      <p className="lib-date">A package {where}: the tasks done together on one visit. Add its tasks after.</p>
      <Field label="Name" text={name}><input autoFocus value={name} maxLength={200} onChange={(e) => setName(e.target.value)} placeholder="e.g. Pool weekly check" /></Field>
      <Field label="Dates">
        <select value={timing} onChange={(e) => setTiming(e.target.value)}>
          <option value="fixed">Set dates (every Saturday)</option>
          <option value="from_last_visit">Counted from the last visit</option>
        </select>
      </Field>
      <div className="pk-dialog-row">
        <Field label="Every"><input type="number" min="1" step="1" inputMode="numeric" value={every} onChange={(e) => setEvery(e.target.value)} /></Field>
        <Field label="Unit">
          <select value={unit} onChange={(e) => setUnit(e.target.value)}>{UNITS.map((u) => <option key={u} value={u}>{u}</option>)}</select>
        </Field>
      </div>
      {patterned && (
        <div className="pk-dialog-row">
          {unit === "months" && (
            <Field label="Which">
              <select value={nth} onChange={(e) => setNth(e.target.value)}>{NTH.map(([v, w]) => <option key={v} value={v}>{w}</option>)}</select>
            </Field>
          )}
          <Field label={unit === "months" ? "Day of the week in the month" : "On"}>
            <select value={weekday} onChange={(e) => setWeekday(e.target.value)}>{WEEKDAYS.map((d) => <option key={d} value={d}>{dayName(d)}</option>)}</select>
          </Field>
        </div>
      )}
      <div className="pk-dialog-row">
        <Field label="Trade (optional)" text={trade}><input value={trade} maxLength={200} onChange={(e) => setTrade(e.target.value)} placeholder="e.g. Fitter" /></Field>
        <Field label="On time up to (days after)"><input type="number" min="0" step="1" inputMode="numeric" value={tolerance} onChange={(e) => setTolerance(e.target.value)} /></Field>
      </div>
    </FormModal>
  );
}

function PauseDialog({ pkg, onClose, onDone }) {
  const [reason, setReason] = useState("");
  const [until, setUntil] = useState("");
  const [full, setFull] = useState(true);
  return (
    <FormModal title={`Pause ${pkg.name}`} submitLabel="Pause" canSubmit={!!reason.trim()} onClose={onClose}
               onSubmit={async () => onDone(await changePackage(pkg.id, "pause", { reason: reason.trim(), until: until || null, full_visit: full }), "Paused.")}>
      <p className="lib-date">While it&apos;s paused it raises no work orders and its tasks aren&apos;t overdue. It comes back by itself on the return date.</p>
      <Field label="Why" text={reason}><input autoFocus value={reason} maxLength={200} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Pool drained for resurfacing" /></Field>
      <Field label="Back on (leave blank if not known)"><input type="date" value={until} onChange={(e) => setUntil(e.target.value)} /></Field>
      <label className="pk-check"><input type="checkbox" checked={full} onChange={(e) => setFull(e.target.checked)} /> The first visit back does everything missed while paused</label>
    </FormModal>
  );
}

function RetireDialog({ pkg, onClose, onDone }) {
  const [reason, setReason] = useState("");
  return (
    <FormModal title={`Retire ${pkg.name}?`} submitLabel="Retire" danger onClose={onClose}
               onSubmit={async () => onDone(await changePackage(pkg.id, "retire", { reason: reason.trim() }), "Retired.")}>
      <p>Its tasks go back to being raised on their own{pkg.layers?.length ? `, and its ${plural(pkg.layers.length, "layer")} retire with it` : ""}. It stays in the history and can be restored.</p>
      <Field label="Why (optional)" text={reason}><input value={reason} maxLength={200} onChange={(e) => setReason(e.target.value)} /></Field>
    </FormModal>
  );
}

// Add tasks…: the tasks where the package is (and below) that are in no package.
function AddTasksDialog({ pkg, onClose, onDone }) {
  const [tasks, setTasks] = useState(null);
  const [error, setError] = useState(null);
  const [picked, setPicked] = useState(() => new Set());
  const [rule, setRule] = useState("every");
  const [nth, setNth] = useState("4");
  const subject = pkg.subject;
  useEffect(() => {
    let live = true;
    const scope = subject?.kind === "location" ? { location_id: subject.id } : { position_id: subject?.id };
    proposePackages(scope).then((p) => live && setTasks(freeTasks(p))).catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [subject?.id, subject?.kind]);
  const flip = (id) => setPicked((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const submit = async () => {
    let last = null;
    for (const id of picked) {
      last = await addPackageTask(pkg.id, { task_id: id, visit_rule: rule, ...(rule === "nth" ? { every_nth: Number(nth) } : {}) });
    }
    onDone(last, `Added ${plural(picked.size, "task")}.`);
  };
  return (
    <FormModal title={`Add tasks to ${pkg.name}`} submitLabel={picked.size ? `Add ${plural(picked.size, "task")}` : "Add tasks"}
               canSubmit={picked.size > 0 && (rule === "every" || Number(nth) >= 2)} onClose={onClose} onSubmit={submit}>
      {error && <div className="card error">{error}</div>}
      {!tasks && !error && <p className="lib-date">Loading…</p>}
      {tasks && tasks.length === 0 && <p className="lib-date">Every task at {subject?.name || "its position"} and below is in a package already, by use, or an item&apos;s own.</p>}
      {tasks && tasks.length > 0 && (
        <ul className="pk-pick">
          {tasks.map((t) => (
            <li key={t.id}>
              <label className="pk-check">
                <input type="checkbox" checked={picked.has(t.id)} onChange={() => flip(t.id)} />
                <span>{t.name} <span className="lib-date">· {t.subject?.name} · every {t.interval} {t.unit}</span></span>
              </label>
            </li>
          ))}
        </ul>
      )}
      <div className="pk-dialog-row">
        <Field label="On">
          <select value={rule} onChange={(e) => setRule(e.target.value)}>
            <option value="every">Every visit</option>
            <option value="nth">Every Nth visit</option>
          </select>
        </Field>
        {rule === "nth" && <Field label="N"><input type="number" min="2" max="100" step="1" inputMode="numeric" value={nth} onChange={(e) => setNth(e.target.value)} /></Field>}
      </div>
    </FormModal>
  );
}

// ---- one package --------------------------------------------------------------------------

function PackageView({ id, today, onBack, onOpen, onChanged }) {
  const confirm = useConfirm();
  const [state, setState] = useState({ id: null, pkg: null, error: null });
  const [modal, setModal] = useState(null);
  const [said, setSaid] = useState(null);
  const load = useCallback(() => {
    let live = true;
    getPackage(id).then((pkg) => live && setState({ id, pkg, error: null })).catch((e) => live && setState({ id, pkg: null, error: e.message }));
    return () => { live = false; };
  }, [id]);
  useEffect(() => load(), [load]);
  const pkg = state.id === id ? state.pkg : null;
  const done = (fresh, text) => {
    setModal(null);
    if (fresh?.id === id) setState({ id, pkg: fresh, error: null });
    else load();
    setSaid(text || null);
    onChanged();
  };
  const run = async (fn, text) => {
    try {
      done(await fn(), text);
    } catch (e) {
      setSaid(e.message);
    }
  };
  const back = <button type="button" className="link pk-back" onClick={onBack}>← All packages here</button>;
  if (state.error && state.id === id) return <div>{back}<div className="card error">Couldn&apos;t load the package: {state.error}</div></div>;
  if (!pkg) return <div>{back}<p className="lib-date">Loading…</p></div>;
  const live = pkg.status !== "retired";
  const menu = [
    pkg.status === "active" && !pkg.flags?.includes("past_return_date") && { id: "pause", label: "Pause…", onSelect: () => setModal("pause") },
    (pkg.status === "paused" || pkg.flags?.includes("past_return_date")) && { id: "resume", label: "Resume", onSelect: () => run(() => changePackage(pkg.id, "resume"), "Resumed.") },
    live && { id: "add", label: "Add tasks…", onSelect: () => setModal("add") },
    live && { id: "retire", label: "Retire…", danger: true, onSelect: () => setModal("retire"), disabled: !!pkg.open_work_order, reason: pkg.open_work_order ? `Close or cancel work order #${pkg.open_work_order.number} first` : undefined },
    !live && { id: "restore", label: "Restore", onSelect: () => run(() => changePackage(pkg.id, "restore"), "Restored.") },
  ].filter(Boolean);
  const remove = async (t) => {
    const ok = await confirm({
      title: "Take this task out?", body: `“${t.name}” is raised on its own again, by its own interval.`,
      confirmLabel: "Take it out", pendingLabel: "Taking out…", failedWhat: "take it out",
      run: () => removePackageTask(pkg.id, t.task_id).then((fresh) => { done(fresh, `Took ${t.name} out.`); return true; }),
    });
    return ok;
  };
  const tol = pkg.tolerance?.amount ? `on time up to ${plural(pkg.tolerance.amount, pkg.tolerance.unit === "hours" ? "hour" : "day")} after` : null;
  return (
    <div className="pk-view">
      {back}
      <div className="pk-view-head">
        <div>
          <h3 className="pk-view-name">{pkg.name}</h3>
          <p className="lib-date pk-sub">
            {[cadenceWords(pkg), pkg.parent ? `on ${pkg.parent.name}'s visits` : pkg.subject?.name && `at ${pkg.subject.name}`, pkg.trade, tol].filter(Boolean).join(" · ")}
          </p>
          <div className="pk-chips"><StatusChips pkg={pkg} today={today} /><WhenCell pkg={pkg} /></div>
        </div>
        {menu.length > 0 && <MoreMenu label={`Actions for ${pkg.name}`} items={menu} />}
      </div>
      {pkg.parent && <p className="lib-date">A layer: its tasks go on <button type="button" className="link" onClick={() => onOpen(pkg.parent.id)}>{pkg.parent.name}</button>&apos;s work order on the days it visits.</p>}
      {said && <p className="lib-date" role="status">{said}</p>}
      <h4 className="td-sublabel">Tasks ({pkg.tasks.length})</h4>
      {pkg.tasks.length === 0 ? (
        <p className="lib-date">No tasks in it yet. {live ? <button type="button" className="link" onClick={() => setModal("add")}>Add tasks…</button> : null}</p>
      ) : (
        <ul className="pk-members">
          {pkg.tasks.map((t) => (
            <li key={t.task_id} className="pk-member">
              <div className="pk-member-main">
                <span className="pk-member-name">{t.name}</span>
                <span className="lib-date pk-sub">
                  {[t.subject?.name, visitRuleText(t), t.suppresses?.length ? `covers ${t.suppresses.map((s) => s.name).join(", ")}` : null,
                    t.next_due ? `next ${fmtDate(t.next_due)}` : null].filter(Boolean).join(" · ")}
                </span>
              </div>
              <span className="pk-chips">
                {t.owed && <Chip tone="warning" title="Not done on the last visit: it goes on the next one">Owed</Chip>}
                {t.retired && <Chip>Retired</Chip>}
              </span>
              {live && <MoreMenu label={`Actions for ${t.name}`} items={[{ id: "remove", label: "Remove from package…", danger: true, onSelect: () => remove(t) }]} />}
            </li>
          ))}
        </ul>
      )}
      {pkg.layers?.length > 0 && (
        <>
          <h4 className="td-sublabel">Layers</h4>
          <ul className="pk-members">
            {pkg.layers.map((l) => (
              <li key={l.id} className="pk-member"><button type="button" className="link" onClick={() => onOpen(l.id)}>{l.name}</button></li>
            ))}
          </ul>
        </>
      )}
      {pkg.next_visits?.length > 0 && (
        <p className="lib-date">Next visits: {pkg.next_visits.map((v) => `${fmtDate(v.on)} (${plural(v.tasks, "task")})`).join(", ")}</p>
      )}
      {modal === "pause" && <PauseDialog pkg={pkg} onClose={() => setModal(null)} onDone={done} />}
      {modal === "retire" && <RetireDialog pkg={pkg} onClose={() => setModal(null)} onDone={done} />}
      {modal === "add" && <AddTasksDialog pkg={pkg} onClose={() => setModal(null)} onDone={done} />}
    </div>
  );
}

// ---- the tab ------------------------------------------------------------------------------

export default function PackagesPanel({ row, today, onMenu = null }) {
  const q = usePackageQuery();
  const scope = useMemo(() => packageScope(row), [row]);
  const [state, setState] = useState({ key: null, rows: null, error: null });
  const [modal, setModal] = useState(null);
  const [said, setSaid] = useState(null);
  const [version, setVersion] = useState(0);
  const key = `${row.key}:${version}`;
  useEffect(() => {
    if (!scope) return undefined;
    let live = true;
    listPackages(scope)
      .then((d) => live && setState({ key, rows: d.packages, error: null }))
      .catch((e) => live && setState({ key, rows: [], error: e.message }));
    return () => { live = false; };
  }, [scope, key]);
  const rows = state.key === key ? state.rows : null;
  const shown = useMemo(() => rows && packageRows(rows, today), [rows, today]);
  const where = `at ${row.ref.name || "this row"} and below`;
  const refresh = () => setVersion((v) => v + 1);
  usePanelMenu(onMenu, [
    { id: "pkg-propose", label: "Package the tasks…", onSelect: () => setModal("propose") },
    { id: "pkg-new", label: "Add a package…", onSelect: () => setModal("new") },
  ]);
  if (!scope) return null;
  const late = shown ? shown.filter((r) => daysLate(r.pkg, today) > 0).length : 0;
  return (
    <div className="td-tab-page pk-panel">
      {q.open ? (
        <PackageView id={q.open} today={today} onBack={() => q.setOpen(null)} onOpen={q.setOpen} onChanged={refresh} />
      ) : (
        <>
          <p className="lib-date pk-purpose">Tasks done together on one visit, one work order each visit. Late first, then the soonest visit.</p>
          {said && <p className="lib-date" role="status">{said}</p>}
          {state.error && <div className="card error">Couldn&apos;t load the packages: {state.error}</div>}
          {shown === null ? <div className="card empty">Loading…</div> : shown.length === 0 ? (
            <div className="card empty pk-empty">
              <p>No packages here yet. <button type="button" className="link" onClick={() => setModal("propose")}>Package the tasks…</button> groups what&apos;s due together, so each visit raises one work order.</p>
              <p className="section-empty-more"><ShowMe help={HELP}>How work packages work</ShowMe></p>
            </div>
          ) : (
            <>
              <p className="lib-date pk-count">{plural(shown.length, "package")} {where}{late ? ` · ${late} late` : ""}</p>
              <ul className="pk-list" aria-label="Work packages">
                {shown.map(({ pkg, depth }) => (
                  <li key={pkg.id} className={"pk-row" + (depth ? " pk-layer" : "")} style={depth ? { "--pk-depth": depth } : undefined}>
                    <button type="button" className="pk-open" onClick={() => q.setOpen(pkg.id)} title="Open its tasks and layers">
                      <span className="pk-name">{depth ? <span className="pk-layer-mark" aria-label="Layer">↳ </span> : null}{pkg.name}</span>
                      <span className="lib-date pk-sub">{packageSubline(pkg)}{pkg.subject && !depth && pkg.subject.id !== row.key ? ` · at ${pkg.subject.name}` : ""}</span>
                    </button>
                    <span className="pk-right">
                      <WhenCell pkg={pkg} />
                      <span className="pk-chips"><StatusChips pkg={pkg} today={today} /></span>
                    </span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
      {modal === "propose" && (
        <PackageTasksDialog scope={scope} where={where} onClose={() => setModal(null)}
                            onDone={(text) => { setModal(null); setSaid(text); q.setOpen(null); refresh(); }} />
      )}
      {modal === "new" && (
        <AddPackageDialog scope={scope} where={`at ${row.ref.name || "this row"}`} onClose={() => setModal(null)}
                          onDone={(text, id) => { setModal(null); setSaid(text); refresh(); q.setOpen(id); }} />
      )}
    </div>
  );
}

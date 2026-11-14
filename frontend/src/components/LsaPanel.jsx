import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import {
  addPackageTask, changePackage, createPackage, createPackages, getPackage, getTaskTable, listPackages, proposePackages,
  removePackageTask,
} from "../api.js";
import { Field, FormModal, fmtDate, today as workspaceToday, useSendOnce } from "./MaintenanceParts.jsx";
import HowOften from "./HowOften.jsx";
import PositionForecast from "./PositionForecast.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import { CALENDAR, formFromPackage, howOftenProblem, packageBody, packageDates } from "../howOften.js";
import Chip from "./ui/Chip.jsx";
import MoreMenu from "./ui/MoreMenu.jsx";
import { ShowMe } from "./SectionPage.jsx";
import { useConfirm } from "./ConfirmProvider.jsx";
import { usePanelMenu } from "../panelMenu.js";
import {
  DEFAULT_TASK_COLUMNS, DEFAULT_TOLERANCE_DAYS, DEFAULT_VISIT_DAY, TASK_COLUMNS, WEEKDAYS, cadenceFor, cadenceWords, cellText, countTitle, dayName, daysLate, freeTasks,
  kindText, lateText, lsaColumns, taskOnText, lsaCsv, lsaRollup, modeLine, nextSort, packageScope, parseSort, proposalBatch, proposalProblem, proposalRows,
  renameRow, rollupLines, searchTasks, sortParam, sortTasks, tickAll, tickState, toggleRow, visitRuleText,
  MAINTENANCE_COLUMNS, costFoot, costWhere, maintenanceOrder, money, tasksHere,
} from "../lsaTab.js";
import { saveText } from "../sparesPlan.js";
import { exportFilename } from "../rcmImport.js";
import LsaTask from "./LsaTask.jsx";
import RbdTaskUses from "./RbdTaskUses.jsx";
import MaintenanceTask, { TradeRates } from "./MaintenanceTask.jsx";
import { PlusIcon } from "./LibRows.jsx";
import { isDesignRow } from "../explorerTabs.js";
import { ColumnChooser } from "./RcmWorksheet.jsx";
import "./RcmWorksheet.css";
import "./Outline.css";
import "../views/Maintenance.css";
import "./LsaPanel.css";

// The LSA tab of the Explorer's panel (Assets › Explorer, ?tab=lsa; it was the
// Packages tab, and ?tab=packages still opens it. Derryn, 8–9 Nov 2026: the
// tree, and a table of every task below the row picked to search, sort and
// package from, with what each task needs: the logistic support analysis).
// One row per task on the picked position or place and everything inside it:
// position, failure mode (its function › functional failure under it), task,
// kind, interval, trade, next due, its package, then hours, people, tools,
// spares, consumables and method. A row opens that task's LSA in the tab
// (?task=, LsaTask.jsx, with a back link). The bar for the ticked tasks adds up
// what they need (labour by trade, tools, spares, consumables), as does a
// package's view. Formatted as the RCM table (RcmWorksheet.css), with the Columns
// chooser in the heading's "…". Search (?q=) and sort (?sort=, Shift-click a
// header for a second key) stay in the address. Tick tasks and the bar at the
// foot offers Package selected… (a new package with them, its cadence from
// their intervals) and Add to a package… (one already on this tree). A
// package's name opens it in the same tab (?package=, with a back link): its
// tasks, layers and ⋯ (Pause…, Resume, Retire…, Add tasks…). "Package the
// tasks…" in the heading's "…" drafts packages from every loose task here, as
// does "Package the tasks here…" on a row's own menu in the tree (it leads the
// menu on this tab: treeRowMenu.js lsaLead); the drafts open in the tab too
// (?packaging=<the row>, with a back link), never a dialog.
//
// On a product's design (Derryn, 9 Nov 2026: a design's maintenance programme
// and its logistic support are design outputs) the table is the same, less
// what only built assets have: no ticks, no packaging bar, no packages to open
// and no Next due or Package columns (the design's tasks are packaged into
// visits, and fall due, on the items built from it: one line says so). The
// foot adds up what every task shown needs. A task's LSA opens as on an asset.

const HELP = { guide: "lsa" };

// ?package= (a package open), ?task= (a task's LSA open) or ?packaging= (the
// row whose tasks are being packaged), kept in the address.
function useOpenParam(name) {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();
  const set = (value) => {
    const next = new URLSearchParams(window.location.search);
    if (value) next.set(name, value);
    else next.delete(name);
    navigate(`${location.pathname}?${next}${location.hash}`, { replace: true, state: location.state });
  };
  return { open: params.get(name) || null, setOpen: set };
}

// What a set of tasks needs together, as label: text lines.
export function Rollup({ rollup, title, empty = null }) {
  const lines = rollupLines(rollup);
  if (!lines.length) return empty;
  return (
    <div className="lsa-rollup" role="group" aria-label={title}>
      <span className="lsa-rollup-title">{title}</span>
      <dl>
        {lines.map((l) => (
          <div key={l.label} className="lsa-rollup-line"><dt>{l.label}</dt><dd>{l.text}</dd></div>
        ))}
      </dl>
    </div>
  );
}

const plural = (n, one, many = `${one}s`) => `${n.toLocaleString("en-AU")} ${n === 1 ? one : many}`;

export function StatusChips({ pkg, today }) {
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
// Drawn in the panel beside the tree, in place of the task table (never a
// dialog): the heading's "…" and the row's own menu on this tab both open it.
export function PackageTasks({ scope, where, onBack, onDone }) {
  const [weekday, setWeekday] = useState(DEFAULT_VISIT_DAY);
  const [tolerance, setTolerance] = useState(String(DEFAULT_TOLERANCE_DAYS));
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
  const can = !!data && !proposalProblem(rows);
  const send = useSendOnce(async () => {
    const out = await createPackages(proposalBatch(rows, { tolerance }));
    onDone(`Made ${plural(out.created.length, "package")}.`);
  }, can);
  // A refusal shows above the buttons, which a long list of drafts puts off screen.
  const refusal = useRef(null);
  useEffect(() => { if (send.error) refusal.current?.scrollIntoView?.({ block: "nearest" }); }, [send.error]);
  return (
    <div className="pk-view pk-packaging" role="region" aria-label="Package the tasks">
      <button type="button" className="link pk-back" onClick={onBack} disabled={send.busy}>← All tasks here</button>
      <h3 className="pk-view-name">Package the tasks</h3>
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
      {send.error && <div className="card error" role="alert" ref={refusal}>{send.error}</div>}
      <div className="pk-packaging-foot">
        <button type="button" onClick={send.submit} disabled={send.busy || !can} aria-busy={send.busy || undefined}>
          {send.busy ? "Making…" : data && rows.some((r) => r.ticked) ? `Make ${plural(rows.filter((r) => r.ticked).length, "package")}` : "Make packages"}
        </button>
        <button type="button" className="secondary" onClick={onBack} disabled={send.busy}>Cancel</button>
      </div>
    </div>
  );
}


// Package selected… (and Add a package…, with no tasks): a new package on the
// picked position or place, with the tasks ticked; its cadence starts from
// their commonest interval.
// Overdue tasks going into a package stay overdue until done: the package's first visit
// doesn't make them on time.
export function overdueNote(n) {
  return `${n === 1 ? "1 of these is" : `${n} of these are`} overdue. ${n === 1 ? "It stays" : "They stay"} overdue, from ` +
    `${n === 1 ? "its" : "their"} own due date, until done: the package's first visit doesn't reset that. ` +
    "To do them sooner, raise the visit now from the package's page.";
}

export function AddPackageDialog({ scope, where, tasks = [], onClose, onDone }) {
  const start = useMemo(() => cadenceFor(tasks), [tasks]);
  const trades = [...new Set(tasks.map((t) => t.trade).filter(Boolean))];
  const [name, setName] = useState("");
  const [timing, setTiming] = useState("fixed");
  // Weekly visits on the visit day; monthly ones on the first of that weekday.
  const [how, setHow] = useState(() => ({
    ...formFromPackage({ cadence: { every: start.every, unit: start.unit } }),
    weekday: dayName(DEFAULT_VISIT_DAY), pattern: start.unit === "weeks" ? "weekday" : start.unit === "months" ? "nth" : "none",
  }));
  const [trade, setTrade] = useState(trades.length === 1 ? trades[0] : "");
  const [tolerance, setTolerance] = useState(String(DEFAULT_TOLERANCE_DAYS));
  const fixed = timing === "fixed";
  const problem = howOftenProblem(how, { wholeOnly: true });
  const ok = name.trim() && !problem;
  const today = workspaceToday();
  const dates = problem ? null : packageDates(how, { anchor: today, today, timing });
  const submit = async () => {
    const { clear_pattern: _none, ...cadence } = packageBody(fixed ? how : { ...how, pattern: "none" });
    const body = {
      ...scope, name: name.trim(), timing, ...cadence, trade: trade.trim(),
      ...(tolerance !== "" && Number(tolerance) > 0 ? { tolerance: Math.round(Number(tolerance)), tolerance_unit: "days" } : {}),
      ...(tasks.length ? { tasks: tasks.map((t) => t.id) } : {}),
    };
    const made = await createPackage(body);
    onDone(tasks.length ? `Made ${made.name} with ${plural(tasks.length, "task")}.` : `Made ${made.name}. Add its tasks from its ⋯.`, made.id);
  };
  return (
    <FormModal title={tasks.length ? `Package ${plural(tasks.length, "task")}` : "Add a package"} submitLabel={tasks.length ? "Make package" : "Add package"}
               canSubmit={!!ok} onClose={onClose} onSubmit={submit}>
      <p className="lib-date">
        {tasks.length
          ? <>A package {where}, done on one visit: {tasks.map(taskOnText).join(", ")}.{start.mixed ? " Their intervals differ: the visit goes by the one below, and each task is done on every visit." : ""}</>
          : <>A package {where}: the tasks done together on one visit. Add its tasks after.</>}
      </p>
      {tasks.some((t) => t.overdue) && (
        <p className="maint-overdue" role="status">
          {overdueNote(tasks.filter((t) => t.overdue).length)}
        </p>
      )}
      <Field label="Name" text={name}><input autoFocus value={name} maxLength={200} onChange={(e) => setName(e.target.value)} placeholder="e.g. Weekly inspection" /></Field>
      <Field label="Dates">
        <select value={timing} onChange={(e) => setTiming(e.target.value)}>
          <option value="fixed">Set dates</option>
          <option value="from_last_visit">Counted from the last visit</option>
        </select>
      </Field>
      <fieldset className="mt-how">
        <legend>How often</legend>
        <HowOften value={how} onChange={setHow} units={CALENDAR} patterns={fixed} problem={problem} dates={dates}
                  datesNote={fixed ? "" : "Counted from the last visit: each visit is the interval after the one before closes."} />
      </fieldset>
      <div className="pk-dialog-row">
        <Field label="Trade (optional)" text={trade}><input value={trade} maxLength={200} onChange={(e) => setTrade(e.target.value)} placeholder="e.g. Fitter" /></Field>
        <Field label="On time up to (days after)"><input type="number" min="0" step="1" inputMode="numeric" value={tolerance} onChange={(e) => setTolerance(e.target.value)} /></Field>
      </div>
    </FormModal>
  );
}

export function PauseDialog({ pkg, onClose, onDone }) {
  const [reason, setReason] = useState("");
  const [until, setUntil] = useState("");
  const [full, setFull] = useState(true);
  return (
    <FormModal title={`Pause ${pkg.name}`} submitLabel="Pause" canSubmit={!!reason.trim()} onClose={onClose}
               onSubmit={async () => onDone(await changePackage(pkg.id, "pause", { reason: reason.trim(), until: until || null, full_visit: full }), "Paused.")}>
      <p className="lib-date">While it&apos;s paused it raises no work orders and its tasks aren&apos;t overdue. It comes back by itself on the return date.</p>
      <Field label="Why" text={reason}><input autoFocus value={reason} maxLength={200} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Plant shut down for overhaul" /></Field>
      <Field label="Back on (leave blank if not known)"><input type="date" value={until} onChange={(e) => setUntil(e.target.value)} /></Field>
      <label className="pk-check"><input type="checkbox" checked={full} onChange={(e) => setFull(e.target.checked)} /> The first visit back does everything missed while paused</label>
    </FormModal>
  );
}

export function RetireDialog({ pkg, onClose, onDone }) {
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
                <span>{t.name} <span className="lib-date">· {[t.subject?.within, t.subject?.name].filter(Boolean).join(" › ")} · every {t.interval} {t.unit}</span></span>
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

// Add to a package…: the packages on this tree; the ticked tasks join the one picked.
function AddToPackageDialog({ scope, tasks, onClose, onDone }) {
  const [list, setList] = useState(null);
  const [error, setError] = useState(null);
  const [pick, setPick] = useState(null);
  const [rule, setRule] = useState("every");
  const [nth, setNth] = useState("4");
  useEffect(() => {
    let live = true;
    listPackages(scope).then((d) => live && setList(d.packages.filter((p) => p.status !== "retired")))
      .catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [scope]);
  const submit = async () => {
    for (const t of tasks) {
      await addPackageTask(pick, { task_id: t.id, visit_rule: rule, ...(rule === "nth" ? { every_nth: Number(nth) } : {}) });
    }
    onDone(`Added ${plural(tasks.length, "task")} to ${list.find((p) => p.id === pick)?.name || "the package"}.`);
  };
  return (
    <FormModal title={`Add ${plural(tasks.length, "task")} to a package`} submitLabel="Add" pendingLabel="Adding…"
               canSubmit={!!pick && (rule === "every" || Number(nth) >= 2)} onClose={onClose} onSubmit={submit}>
      {error && <div className="card error">{error}</div>}
      {tasks.some((t) => t.overdue) && <p className="maint-overdue" role="status">{overdueNote(tasks.filter((t) => t.overdue).length)}</p>}
      {!list && !error && <p className="lib-date">Loading…</p>}
      {list && list.length === 0 && <p className="lib-date">No packages on this part of the tree yet: use Package selected… to make one.</p>}
      {list && list.length > 0 && (
        <ul className="pk-pick" role="radiogroup" aria-label="Packages">
          {list.map((p) => (
            <li key={p.id}>
              <label className="pk-check">
                <input type="radio" name="pk-target" checked={pick === p.id} onChange={() => setPick(p.id)} />
                <span>{p.parent ? "↳ " : ""}{p.name} <span className="lib-date">· {cadenceWords(p)}{p.trade ? ` · ${p.trade}` : ""} · {plural(p.task_count, "task")}</span></span>
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
      <Rollup rollup={pkg.rollup} title="Each visit needs"
              empty={pkg.tasks.length ? <p className="lib-date">No labour, tools or spares set on its tasks yet: open a task on the table to add them.</p> : null} />
      {pkg.next_visits?.length > 0 && (
        <p className="lib-date">Next visits: {pkg.next_visits.map((v) => `${fmtDate(v.on)} (${plural(v.tasks, "task")})`).join(", ")}</p>
      )}
      {modal === "pause" && <PauseDialog pkg={pkg} onClose={() => setModal(null)} onDone={done} />}
      {modal === "retire" && <RetireDialog pkg={pkg} onClose={() => setModal(null)} onDone={done} />}
      {modal === "add" && <AddTasksDialog pkg={pkg} onClose={() => setModal(null)} onDone={done} />}
    </div>
  );
}

// ---- the tab: every task here and below, as a table --------------------------------

// Each variant keeps its own columns: the LSA tab every column, the Maintenance tab the
// planning ones (MAINTENANCE_COLUMNS) until changed.
const COLS_KEY = { lsa: "reliafy.lsa.columns", maintenance: "reliafy.maintenance.columns" };
// The LSA tab's usual columns are as they were; From and Cost each time are in its chooser.
const USUAL_COLS = { lsa: DEFAULT_TASK_COLUMNS.filter((id) => id !== "from" && id !== "cost"), maintenance: MAINTENANCE_COLUMNS };
function readCols(variant) {
  try {
    const got = JSON.parse(localStorage.getItem(COLS_KEY[variant]) || "null");
    if (Array.isArray(got) && got.length) return DEFAULT_TASK_COLUMNS.filter((id) => got.includes(id));
  } catch { /* storage blocked: the usual columns */ }
  return USUAL_COLS[variant];
}
function saveCols(variant, cols) {
  try { localStorage.setItem(COLS_KEY[variant], JSON.stringify(cols)); } catch { /* not kept */ }
}

// ?q= and ?sort= (with ?package=, the package open), kept in the address.
// Each change starts from the address as it is when it's written, not as it
// was when the change was made: the search box writes a moment after typing
// stops, and a sort clicked meanwhile must not be undone by it.
function useTableQuery() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();
  const set = (changes) => {
    const next = new URLSearchParams(window.location.search);
    for (const [k, v] of Object.entries(changes)) if (v) next.set(k, v); else next.delete(k);
    navigate(`${location.pathname}?${next}${location.hash}`, { replace: true, state: location.state });
  };
  return {
    q: params.get("q") || "", setQ: (v) => set({ q: v }),
    sort: parseSort(params.get("sort")), setSort: (keys) => set({ sort: sortParam(keys) }),
  };
}

function TaskCell({ t, col, onPackage, onTask, maint = false }) {
  if (col === "cost") {
    const c = t.cost;
    if (c?.amount == null) return <span className="rw-blank" title={costWhere(c)}>Not set</span>;
    const partial = c.source === "lsa" && !c.lsa?.complete;
    return (
      <span className="rw-txt pk-num" title={`${money(c.amount)} each time. ${costWhere(c)}`}>
        {money(c.amount)}{partial ? <span className="rw-sum" aria-label="partial"> *</span> : null}
      </span>
    );
  }
  if (col === "mode") {
    const m = t.modes?.[0];
    if (!m) return <span className="rw-blank">No failure mode</span>;
    const more = t.modes.length - 1;
    return (
      <span className="pk-two" title={[m.text, modeLine(m)].filter(Boolean).join("\n")}>
        <span className="rw-txt">{m.text}{more > 0 ? <span className="rw-sum"> +{more}</span> : null}</span>
        {modeLine(m) && <span className="rw-sum">{modeLine(m)}</span>}
      </span>
    );
  }
  if (col === "kind") {
    const text = kindText(t);
    return text ? <Chip tone={t.on_event ? "neutral" : "accent"} className="pk-kind" title={text}>{text}</Chip> : null;
  }
  if (col === "due") {
    if (!t.next_due) return null;
    const why = [t.overdue ? "Overdue" : null, t.due_basis].filter(Boolean).join(". ");
    return <span className={t.overdue ? "pk-overdue" : undefined} title={why || undefined}>{fmtDate(t.next_due)}</span>;
  }
  if (col === "package") {
    if (t.package) {
      return <button type="button" className="link pk-pkg-link" onClick={() => onPackage(t.package.id)} title={`Open ${t.package.name}`}>{t.package.name}</button>;
    }
    return t.why_not ? <span className="rw-sum" title={`Stays on its own: ${t.why_not}`}>On its own</span> : null;
  }
  if (col === "task") {
    return <button type="button" className="link pk-task-link" onClick={() => onTask(t.id)} title={maint ? `Open ${t.name}` : `Open what ${t.name} needs`}>{t.name}</button>;
  }
  const text = cellText(t, col);
  const counted = countTitle(t, col);
  return <span className={"rw-txt" + (TASK_COLUMNS.find((c) => c.id === col)?.num ? " pk-num" : "")} title={counted || text}>{text}</span>;
}

const TICK_W = 36;

// variant "maintenance": the Explorer's Maintenance tab (Derryn, 12 Nov 2026: "all maintenance
// tasks … from RCM or just added directly … the costs per task"). The same table and its search,
// sort, columns and CSV, with the planning columns first (MAINTENANCE_COLUMNS: From and Cost each
// time among them), the row's own tasks unless "Include what's inside" is ticked (?below=1), no
// ticks or packaging (the LSA tab packages), "Add task" in its bar (?addtask=<the row>) and a task
// opening as its own pane (?mtask=, MaintenanceTask.jsx) rather than its LSA. "Trade rates…" in the
// heading's "…" (?rates=1) prices every task's labour.
export default function LsaPanel({ row, today, onMenu = null, variant = "lsa" }) {
  const maint = variant === "maintenance";
  const open = useOpenParam("package");
  const taskOpen = useOpenParam(maint ? "mtask" : "task");
  const adding = useOpenParam("addtask");
  const ratesOpen = useOpenParam("rates");
  // Tasks / Forecast (?mview=forecast): the forecast for a position and everything inside it
  // (PositionForecast.jsx), inside the asset opened (?root=). The Maintenance tab is operators' only.
  const viewParam = useOpenParam("mview");
  const [search] = useSearchParams();
  const forecastable = maint && row.type === "pos";
  const forecastOn = forecastable && viewParam.open === "forecast";
  // Held here as well as in the address, so the box answers at once.
  const belowParam = useOpenParam("below");
  const [belowOn, setBelowOn] = useState(belowParam.open === "1");
  const below = !maint || belowOn;
  const showBelow = (on) => { setBelowOn(on); belowParam.setOpen(on ? "1" : null); };
  // The row whose tasks are being packaged: only this row's (another row picked shows its table).
  const packaging = useOpenParam("packaging");
  const tq = useTableQuery();
  const scope = useMemo(() => packageScope(row), [row]);
  const [state, setState] = useState({ key: null, data: null, error: null });
  const [picked, setPicked] = useState(() => new Set());
  const [modal, setModal] = useState(null);
  const [said, setSaid] = useState(null);
  const [version, setVersion] = useState(0);
  const [cols, setColsState] = useState(() => readCols(variant));
  const [colsOpen, setColsOpen] = useState(false);
  const [query, setQuery] = useState(tq.q);
  const key = `${row.key}:${version}`;
  useEffect(() => {
    if (!scope) return undefined;
    let live = true;
    getTaskTable(scope)
      .then((data) => live && setState({ key, data, error: null }))
      .catch((e) => live && setState({ key, data: null, error: e.message }));
    return () => { live = false; };
  }, [scope, key]);
  // A new row picked: nothing ticked.
  useEffect(() => { setPicked(new Set()); }, [row.key]);
  // The search box writes the address a moment after typing stops.
  useEffect(() => {
    if (query === tq.q) return undefined;
    const t = setTimeout(() => tq.setQ(query), 250);
    return () => clearTimeout(t);
  }, [query]); // eslint-disable-line react-hooks/exhaustive-deps
  const data = state.key === key ? state.data : null;
  const all = useMemo(() => (data?.tasks ? tasksHere(data.tasks, row.key, below) : null), [data, row.key, below]);
  const shown = useMemo(() => all && sortTasks(searchTasks(all, query), tq.sort), [all, query, tq.sort]);
  const design = isDesignRow(row);
  // No ticks or packaging bar: a design's (packaged on the built items) and the Maintenance tab's.
  const plain = design || maint;
  const offered = lsaColumns({ design });
  // The row's own tasks alone are all on it: no Position column.
  const chosenCols = offered.filter((c) => cols.includes(c.id) && (below || c.id !== "position"));
  const columns = maint ? maintenanceOrder(chosenCols) : chosenCols;
  const tickW = plain ? 0 : TICK_W;
  const total = tickW + columns.reduce((n, c) => n + c.width, 0);
  const refresh = () => setVersion((v) => v + 1);
  // A design's chooser lists fewer columns: the ones it leaves out keep their state for assets.
  const setCols = (next) => {
    const kept = cols.filter((id) => !offered.some((c) => c.id === id));
    const merged = DEFAULT_TASK_COLUMNS.filter((id) => next.includes(id) || kept.includes(id));
    setColsState(merged);
    saveCols(variant, merged);
  };
  const chosen = all ? all.filter((t) => picked.has(t.id)) : [];
  const where = `at ${row.ref.name || "this row"}`;
  usePanelMenu(onMenu, [
    ...(maint ? [{ id: "mt-add", label: "Add task…", onSelect: () => adding.setOpen(row.key) }] : []),
    { id: "pkg-cols", label: "Columns…", onSelect: () => setColsOpen(true) },
    ...(maint ? [{ id: "mt-rates", label: "Trade rates…", title: "The hourly rate of each trade: it prices every task's labour", onSelect: () => ratesOpen.setOpen("1") }] : []),
    { id: "lsa-csv", label: "Export CSV", disabled: !all?.length, title: all?.length ? "The table with every column, for Excel" : "No tasks to export",
      onSelect: () => saveText(lsaCsv(shown || all), exportFilename(row.ref.name, { what: maint ? "Maintenance" : "LSA" })) },
    ...(plain ? [] : [
      { id: "pkg-propose", label: "Package the tasks…", onSelect: () => packaging.setOpen(row.key), title: "Drafts packages from every task here not in one, by how often and by trade" },
      { id: "pkg-new", label: "Add a package…", onSelect: () => setModal("new") },
    ]),
  ]);
  if (!scope) return null;
  const done = (text) => { setModal(null); setSaid(text); setPicked(new Set()); refresh(); };
  if (maint && (adding.open === row.key || taskOpen.open)) {
    const close = () => { adding.setOpen(null); taskOpen.setOpen(null); };
    return (
      <div className="td-tab-page pk-panel">
        <MaintenanceTask row={row} taskId={adding.open === row.key ? null : taskOpen.open} onBack={close}
                         onDone={(text) => { close(); done(text); }} />
      </div>
    );
  }
  if (maint && ratesOpen.open) {
    return (
      <div className="td-tab-page pk-panel">
        <TradeRates onBack={() => ratesOpen.setOpen(null)} onChanged={refresh} />
      </div>
    );
  }
  if (packaging.open === row.key && !plain) {
    return (
      <div className="td-tab-page pk-panel">
        <PackageTasks scope={scope} where={`${where} and below`} onBack={() => packaging.setOpen(null)}
                      onDone={(text) => { packaging.setOpen(null); done(text); }} />
      </div>
    );
  }
  if (taskOpen.open) {
    return (
      <div className="td-tab-page pk-panel">
        <LsaTask taskId={taskOpen.open} onBack={() => taskOpen.setOpen(null)} onChanged={refresh} />
      </div>
    );
  }
  if (open.open && !design) {
    return (
      <div className="td-tab-page pk-panel">
        <PackageView id={open.open} today={today} onBack={() => open.setOpen(null)} onOpen={open.setOpen} onChanged={refresh} />
      </div>
    );
  }
  const viewSwitch = forecastable ? (
    <SegmentedControl size="sm" className="mt-view" label="Show" value={forecastOn ? "forecast" : "tasks"}
                      onChange={(v) => viewParam.setOpen(v === "forecast" ? "forecast" : null)}
                      options={[{ value: "tasks", label: "Tasks" }, { value: "forecast", label: "Forecast", title: "The work, failures and costs to come here and inside it, by month" }]} />
  ) : null;
  if (forecastOn) {
    return (
      <div className="td-tab-page pk-panel rw">
        <PositionForecast positionId={row.key} name={row.ref.name || "this position"} root={search.get("root") || null}
                          bar={viewSwitch} />
      </div>
    );
  }
  const tick = shown ? tickState(shown.filter((t) => !t.why_not), picked) : "none";
  const flip = (id) => setPicked((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const free = chosen.filter((t) => !t.package && !t.why_not);
  const inOne = chosen.filter((t) => t.package);
  return (
    <div className="td-tab-page pk-panel rw">
      <p className="lib-date pk-purpose">
        {maint
          ? `Every maintenance task ${below ? "here and below" : "here"}: from the RCM or added directly, how often, when it's next due and what it costs each time. The RCM reads each task's cost from here. Open a task to change it.`
          : design
          ? "Every task in the design here and below, with what it needs: open a task to set its labour, tools, spares and method. Tasks are packaged into visits on the items built from it."
          : "Every task here and below, with what it needs: open a task to set its labour, tools, spares and method. Tick the ones done on the same visit and package them: each visit then raises one work order."}
      </p>
      <div className="pk-bar">
        <label className="tp-filter pk-filter">
          <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.6" fill="none" /><path d="m10.5 10.5 3 3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>
          <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={design ? "Filter: position, failure mode, task" : "Filter: position, failure mode, task, package"}
                 aria-label="Search the tasks" />
        </label>
        {maint && (
          <label className="mt-below">
            <input type="checkbox" checked={below} onChange={(e) => showBelow(e.target.checked)} />
            Include what&apos;s inside
          </label>
        )}
        {maint && (
          <button type="button" className="secondary sm mt-add" onClick={() => adding.setOpen(row.key)}>
            <PlusIcon /> Add task
          </button>
        )}
        {shown && <span className="lib-date pk-count">{shown.length === all.length ? plural(all.length, "task") : `${shown.length} of ${plural(all.length, "task")}`}</span>}
        {viewSwitch}
        {colsOpen && (
          <div className="pk-cols">
            <ColumnChooser cols={cols} onCols={setCols} usual={USUAL_COLS[variant]} columns={offered} open={colsOpen}
                           onClose={() => setColsOpen(false)} />
          </div>
        )}
      </div>
      {said && <p className="lib-date" role="status">{said}</p>}
      {state.error && <div className="card error">Couldn&apos;t load the tasks: {state.error}</div>}
      {data?.truncated && <p className="lib-date">Showing the first {all.length} of {data.total} tasks: pick a smaller branch to see the rest.</p>}
      {!shown && !state.error ? <div className="card empty">Loading…</div> : shown && all.length === 0 ? (
        <div className="card empty pk-empty">
          <p>{maint ? `No maintenance tasks ${below ? "here or below" : "here"} yet. Add one (from the maker's manual, a regulation or your own practice), or decide the failure modes on the RCM tab: their tasks show here.`
            : design ? "No tasks in the design here or below yet. Decide the failure modes on the RCM tab: their tasks show here, to say what each needs."
            : "No tasks here or below yet. Decide the failure modes on the RCM tab: their tasks show here to package."}</p>
          {maint ? (
            <p className="section-empty-more">
              <button type="button" className="link" onClick={() => adding.setOpen(row.key)}>Add a task</button>
              {!below && <> · <button type="button" className="link" onClick={() => showBelow(true)}>Include what&apos;s inside</button></>}
            </p>
          ) : <p className="section-empty-more"><ShowMe help={HELP}>Say what each task needs, and package tasks into visits</ShowMe></p>}
        </div>
      ) : shown && (
        <div className="maint-scroll rw-grid pk-grid">
          <div className="pk-table" role="table" aria-label={below ? "Tasks here and below" : "Tasks here"} aria-rowcount={shown.length + 1} style={{ minWidth: total }}>
            <div className="rw-head" role="row">
              {!plain && (
                <div className="rw-h pk-tick" role="columnheader" style={{ width: TICK_W }}>
                  <input type="checkbox" aria-label="Tick every task shown" checked={tick === "all"} disabled={!shown.length}
                         ref={(el) => { if (el) el.indeterminate = tick === "some"; }}
                         onChange={(e) => setPicked(tickAll(shown.filter((t) => !t.why_not), picked, e.target.checked))} />
                </div>
              )}
              {columns.map((c) => {
                const at = tq.sort.findIndex((k) => k.col === c.id);
                const dir = at >= 0 ? tq.sort[at].dir : 0;
                return (
                  <div key={c.id} role="columnheader" className="rw-h" style={{ width: c.width }}
                       aria-sort={dir ? (dir < 0 ? "descending" : "ascending") : "none"} title={c.title ? `${c.label}: ${c.title}` : c.label}>
                    <button type="button" className="rw-hs" onClick={(e) => tq.setSort(nextSort(tq.sort, c.id, e.shiftKey))}
                            aria-label={`${c.label}: sort (Shift-click to add it as a second sort)`}>
                      {c.label}{dir ? <span className="tt-sortarrow" aria-hidden="true">{dir < 0 ? " ▼" : " ▲"}{tq.sort.length > 1 ? at + 1 : ""}</span> : null}
                    </button>
                  </div>
                );
              })}
              <div className="rw-h rw-fill" aria-hidden="true" />
            </div>
            {shown.length === 0 ? (
              <p className="lib-date pk-none">No tasks match “{query}”. <button type="button" className="link" onClick={() => setQuery("")}>Clear the search</button></p>
            ) : shown.map((t) => (
              <div key={t.id} role="row" className={"rw-row pk-trow" + (picked.has(t.id) ? " focus" : "")}
                   onClick={(e) => { if (!e.target.closest("button, a, input")) taskOpen.setOpen(t.id); }}>
                {!plain && (
                  <div className="rw-c pk-tick" role="cell" style={{ width: TICK_W }}>
                    <input type="checkbox" checked={picked.has(t.id)} disabled={!!t.why_not} onChange={() => flip(t.id)}
                           aria-label={`Tick ${t.name}`} title={t.why_not ? `Can't join a package: ${t.why_not}` : undefined} />
                  </div>
                )}
                {columns.map((c) => (
                  <div key={c.id} role="cell" className="rw-c" style={{ width: c.width }}>
                    <TaskCell t={t} col={c.id} onPackage={open.setOpen} onTask={taskOpen.setOpen} maint={maint} />
                  </div>
                ))}
                <div className="rw-c rw-fill" aria-hidden="true" />
              </div>
            ))}
          </div>
        </div>
      )}
      {design && shown?.length > 0 && (
        <div className="pk-actions pk-design-foot" role="region" aria-label="What the tasks need">
          <span className="pk-actions-n">{shown.length === all.length ? plural(all.length, "task") : `${shown.length} of ${plural(all.length, "task")}`}</span>
          <Rollup rollup={lsaRollup(shown)} title="Together they need"
                  empty={<span className="lib-date">No labour, tools or spares set yet: open a task to add them.</span>} />
        </div>
      )}
      {maint && all?.length > 0 && <RbdTaskUses taskIds={all.map((t) => t.id)} version={version} />}
      {maint && shown?.length > 0 && (
        <div className="pk-actions pk-design-foot" role="region" aria-label="What the tasks cost">
          <span className="pk-actions-n">{shown.length === all.length ? plural(all.length, "task") : `${shown.length} of ${plural(all.length, "task")}`}</span>
          <span className="lib-date">{costFoot(shown)}</span>
        </div>
      )}
      {!plain && picked.size > 0 && (
        <div className="pk-actions" role="region" aria-label="Selected tasks">
          <span className="pk-actions-n">{plural(picked.size, "task")} selected</span>
          <button type="button" className="link" disabled={!free.length} onClick={() => setModal("package")}
                  title={free.length ? undefined : "They're all in a package already"}>Package selected…</button>
          <button type="button" className="link" disabled={!free.length} onClick={() => setModal("add-to")}>Add to a package…</button>
          <button type="button" className="link" onClick={() => setPicked(new Set())}>Clear</button>
          <Rollup rollup={lsaRollup(chosen)} title="To bring" />
          {inOne.length > 0 && <span className="lib-date pk-actions-note">{plural(inOne.length, "task")} already in a package stay{inOne.length === 1 ? "s" : ""} there.</span>}
        </div>
      )}
      {modal === "package" && (
        <AddPackageDialog scope={scope} where={where} tasks={free} onClose={() => setModal(null)} onDone={(text) => done(text)} />
      )}
      {modal === "add-to" && <AddToPackageDialog scope={scope} tasks={free} onClose={() => setModal(null)} onDone={done} />}
      {modal === "new" && (
        <AddPackageDialog scope={scope} where={where} onClose={() => setModal(null)}
                          onDone={(text, id) => { done(text); open.setOpen(id); }} />
      )}
    </div>
  );
}

import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { noDutyBasis, dutyHref } from "../explorerOperations.js";
import { dueCell, nextOf, readingWords } from "../explorerTasks.js";
import {
  createSubjectTask, getFailureModeCosts, getFailureModeIntervalInputs, getStrategyAnalysis, getMaintenancePosition, getSupportFit, getTaskIntervalBasis, getTaskLsa, linkTaskFailureMode, listTradeRates,
  retireMaintenanceTask, setModeResponse, setTradeRate, unlinkTaskFailureMode, updateFailureMode, updateMaintenanceTask,
} from "../api.js";
import { today as workspaceToday, useSendOnce } from "./MaintenanceParts.jsx";
import Field from "./ui/Field.jsx";
import { Checkbox, Select as NativeSelect, TextInput } from "./ui/Controls.jsx";
import Section from "./ui/Section.jsx";
import Select from "./Select.jsx";
import { formatDate } from "../dates.js";
import LoadFailed from "./LoadFailed.jsx";
import Loading from "./ui/Loading.jsx";
import TaskSchedule from "./TaskSchedule.jsx";
import TaskExtras from "./TaskExtras.jsx";
import QuantityInput from "./ui/QuantityInput.jsx";
import { formFromTask, howOftenProblem, previewFor, taskAnchor, taskBody, taskUnitChoices } from "../howOften.js";
import { costFields, figureText, placeholderFor, RESPONSE_KIND, responseKindOf, responseTrigger, usedText } from "../failureCosts.js";
import { costWords, labourWords, partWords } from "../taskExtras.js";
import { basisLine } from "../intervalBasis.js";
import { triggerBody, triggerState, triggerWhy } from "../taskTrigger.js";
import { taskKey as rcmTaskKey } from "../explorerRcm.js";
import { useConfirm } from "./ConfirmProvider.jsx";
import { costWhere, fromRcm, fromText, money, SOURCE_WORDS } from "../lsaTab.js";
import { taskUnits } from "../maintenanceSubjects.js";
import { AGE_NOTE, lengthNote, tooLong } from "../maintenanceText.js";
import { explorerHere } from "../products.js";
import { workspaceCurrency } from "../money.js";
import TaskTwins from "./TaskTwins.jsx";
import NeedsSection, { LabourRows, SparesRows, useNeeds } from "./TaskNeeds.jsx";
import { every } from "../taskOptimise.js";
import { restorationBody, restorationForm, restorationProblem, RESTORE_CHOICES } from "../taskRestoration.js";
import { canSupport, COMBINE_HELP, SOURCE_WORD, SUPPORT_HELP, SUPPORT_SOURCES, impactWords, supportBody, supportForm, supportProblem, withFit } from "../taskSupport.js";
import Chip from "./ui/Chip.jsx";

// A task on the Explorer's Maintenance tab, in the panel beside the tree (never a dialog):
// "Add task" (?addtask=<the row>), a task opened from the table (?mtask=<id>), and a failure mode's
// response added from a row's menu (?respond=failure|found&fm=<mode>). It draws the panel's title
// (the task's name), its body and the footer with Save, Cancel and Retire…; TaskSide gives it the
// panel's head (PanelKind: the spanner, "Task · <where>"; × and Expand are the way out).
//
// In order (Derryn, 23 Nov 2026, "way too confusing"):
//   Kind of task, then What's done (the action alone, "Replace the seal": how it's done is its LSA),
//   then How often (TaskSchedule: "Every [N] [unit]", its next dates and Next due; More scheduling
//   options folded: the second limit, set calendar dates, at shutdowns, when the item is replaced),
//   then its kind's own settings (keeps it on its life; what it leaves the item as), Why it's done,
//   and the optional extras folded: Cost, Labour, Parts (each with a line saying what's set), the
//   rest of What it needs.
//
// A task from an RCM decision: what the RCM owns (its failure modes, why it's done and its kind of
// task, the decision's) is edited only on the RCM tab; here it's one quiet line, "From RCM: <its
// failure modes> · <kind> · Open in RCM ›". A response (a task raised when a failure mode fails, or
// when an inspection finds it: responses.py) has its trigger in place of How often, and a corrective
// one the cost of the failure itself (the failure mode's downtime, its cost an hour, a typed cost).

// The words of each kind: a short name (so the closed picker fits a phone) and the rest as its hint.
const KINDS = [
  { value: "", label: "Routine work", hint: "Lubricate, clean, adjust, inspect" },
  { value: "fixed_interval", label: "Replace at age", hint: "Every … since it was last done" },
  { value: "failure_finding", label: "Check a hidden function", hint: "Failure-finding" },
  { value: "on_condition", label: "Check condition" },
];
export const kindLabel = (outcome) => (KINDS.find((k) => k.value === (outcome || "")) || KINDS[0]).label;

const num = (v) => (v === "" || v == null ? null : Number(v));
const validMoney = (v) => v === "" || (Number.isFinite(Number(v)) && Number(v) >= 0);

// What the form starts from: a task's fields, or blanks for a new one.
function startFrom(task) {
  return {
    name: task?.name || "", interval: task?.interval != null ? String(task.interval) : "", unit: task?.unit || "months",
    how: formFromTask(task),
    outcome: task?.outcome || "", source: task && !fromRcm(task) ? task.source : "manual",
    // Its reference (a manual's section, a standard): `docRef`, as `reference` is the supporting
    // task's reference interval (taskSupport.js), which would otherwise overwrite it.
    docRef: task?.reference || "",
    cost: task?.cost?.typed != null ? String(task.cost.typed) : "",
    visitCost: task?.visit_cost != null ? String(task.visit_cost) : "",
    modes: new Set((task?.failure_modes || []).map((m) => m.id)),
    ...restorationForm(task),
    ...supportForm(task),
    onReplace: task?.on_replace?.set || "",
    // What raises it besides (or instead of) its interval: a reading past a limit, an event logged
    // (taskTrigger.js). A response's trigger is its failure mode's, never changed here.
    trig: triggerState(task && !responseKindOf(task) ? task : null),
    // A response added here: its failure mode, its labour (hours and trade) and its part.
    respMode: "", hours: "", trade: "", spare: "", spareQty: "1",
    // A corrective response: the cost of the failure itself (the failure mode's own figures).
    fail: { failure_cost: "", downtime_hours: "", downtime_rate: "" },
  };
}

// When the item is replaced: restart the schedule or keep it (backend/maintenance/restart.py). Short
// words; "" is the default, named ("Restart (default)"), with why in the field's help.
function onReplaceOptions(task) {
  const d = task?.on_replace;
  const word = (v) => (v === "restart" ? "Restart" : "Keep");
  return [
    { value: "", label: d ? `${word(d.default)} (default)` : "Default" },
    { value: "restart", label: "Restart" },
    { value: "keep", label: "Keep" },
  ];
}

// The trades this task's labour uses with no rate yet: a box each, saved with the task.
function RateBoxes({ trades, rates, onRates, disabled }) {
  if (!trades.length) return null;
  return (
    <div className="mt-rates" role="group" aria-label="Trade rates">
      <p className="field-help">No rate yet for {trades.join(", ")}: an hourly rate prices that trade on every task.</p>
      {trades.map((t) => (
        <Field key={t} label={`${t} (${workspaceCurrency()} an hour)`} className="mt-rate">
          <TextInput type="number" min="0" step="any" inputMode="decimal" value={rates[t] ?? ""} disabled={disabled}
                     aria-label={`Hourly rate for ${t}`} onChange={(e) => onRates({ ...rates, [t]: e.target.value })} />
        </Field>
      ))}
    </div>
  );
}

// When a saved task is next due, the same as its Next due cell in the table (Derryn, 23 Nov 2026:
// blank when we don't know, never a date from today or from running 24 h a day): one plain line.
function DueBasis({ task, positionId = null, root = null }) {
  const n = nextOf(task);
  const c = dueCell(n);
  const byUse = (task.limits || []).find((l) => l.basis);
  const noDuty = byUse && noDutyBasis(byUse.basis) && positionId;
  return (
    <p className="field-help mt-due-line" role="note">
      <strong>Next due:</strong>{" "}
      {n.on ? <span className={n.overdue ? "pk-overdue" : undefined}>{c.words}{n.overdue ? " · overdue" : ""}</span>
        : n.at_reading != null ? c.words : "not known"}
      {n.on && n.at_reading != null ? ` (${readingWords(n)})` : ""}
      {!n.on && n.why ? ` (${n.why.charAt(0).toLowerCase()}${n.why.slice(1)})` : ""}.
      {noDuty ? <> <Link to={dutyHref(positionId, root)}>Set a duty</Link>.</> : null}
    </p>
  );
}

// The counters on a position, by unit ("hours", "km"): which units of use its tasks can count.
const counterUnits = (pos) => (pos?.measurements || []).filter((p) => p.kind === "counter").map((p) => p.unit);

export default function MaintenanceTask({ row, taskId = null, taskName = "", head = null, headingRef = null, uses = null, onBack, onDone,
  onOptimise = null, needsOpen = false, section = null, respond = null }) {
  const location = useLocation();
  const confirm = useConfirm();
  const adding = !taskId;
  const [loaded, setLoaded] = useState({ key: null, task: null, data: null, modes: [], counters: [], costs: null, error: null });
  // What it needs: a section of the form, folded until asked for (or opened by an address with ?needs=1).
  const [needsShown, setNeedsShown] = useState(needsOpen);
  const needsRef = useRef(null);
  // The extras' fold-outs: Cost, Labour, Parts (and a corrective response's failure cost); `section`
  // (a sub-item clicked in the tree, ?msec=) opens one.
  const [folds, setFolds] = useState(() => (section ? { [section]: true } : {}));
  const foldRefs = { cost: useRef(null), labour: useRef(null), parts: useRef(null) };
  const [f, setF] = useState(() => startFrom(null));
  const [rates, setRates] = useState({});
  const [attempt, setAttempt] = useState(0); // Try again after a failed load
  const key = `${row.key}:${taskId || (respond ? `resp:${respond.kind}:${respond.mode || ""}` : "new")}`;

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const data = taskId ? await getTaskLsa(taskId) : null;
        const task = data ? data.task : null;
        // A position's failure modes (to say which the task prevents) and its counters (the units it can count).
        const posId = task ? (task.subject?.kind === "position" ? task.subject.id : null) : (row.type === "pos" ? row.key : null);
        const pos = posId ? await getMaintenancePosition(posId) : null;
        const modeId = task ? responseKindOf(task) && task.trigger.failure_mode_id : respond?.kind === "failure" ? respond.mode : null;
        const costs = modeId && responseKindOf(task || { trigger: { kind: respond?.kind } }) === "failure"
          ? await getFailureModeCosts(modeId).catch(() => null) : null;
        if (!live) return;
        setLoaded({ key, task, data, modes: pos?.failure_modes || [], counters: counterUnits(pos), costs, error: null });
        const start = startFrom(task);
        if (respond && !task) start.respMode = respond.mode || (pos?.failure_modes || [])[0]?.id || "";
        if (costs?.own) start.fail = Object.fromEntries(Object.entries(costs.own).map(([k, v]) => [k, v == null ? "" : String(v)]));
        setF(start);
        setRates({});
      } catch (e) {
        if (live) setLoaded({ key, task: null, data: null, modes: [], counters: [], costs: null, error: e });
      }
    })();
    return () => { live = false; };
  }, [key, attempt]); // eslint-disable-line react-hooks/exhaustive-deps

  const task = loaded.key === key ? loaded.task : null;
  const needs = useNeeds(loaded.key === key ? loaded.data : null);
  useEffect(() => {
    if (needsOpen && needs.ready) setTimeout(() => needsRef.current?.scrollIntoView({ block: "start" }), 0);
  }, [needsOpen, needs.ready]);
  useEffect(() => {
    if (!section) return;
    setFolds((x) => ({ ...x, [section]: true }));
    if (needs.ready) setTimeout(() => foldRefs[section]?.current?.scrollIntoView({ block: "start" }), 0);
  }, [section, needs.ready]); // eslint-disable-line react-hooks/exhaustive-deps
  const ready = loaded.key === key && !loaded.error;
  const rcm = !!task && fromRcm(task);
  // A response: "failure" (corrective) or "found" (follow-on), saved or being added.
  const resp = task ? responseKindOf(task) : respond?.kind || null;
  const set = (k) => (e) => setF((x) => ({ ...x, [k]: e.target.value }));
  // How often: interval and unit mirror it, for what reads them (its restoration fields).
  const setHow = (how) => setF((x) => ({ ...x, how, interval: how.every, unit: how.unit }));
  const flip = (id) => setF((x) => { const m = new Set(x.modes); if (m.has(id)) m.delete(id); else m.add(id); return { ...x, modes: m }; });
  const missing = task?.cost?.lsa?.missing_rates?.filter((t) => t !== "no trade") || [];
  const restoreProblem = !resp && f.outcome === "fixed_interval" && !f.supporting ? restorationProblem(f) : null;
  const supportable = !resp && canSupport(f.outcome);
  const supportIssue = supportable ? supportProblem(f) : null;
  const eventOnly = !resp && f.trig.mode === "event" && !f.trig.withInterval;
  const howProblem = resp || eventOnly ? null : howOftenProblem(f.how);
  const trigProblem = resp ? "" : triggerWhy(f.trig);
  const failProblem = Object.values(f.fail).every(validMoney) ? null : "Enter the failure's figures as numbers, 0 or more.";
  const respProblem = resp && adding ? (!f.respMode ? "Pick the failure mode it answers." : !validMoney(f.hours) ? "Enter the hours, 0 or more." : null) : null;
  const can = ready && !!f.name.trim() && !tooLong(f.name) && !howProblem && validMoney(f.cost) && validMoney(f.visitCost)
    && Object.values(rates).every(validMoney) && !restoreProblem && !supportIssue && !failProblem && !respProblem && !trigProblem;
  const subject = { kind: row.type === "loc" ? "location" : "position", id: row.key, name: row.ref?.name };

  // The failure's own figures, when changed (on the failure mode: failure_costs.py).
  const saveFailCost = async (modeId) => {
    const own = loaded.costs?.own || {};
    const body = {};
    for (const [k, v] of Object.entries(f.fail)) if ((own[k] ?? null) !== num(v)) body[k] = num(v);
    if (modeId && Object.keys(body).length) await updateFailureMode(modeId, body);
  };

  const send = useSendOnce(async () => {
    for (const [trade, rate] of Object.entries(rates)) if (rate !== "") await setTradeRate(trade, Number(rate));
    if (resp && adding) {
      // A failure mode's response (responses.py): made with what's done, its labour, cost and part.
      const made = await setModeResponse(f.respMode, resp, {
        name: f.name.trim(),
        labour: Number(f.hours) > 0 ? [{ trade: f.trade.trim(), people: 1, hours: Number(f.hours) }] : [],
        cost: num(f.cost),
        spares: f.spare.trim() ? [{ name: f.spare.trim(), qty: Number(f.spareQty) || 1 }] : [],
      });
      if (resp === "failure") await saveFailCost(f.respMode);
      onDone(`Added ${made?.name || f.name.trim()}.`, made?.id || null);
      return;
    }
    const ids = [...f.modes];
    const how = resp ? {} : taskBody(f.how, taskAnchor(task, workspaceToday()));
    // Its trigger, when changed (a response's is its failure mode's, never changed here).
    const trigNow = resp ? null : triggerBody(f.trig);
    const trigChanged = !resp && JSON.stringify(trigNow) !== JSON.stringify(triggerBody(triggerState(task)));
    // What the RCM owns (its kind of task) isn't sent for an RCM task, nor a response's (its trigger says it).
    const fields = { name: f.name.trim(), ...how, ...(rcm || resp ? {} : { outcome: f.outcome || null }) };
    const needed = adding ? {} : needs.body();
    if (adding) {
      const made = await createSubjectTask(subject, {
        ...fields, also_interval: how.also_interval || null, rule: how.rule || null, source: f.source, reference: f.docRef,
        ...(ids.length && subject.kind === "position" ? { failure_mode_ids: ids } : {}),
      });
      if (f.cost !== "") await updateMaintenanceTask(made.id, { cost: Number(f.cost) });
      const extra = restorationBody(null, f);
      if (Object.keys(extra).length) await updateMaintenanceTask(made.id, extra);
      // Keeps it on its life: after its failure modes are linked (it supports only modes it serves).
      const sup = supportable ? supportBody(null, f, { modes: subject.kind === "position" ? ids : [], unit: f.unit }) : {};
      if (Object.keys(sup).length) await updateMaintenanceTask(made.id, sup);
      onDone(`Added ${made.name}.`, made.id);
      return;
    }
    await updateMaintenanceTask(task.id, {
      ...fields, ...needed, ...(rcm || resp ? {} : { source: f.source, reference: f.docRef }),
      ...(trigChanged ? { trigger: trigNow } : {}),
      ...((task.cost?.typed ?? null) !== num(f.cost) ? { cost: num(f.cost) } : {}),
      ...(!task.package && (task.visit_cost ?? null) !== num(f.visitCost) ? { visit_cost: num(f.visitCost) } : {}),
    });
    if (resp === "failure") await saveFailCost(task.trigger.failure_mode_id);
    if (resp) {
      onDone(`Saved ${f.name.trim()}.`, task.id);
      return;
    }
    // What it leaves the item as, how it's counted, its age at a shutdown: after its kind is saved.
    const extra = restorationBody(task, f);
    if (Object.keys(extra).length) await updateMaintenanceTask(task.id, extra);
    if (!rcm) {
      const had = new Set((task.failure_modes || []).map((m) => m.id));
      for (const id of ids) if (!had.has(id)) await linkTaskFailureMode(task.id, id);
      for (const id of had) if (!f.modes.has(id)) await unlinkTaskFailureMode(task.id, id);
    }
    // Keeps it on its life (after its failure modes, which it may name): a kind that can't be
    // supporting (a check) clears it.
    const served = rcm ? (task.failure_modes || []).map((m) => m.id) : ids;
    const sup = supportBody(task, supportable ? f : { ...f, supporting: false }, { modes: served, unit: f.unit });
    if (Object.keys(sup).length) await updateMaintenanceTask(task.id, sup);
    if ((f.onReplace || null) !== (task.on_replace?.set || null)) await updateMaintenanceTask(task.id, { on_replace: f.onReplace || null });
    // A new interval: the same task on identical positions may be brought in line (offered first).
    if (Number(f.interval) !== Number(task.interval) || f.unit !== task.unit) {
      setTwinCheck({ taskId: task.id, name: f.name.trim(), interval: Number(f.interval), unit: f.unit });
      return;
    }
    onDone(`Saved ${f.name.trim()}.`, task.id);
  }, can);
  const [twinCheck, setTwinCheck] = useState(null);

  const retire = async () => {
    const ok = await confirm({
      title: "Retire this task?", body: `“${task.name}” stops falling due and raising work orders. It stays in the history.`,
      confirmLabel: "Retire the task", pendingLabel: "Retiring…", failedWhat: "retire it",
      run: () => retireMaintenanceTask(task.id, "").then(() => true),
    });
    if (ok) onDone(`Retired ${task.name}.`, null);
  };

  // The panel's title: the task's name (as saved), or what's being added; under it, where it's from.
  const top = (title, sub = null) => (
    <div className="rw-panel-top">
      {head}
      {/* On a page of its own (no panel head, so no ×): the way back to the list. */}
      {!head && onBack && <button type="button" className="link pk-back" onClick={onBack} disabled={send.busy}>← All tasks here</button>}
      <h2 className="rw-panel-title" tabIndex={-1} ref={headingRef}>{title}</h2>
      {sub && <p className="rw-inside mt-from">{sub}</p>}
    </div>
  );
  const named = task?.name || taskName || "Maintenance task";
  const addTitle = resp ? (resp === "failure" ? "Add what's done if it fails" : "Add what's done when it's found")
    : `Add a task to ${row.ref?.name || "this row"}`;
  if (twinCheck) {
    return (
      <div className="mt-form">
        {top(twinCheck.name)}
        <div className="rw-pbody pk-panel mt-pane">
          <p className="field-help" role="status">Saved {twinCheck.name}.</p>
          <TaskTwins {...twinCheck}
                     onDone={(said) => onDone(said ? `Saved ${twinCheck.name}. ${said}` : `Saved ${twinCheck.name}.`, twinCheck.taskId)} />
        </div>
      </div>
    );
  }
  if (loaded.key === key && loaded.error) {
    return (
      <div className="mt-form">
        {top(adding ? addTitle : named)}
        <div className="rw-pbody pk-panel mt-pane">
          <LoadFailed what={adding ? "Couldn't load this position's failure modes." : "Couldn't load the task."} error={loaded.error}
                      onRetry={() => setAttempt((n) => n + 1)} />
        </div>
      </div>
    );
  }
  if (!ready) {
    return (
      <div className="mt-form">
        {top(adding ? addTitle : named)}
        <div className="rw-pbody pk-panel mt-pane">
          <Loading shape="fields" rows={4} label={adding ? "Loading…" : "Loading the task…"} />
        </div>
      </div>
    );
  }
  const onPosition = subject.kind === "position";
  const units = taskUnitChoices({ place: !onPosition || taskUnits(subject.kind).length < 5, counters: loaded.counters, form: f.how });
  const modes = loaded.modes;
  // The next dates it gives: from when it was last done, else from today.
  const today = workspaceToday();
  const preview = resp ? null : previewFor(f.how, { from: task?.last_done || today, after: !!task?.last_done, anchor: taskAnchor(task, today),
    positionId: onPosition ? subject.id : null, count: 3 });
  const showNeeds = () => {
    setNeedsShown(true);
    setTimeout(() => needsRef.current?.scrollIntoView({ block: "start", behavior: "smooth" }), 0);
  };
  const firstMode = rcm ? (task.failure_modes || [])[0] : null;
  const rcmPath = task ? explorerHere(location.pathname, location.search, {
    sel: task.subject?.id, tab: "rcm", ...(firstMode ? { fm: rcmTaskKey(firstMode.id, task.id) } : {}),
  }) : null;
  const nameNote = lengthNote(f.name, undefined, "say how in its LSA");
  const lsaCost = task?.cost?.lsa?.amount;
  const respModeName = resp ? (task?.trigger?.failure_mode?.text || modes.find((m) => m.id === f.respMode)?.text || "") : "";
  // Under the title: where it came from. An RCM task: what the RCM owns, read-only, and the way there.
  const sub = adding ? null : rcm ? (
    <>
      From RCM: {(task.failure_modes || []).map((m) => m.text).join(", ") || "its decision"} · {kindLabel(task.outcome)} ·{" "}
      <Link to={rcmPath} className="mt-rcm-link">Open in RCM ›</Link>
    </>
  ) : resp ? `Failure mode: ${respModeName}` : fromText({ ...task, modes: task.failure_modes });
  const replaceField = task && task.subject?.kind === "position" && !task.on_event && !resp ? {
    value: f.onReplace,
    node: (
      <Field label="When the item is replaced" help={task.on_replace?.restarted_on && (f.onReplace || task.on_replace.default) === "restart"
        ? `Restarted when the item was fitted on ${formatDate(task.on_replace.restarted_on)}.`
        : `Restart counts again from the new item; keep runs on.${task.on_replace?.why ? ` Default here: ${task.on_replace.why}.` : ""}`}>
        <Select value={f.onReplace} onChange={(v) => setF((x) => ({ ...x, onReplace: v }))} options={onReplaceOptions(task)}
                ariaLabel="When the item is replaced" className="mt-onreplace" />
      </Field>
    ),
  } : null;
  const labourSum = needs.ready ? labourWords(needs.draft.labour) : labourWords(Number(f.hours) > 0 ? [{ hours: f.hours, trade: f.trade }] : []);
  const partSum = needs.ready ? partWords(needs.draft.spares) : partWords(f.spare.trim() ? [{ name: f.spare, qty: f.spareQty }] : []);
  // The cost in force while folded: typed, or (nothing typed) its LSA's, said so.
  const costSum = costWords(f.cost, task?.package ? null : f.visitCost)
    || (lsaCost != null ? `${money(lsaCost)} each time, from its LSA` : "");
  const failSum = resp === "failure" ? usedText(loaded.costs?.used) && Object.values(f.fail).some((v) => v !== "")
    ? Object.entries(f.fail).filter(([, v]) => v !== "").map(([k, v]) => figureText(k, Number(v))).join(" · ") : "" : "";
  return (
    <form className="mt-form" aria-label={adding ? (resp ? addTitle : "Add a task") : `Task: ${task.name}`}
          onSubmit={(e) => { e.preventDefault(); send.submit(); }}>
      {top(adding ? addTitle : task.name, sub)}
      <div className="rw-pbody pk-panel mt-pane">
        {/* 1. Kind of task: the RCM's own is in the line under the title (edited in RCM only). */}
        {resp ? (
          <Field label="Kind of task">
            <p className="mt-fixed">{RESPONSE_KIND[resp]}</p>
          </Field>
        ) : !rcm && (
          <Field label="Kind of task">
            <Select value={f.outcome} onChange={(v) => setF((x) => ({ ...x, outcome: v }))} options={KINDS}
                    ariaLabel="Kind of task" className="mt-kind" />
          </Field>
        )}
        {resp && adding && (
          <Field label="Failure mode" error={modes.length ? null : "This position has no failure modes yet: add one on its RCM tab first."}>
            <Select value={f.respMode} onChange={(v) => setF((x) => ({ ...x, respMode: v }))} ariaLabel="Failure mode" className="mt-kind"
                    options={modes.map((m) => ({ value: m.id, label: m.text }))} />
          </Field>
        )}
        {/* 2. What's done: the action alone. */}
        <Field label="What's done" error={nameNote?.over ? nameNote.text : null}
               count={nameNote && !nameNote.over ? nameNote.text : null}>
          <TextInput autoFocus={adding} value={f.name} onChange={set("name")} placeholder={resp === "failure" ? "e.g. Replace the drive belt" : "e.g. Inspect the guard"} />
        </Field>
        {/* 3. How often: one line; a response is raised by its event instead. */}
        {resp ? (
          <Section title="When" className="ruled mt-sec">
            <p className="mt-fixed">{responseTrigger(resp, respModeName)}. Next due: none (raised by the event, not on a date).</p>
          </Section>
        ) : (
          <Section title="How often" className="ruled mt-sec"
                   action={onOptimise ? { label: "Optimise…", quiet: true, onClick: onOptimise, ariaLabel: `Optimise how often to do ${task.name}`, disabled: send.busy } : null}>
            <TaskSchedule value={f.how} onChange={setHow} units={units} shutdowns={onPosition} disabled={send.busy}
                          problem={howProblem} preview={preview} replace={replaceField}
                          trigger={task ? { task, state: f.trig, set: (trig) => setF((x) => ({ ...x, trig })) } : null} />
            {trigProblem && f.trig.mode === "event" && <p className="field-error" role="alert">{trigProblem}</p>}
            {task && <DueBasis task={task} positionId={task.subject?.kind === "position" ? task.subject.id : null}
                               root={new URLSearchParams(location.search).get("root")} />}
            {task && rcm && firstMode && !eventOnly && <RcmBasis modeId={firstMode.id} task={task} to={rcmPath} />}
            {task && <RestsOn taskId={task.id} onOptimise={onOptimise} />}
            {f.outcome === "fixed_interval" && <More summary="How replace at age is counted">{AGE_NOTE}</More>}
          </Section>
        )}
        {supportable && (
          <SupportFields f={f} setF={setF} task={task} problem={supportIssue}
                         modes={rcm ? (task.failure_modes || []) : modes.filter((m) => f.modes.has(m.id))} />
        )}
        {!resp && f.outcome === "fixed_interval" && (
          <RestorationFields f={f} setF={setF} task={task} problem={restoreProblem} />
        )}
        {/* Why it's done: a task added directly says it here (an RCM task's is the RCM's). */}
        {!rcm && !resp && (
          <Section title="Why it's done" className="ruled mt-sec">
            <Field label="Reason" optional>
              <NativeSelect value={f.source} onChange={set("source")}>
                {Object.entries(SOURCE_WORDS).map(([k, l]) => <option key={k} value={k}>{l[0].toUpperCase() + l.slice(1)}</option>)}
              </NativeSelect>
            </Field>
            <Field label="Reference" optional>
              <TextInput value={f.docRef} onChange={set("docRef")} placeholder="e.g. Owner's manual §7, AS 1851 table 5" />
            </Field>
            {modes.length > 0 && (
              <Field as="fieldset" label="Failure modes it prevents" optional className="mt-modes">
                {modes.map((m) => (
                  <Checkbox key={m.id} checked={f.modes.has(m.id)} onChange={() => flip(m.id)} label={m.text} />
                ))}
              </Field>
            )}
          </Section>
        )}
        {/* The optional extras, each folded with a line saying what's set. */}
        <TaskExtras className="ruled mt-sec" open={folds} onToggle={(k, o) => setFolds((x) => ({ ...x, [k]: o }))} items={[
          { key: "cost", title: "Cost", summary: costSum, ref: foldRefs.cost, id: "task-cost", body: (
            <>
              <Field label={`Each time (${workspaceCurrency()})`} optional
                     help={adding ? "Blank: worked out from its labour and parts." : null}>
                <TextInput type="number" inputMode="decimal" min="0" step="any" value={f.cost} onChange={set("cost")}
                           placeholder={lsaCost != null ? `${money(lsaCost)} from its LSA` : "e.g. 180"} />
              </Field>
              {!adding && (
                <p className="field-help" role="note">
                  <strong>{task.cost?.amount != null ? `${money(task.cost.amount)} each time. ` : ""}</strong>
                  {costWhere(task.cost)}{" "}
                  {f.cost !== "" && lsaCost != null ? `Clear the box to use its LSA's ${money(lsaCost)}.` : ""}
                </p>
              )}
              {!adding && f.cost === "" && <RateBoxes trades={missing} rates={rates} onRates={setRates} disabled={send.busy} />}
              {/* A task in no package is a visit of its own: its call-out and setup (backend/maintenance/visit_costs.py). */}
              {!adding && !task.package && !resp && (
                <Field label={`Call-out and setup each time (${workspaceCurrency()})`} optional help="Counted in the forecast's planned cost.">
                  <TextInput type="number" inputMode="decimal" min="0" step="any" value={f.visitCost} onChange={set("visitCost")} />
                </Field>
              )}
              {!adding && task.package && (
                <p className="field-help" role="note">Done on {task.package.name}&apos;s visits: their call-out is set on the package.</p>
              )}
            </>
          ) },
          { key: "labour", title: "Labour", summary: labourSum, ref: foldRefs.labour, id: "task-labour", body: (
            <>
              {needs.ready ? <LabourRows data={loaded.data} needs={needs} disabled={send.busy} /> : (
                <div className="mt-restore-row">
                  <Field label="Hours">
                    <QuantityInput label="Hours" value={f.hours} onChange={(v) => setF((x) => ({ ...x, hours: v }))} suffix="h" chars={5} />
                  </Field>
                  <Field label="Trade" optional>
                    <TextInput value={f.trade} onChange={set("trade")} placeholder="e.g. Mechanic" maxLength={200} />
                  </Field>
                </div>
              )}
              {adding && !resp && <p className="field-help">Add its labour once it&apos;s saved.</p>}
            </>
          ) },
          { key: "parts", title: "Parts", summary: partSum, ref: foldRefs.parts, id: "task-parts", body: (
            <>
              {needs.ready ? <SparesRows data={loaded.data} needs={needs} disabled={send.busy} /> : resp ? (
                <div className="mt-restore-row">
                  <Field label="Part" optional>
                    <TextInput value={f.spare} onChange={set("spare")} placeholder="e.g. Drive belt" maxLength={200} />
                  </Field>
                  <Field label="Quantity">
                    <QuantityInput label="Quantity" value={f.spareQty} onChange={(v) => setF((x) => ({ ...x, spareQty: v }))} suffix="×" chars={3} />
                  </Field>
                </div>
              ) : <p className="field-help">Add its parts once it&apos;s saved.</p>}
            </>
          ) },
          resp === "failure" ? { key: "failure", title: "Cost of the failure itself (besides the repair)", summary: failSum, id: "task-failure-cost", body: (
            <>
              <div className="mt-restore-row">
                {costFields().map((c) => (
                  <Field key={c.key} label={c.key === "failure_cost" ? "Or a failure's whole cost, typed" : c.label} optional
                         help={c.key === "failure_cost" ? "Overrides the repair's cost above." : null}>
                    <QuantityInput label={c.label} value={f.fail[c.key]} suffix={c.suffix} chars={7}
                                   placeholder={loaded.costs ? placeholderFor(c.key, loaded.costs).replace(/^Not set$/, "") : ""}
                                   onChange={(v) => setF((x) => ({ ...x, fail: { ...x.fail, [c.key]: v } }))} />
                  </Field>
                ))}
              </div>
              {loaded.costs && <p className="field-help" role="note">{usedText(loaded.costs.used)}</p>}
              {failProblem && <p className="field-error" role="alert">{failProblem}</p>}
            </>
          ) } : null,
        ]} />
        {!adding && !resp && (
          <p className="field-help mt-rcm-uses">The RCM uses its cost. <button type="button" className="link" onClick={showNeeds}>What else it needs</button></p>
        )}
        {task && needs.ready && (
          <div ref={needsRef}>
            <NeedsSection data={loaded.data} needs={needs} open={needsShown} onToggle={() => setNeedsShown((o) => !o)} disabled={send.busy} />
          </div>
        )}
        {respProblem && f.name.trim() && <p className="field-error" role="alert">{respProblem}</p>}
        {uses}
        {send.error && <p className="field-error" role="alert">{send.error}</p>}
      </div>
      {/* The shared footer: Save and Cancel; Retire… as red text at the right (it asks first). */}
      <div className="rw-panel-acts mt-acts">
        <span className="mt-acts-main">
          <button type="submit" disabled={!can || send.busy}>{send.busy ? "Saving…" : adding ? (resp ? "Add" : "Add task") : "Save"}</button>
          <button type="button" className="secondary" onClick={onBack} disabled={send.busy}>Cancel</button>
        </span>
        {!adding && !rcm && <button type="button" className="ghost rw-del" onClick={(e) => { if (e.detail < 2) retire(); }} disabled={send.busy}>Retire…</button>}
      </div>
    </form>
  );
}

// A task from an RCM decision: what its interval rests on, the same one line as the RCM tab's
// "Interval based on" (intervalBasis.js), from the calculation saved with its decision. The
// calculation itself opens in place there (it's the decision's evidence), so the way is a link.
function RcmBasis({ modeId, task, to }) {
  const [got, setGot] = useState(null);
  const [headline, setHeadline] = useState(null);
  useEffect(() => {
    let live = true;
    getFailureModeIntervalInputs(modeId, task.id).then((g) => {
      if (!live) return;
      setGot(g || {});
      if (g?.evidence?.type === "strategy_analysis") getStrategyAnalysis(g.evidence.id).then((a) => live && setHeadline(a?.headline || null), () => {});
    }, () => live && setGot({}));
    return () => { live = false; };
  }, [modeId, task.id]);
  if (!got) return null;
  const line = basisLine(task, got, got.evidence ? { artifact_name: got.evidence.name, headline } : null);
  return (
    <p className="field-help mt-basis" role="note">
      <strong>Interval based on:</strong> {line.text}{" "}
      <Link to={to} className="mt-rcm-link">{line.worked ? "Change in RCM ›" : "Work it out in RCM ›"}</Link>
    </p>
  );
}

// What the task's interval rests on (an Optimise saved as its evidence): the model, linked, and a
// word when that model has been refitted since, so its optimum may have moved (never changed by itself).
function RestsOn({ taskId, onOptimise }) {
  const [rows, setRows] = useState([]);
  useEffect(() => {
    let live = true;
    getTaskIntervalBasis(taskId).then((d) => live && setRows(d.rests_on || []), () => live && setRows([]));
    return () => { live = false; };
  }, [taskId]);
  if (!rows.length) return null;
  return (
    <div className="mt-rests" role="note">
      {rows.map((r) => (
        <p key={r.failure_mode_id} className="field-help">
          {r.use ? `Every ${every(r.use.value, r.use.unit)}` : "Its interval"} rests on{" "}
          {r.model && !r.model.gone ? <Link to={r.model.path}>{r.model.name}</Link> : <Link to={`/strategy/analyses/${encodeURIComponent(r.analysis.id)}`}>{r.analysis.name}</Link>}
          {rows.length > 1 ? ` (${r.mode})` : ""}.
          {r.moved && (
            <span className="mt-moved"> ! The model has been refitted since: its optimum may have moved.
              {onOptimise && <> <button type="button" className="link" onClick={onOptimise}>Re-optimise…</button></>}
            </span>
          )}
        </p>
      ))}
    </div>
  );
}

// Long guidance folded under one short line (progressive disclosure): the line says what's inside.
function More({ summary, children }) {
  return (
    <details className="mt-more">
      <summary>{summary}</summary>
      <p className="field-help">{children}</p>
    </details>
  );
}

// What a replace-or-restore task leaves the item as (as new, or part of its age taken away, with
// every Nth task a full replacement), whether its interval counts running hours, and its age limit
// at a shutdown. A repairable RBD built on the position reads these (its Maintenance plan).
function RestorationFields({ f, setF, task, problem }) {
  const set = (k) => (e) => setF((x) => ({ ...x, [k]: e.target.value }));
  const r = task?.restoration;
  const calendar = ["days", "weeks", "months", "years"].includes(f.unit);
  return (
    <Section title="What it leaves the item as" className="ruled mt-sec mt-restore">
      {f.supporting ? (
        <p className="field-help" role="note">It keeps the item on its life (above): it restores none of its age.</p>
      ) : (
        <Field label="After the task">
          <NativeSelect value={f.restoreKind} onChange={set("restoreKind")}>
            {RESTORE_CHOICES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </NativeSelect>
        </Field>
      )}
      {!f.supporting && f.restoreKind !== "as_new" && (
        <div className="mt-restore-row">
          <Field label="Restores (% of the age)">
            <TextInput type="number" inputMode="decimal" min="0" max="100" step="any" value={f.restores} onChange={set("restores")}
                       placeholder="e.g. 70" />
          </Field>
          <Field label="Every Nth task is a full replacement" optional>
            <TextInput type="number" inputMode="numeric" min="2" max="100" step="1" value={f.replaceEvery} onChange={set("replaceEvery")}
                       placeholder="e.g. 3" />
          </Field>
          {f.replaceEvery !== "" && (
            <Field label={`Replacement cost (${workspaceCurrency()})`} optional>
              <TextInput type="number" inputMode="decimal" min="0" step="any" value={f.replacementCost} onChange={set("replacementCost")} />
            </Field>
          )}
        </div>
      )}
      {!f.supporting && <p className="field-help" role="note">
        {f.restoreKind === "as_new"
          ? "The item is as good as new after each task (replaced, or fully overhauled)."
          : `An overhaul that takes away ${f.restores || "X"}% of ${f.restoreKind === "kijima1" ? "the age gained since the last task" : "its whole age"}: 100% is as good as new, 0% as old as before.`}
        {f.replaceEvery !== "" && f.replacementCost === "" ? " With no replacement cost, a replacement is charged nothing until you set one." : ""}
      </p>}
      {!f.supporting && r?.source === "assumed" && (
        <p className="field-help" role="note">
          Not set yet: taken as restoring none of its age, as servicing work (greasing, cleaning, adjusting) usually
          does, so the forecast counts no failures off for it. Choose As new if it replaces or fully restores the item.
        </p>
      )}
      {!f.supporting && r?.source === "decision" && (
        <p className="field-help" role="note">
          Its failure modes&apos; decisions set this for themselves ({r.by_mode.map((x) => `${x.text}: ${x.words}`).join("; ")}).
          {r.conflict ? " They disagree: an RBD takes the least restoring." : ""} Saving here sets it for every failure mode it serves.
        </p>
      )}
      {calendar && (
        <div className="mt-check">
          <Checkbox checked={f.runningHours} onChange={(e) => setF((x) => ({ ...x, runningHours: e.target.checked }))}
                    label="Counted in running hours" />
          <More summary="What this changes">
            Every {f.interval || "N"} {f.unit} of running, not of the calendar. An RBD turns it into calendar time through the
            block&apos;s Runs %; its due dates here stay on the calendar.
          </More>
        </div>
      )}
      <div className="mt-restore-row">
        <Field label="Only if older than" optional help="At a shutdown: it's replaced only once it's that old.">
          <TextInput type="number" inputMode="decimal" min="0" step="any" value={f.olderThan} onChange={set("olderThan")} placeholder="—" />
        </Field>
        <Field label="Unit" className="mt-unit">
          <NativeSelect value={f.olderUnit} onChange={set("olderUnit")}>{["days", "weeks", "months", "years"].map((u) => <option key={u} value={u}>{u}</option>)}</NativeSelect>
        </Field>
      </div>
      {problem && <p className="field-error" role="alert">{problem}</p>}
    </Section>
  );
}

// Keeps it on its life (a supporting task, taskSupport.js): greasing or an oil change keeps the part
// on the life its model describes rather than renewing it. What it supports (the failure modes it
// prevents, ticked above, or its whole life), the interval the life model assumes, the optional
// impact if it isn't done (failure rate × k), grace, and where the impact comes from ("Assumed"
// by default, shown as a chip), or fitted from history (SupportFit). Used in what-ifs and when its interval runs
// past the reference.
function SupportFields({ f, setF, task, problem, modes }) {
  const set = (k) => (e) => setF((x) => ({ ...x, [k]: e.target.value }));
  const flip = (id) => setF((x) => { const m = new Set(x.supports); if (m.has(id)) m.delete(id); else m.add(id); return { ...x, supports: m }; });
  const combined = task?.support?.combined;
  const chip = f.k !== "" ? <Chip tone={f.supportSource === "assumed" ? "warning" : "neutral"}>{SOURCE_WORD[f.supportSource] || "Assumed"}</Chip> : null;
  return (
    <Section title="Keeps it on its life" className="ruled mt-sec mt-support" aside={f.supporting ? chip : null}>
      <Checkbox checked={f.supporting} label="Supporting: it keeps the item on its life (greasing, an oil change)"
                onChange={(e) => setF((x) => ({ ...x, supporting: e.target.checked, reference: x.reference || (e.target.checked ? String(x.interval || "") : "") }))} />
      {!f.supporting && <p className="field-help">{SUPPORT_HELP}</p>}
      {f.supporting && (
        <>
          {modes.length > 0 ? (
            <Field as="fieldset" label="What it supports" optional help="None ticked: the part's whole life." className="mt-modes">
              {modes.map((m) => <Checkbox key={m.id} checked={f.supports.has(m.id)} onChange={() => flip(m.id)} label={m.text} />)}
            </Field>
          ) : (
            <p className="field-help">It supports the part&apos;s whole life. Link a failure mode it prevents to name one instead.</p>
          )}
          <div className="mt-restore-row">
            <Field label={`Reference interval (${f.unit})`} help="The interval the life model assumes.">
              <TextInput type="number" inputMode="decimal" min="0" step="any" value={f.reference} onChange={set("reference")}
                         placeholder={String(f.interval || "")} />
            </Field>
            <Field label="If it isn't done: failure rate ×" optional help="Blank: supports, no modelled impact.">
              <TextInput type="number" inputMode="decimal" min="1" max="100" step="any" value={f.k} onChange={set("k")} placeholder="e.g. 2" />
            </Field>
            <Field label="Grace (% overdue)" optional help="Overdue by more than this before the impact applies.">
              <TextInput type="number" inputMode="decimal" min="0" max="100" step="any" value={f.grace} onChange={set("grace")} placeholder="0" />
            </Field>
          </div>
          {f.k !== "" && (
            <div className="mt-restore-row">
              <Field label="Where the impact comes from">
                <NativeSelect value={f.supportSource} onChange={set("supportSource")}>
                  {SUPPORT_SOURCES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </NativeSelect>
              </Field>
              <Field label="Note" optional>
                <TextInput value={f.supportNote} onChange={set("supportNote")} placeholder="e.g. Maker's manual §4.2" />
              </Field>
            </div>
          )}
          {task?.id && task.support && <SupportFit taskId={task.id} onUse={(use) => setF((x) => withFit(x, use))} />}
          <p className="field-help" role="note">
            {impactWords(f.k === "" ? null : { k: f.k })}: the forecast uses it in what-ifs, and when its interval runs past the
            reference. {COMBINE_HELP}
            {combined ? ` On this part, with ${combined.tasks.filter((t) => t.id !== task.id).map((t) => `${t.name} (× ${t.k})`).join(", ")}: × ${combined.k} if none is done.` : ""}
          </p>
        </>
      )}
      {problem && <p className="field-error" role="alert">{problem}</p>}
    </Section>
  );
}

// Fit the impact from history (forecast plan step 9; support_fit.py): k with its 90% two-sided range from the
// items where the task holds the life up, "not shown to matter" when the range includes 1, or why it can't be
// estimated (service timing barely varies, too few failures). "Use this" fills the fields (source Fitted, the
// fit kept as evidence); Save keeps it, as with any change.
function SupportFit({ taskId, onUse }) {
  const [fit, setFit] = useState({ busy: false, data: null, error: null });
  const go = () => {
    setFit({ busy: true, data: null, error: null });
    getSupportFit(taskId).then((data) => setFit({ busy: false, data, error: null }),
      (e) => setFit({ busy: false, data: null, error: e.message }));
  };
  const d = fit.data;
  const fmt = (v) => (v == null ? "∞" : Number(v).toLocaleString("en-GB", { maximumSignificantDigits: 2 }));
  return (
    <div className="mt-fit">
      <button type="button" className="secondary sm" onClick={go} disabled={fit.busy}>
        {fit.busy ? "Fitting from history…" : "Fit the impact from history…"}
      </button>
      {fit.error && <p className="field-error" role="alert">Couldn&apos;t fit it: {fit.error}</p>}
      {d && (
        <div className="mt-fit-out" role="status">
          <p className={d.identifiable ? "" : "mt-fit-gap"}>{d.words}</p>
          {d.identifiable && (
            <p className="field-help">
              {d.method}. Failure rate × {fmt(d.k)} while overdue (90% two-sided: {fmt(d.range?.[0])} to {fmt(d.range?.[1])}),
              from {d.exposure?.failures} failures, {Math.round((d.exposure?.overdue_share || 0) * 100)}% of the time overdue.
              {d.group && <> A plain comparison of failures per hour gives × {fmt(d.group.k)}.</>}
            </p>
          )}
          {d.history && <p className="field-help">{d.history.items} items, {d.history.services} times done, by {d.history.clock || "—"}.</p>}
          {d.use && (
            <button type="button" className="secondary sm" onClick={() => onUse(d.use)}>
              {d.use.impact ? `Use × ${d.use.impact.k} (Fitted)` : "Use: supports, no modelled impact"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// Every trade's hourly rate, in the panel beside the tree (?rates=1 on the Maintenance tab):
// the rates set, and the trades the tasks' labour uses with none yet. Each saves when it's left.
export function TradeRates({ onBack = null, onChanged }) {
  const [state, setState] = useState({ rates: null, error: null });
  const [draft, setDraft] = useState({});
  const [said, setSaid] = useState(null);
  const load = () => listTradeRates().then((d) => setState({ rates: d.rates, error: null }), (e) => setState({ rates: null, error: e }));
  useEffect(() => { load(); }, []);
  const save = async (r) => {
    const v = draft[r.trade];
    if (v === undefined || (v === "" ? null : Number(v)) === r.rate || !validMoney(v)) return;
    try {
      await setTradeRate(r.trade, v === "" ? null : Number(v));
      setSaid(`Saved the rate for ${r.trade}.`);
      await load();
      onChanged();
    } catch (e) {
      setSaid(e.message);
    }
  };
  return (
    <div className="pk-view mt-pane" role="region" aria-label="Trade rates">
      {onBack && (
        <>
          <button type="button" className="link pk-back" onClick={onBack}>← All tasks here</button>
          <h3 className="pk-view-name">Trade rates</h3>
        </>
      )}
      <p className="lib-date">An hourly rate for each trade prices the labour in every task&apos;s LSA, and so its cost each time. Leave one blank to leave that trade unpriced.</p>
      {said && <p className="lib-date" role="status">{said}</p>}
      {state.error && <LoadFailed what="Couldn't load the trade rates." error={state.error} onRetry={load} />}
      {!state.rates && !state.error && <Loading shape="fields" rows={3} label="Loading the trade rates…" />}
      {state.rates?.length === 0 && <p className="lib-date">No trades yet: they come from the labour in the tasks&apos; LSA.</p>}
      {state.rates?.length > 0 && (
        <ul className="pk-members mt-rate-list">
          {state.rates.map((r) => (
            <li key={r.trade} className="pk-member">
              <div className="pk-member-main">
                <span className="pk-member-name">{r.trade}</span>
                <span className="lib-date pk-sub">{r.tasks ? `${r.tasks} task${r.tasks === 1 ? "" : "s"}` : "No tasks use it"}</span>
              </div>
              <label className="lsa-num">{workspaceCurrency()} an hour
                <input type="number" min="0" step="any" inputMode="decimal" aria-label={`Hourly rate for ${r.trade}`}
                       value={draft[r.trade] ?? (r.rate ?? "")} onChange={(e) => setDraft({ ...draft, [r.trade]: e.target.value })}
                       onBlur={() => save(r)} onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }} />
              </label>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

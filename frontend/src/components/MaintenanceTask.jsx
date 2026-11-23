import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { noDutyBasis, dutyHref } from "../explorerOperations.js";
import {
  createSubjectTask, getMaintenancePosition, getTaskIntervalBasis, getTaskLsa, linkTaskFailureMode, listTradeRates, retireMaintenanceTask,
  setTradeRate, unlinkTaskFailureMode, updateMaintenanceTask,
} from "../api.js";
import { fmtDate, today as workspaceToday, useSendOnce } from "./MaintenanceParts.jsx";
import Field from "./ui/Field.jsx";
import { Checkbox, Select as NativeSelect, TextInput } from "./ui/Controls.jsx";
import Section from "./ui/Section.jsx";
import Select from "./Select.jsx";
import LoadFailed from "./LoadFailed.jsx";
import Loading from "./ui/Loading.jsx";
import HowOften from "./HowOften.jsx";
import { formFromTask, howOftenProblem, previewFor, taskAnchor, taskBody } from "../howOften.js";
import { useConfirm } from "./ConfirmProvider.jsx";
import { costWhere, fromRcm, fromText, money, SOURCE_WORDS } from "../lsaTab.js";
import { taskUnits } from "../maintenanceSubjects.js";
import { AGE_NOTE, lengthNote, tooLong } from "../maintenanceText.js";
import { explorerHere } from "../products.js";
import { workspaceCurrency } from "../money.js";
import TaskTwins from "./TaskTwins.jsx";
import NeedsSection, { useNeeds } from "./TaskNeeds.jsx";
import { every } from "../taskOptimise.js";
import { restorationBody, restorationForm, restorationProblem, RESTORE_CHOICES } from "../taskRestoration.js";

// A task on the Explorer's Maintenance tab, in the panel beside the tree (never a dialog):
// "Add task" (?addtask=<the row>) and a task opened from the table (?mtask=<id>). It draws the
// panel's title (the task's name), its body in Sections, and the footer with Save, Cancel and
// Retire…; TaskSide gives it the panel's head (× and Expand are the way out). The RCM says what
// is done: a task's name is the action alone ("Replace the seal"), and how it's done is its LSA.
//
//   Add task:   name, how often (HowOften: every N unit, a pattern, a second limit), what kind, why it's done (own practice, the maker,
//               a law or standard, other) and a reference, the failure modes it prevents
//               (optional, a position's), and what it costs each time (optional).
//   A task:     the same fields, saved together. A task from an RCM decision keeps its
//               failure modes and reason on the RCM tab (a link says so). Its cost: typed
//               here, or from its LSA at the trade rates (a trade with no rate gets a box
//               for one, used by every task). "Retire…" for a task added directly.

// The words of each kind: a short name (so the closed picker fits a phone) and the rest as its hint.
const KINDS = [
  { value: "", label: "Routine work", hint: "Lubricate, clean, adjust, inspect" },
  { value: "fixed_interval", label: "Replace at age", hint: "Every … since it was last done" },
  { value: "failure_finding", label: "Check a hidden function", hint: "Failure-finding" },
  { value: "on_condition", label: "Check condition" },
];

const num = (v) => (v === "" || v == null ? null : Number(v));
const validMoney = (v) => v === "" || (Number.isFinite(Number(v)) && Number(v) >= 0);

// What the form starts from: a task's fields, or blanks for a new one.
function startFrom(task) {
  return {
    name: task?.name || "", interval: task?.interval != null ? String(task.interval) : "", unit: task?.unit || "months",
    how: formFromTask(task),
    outcome: task?.outcome || "", source: task && !fromRcm(task) ? task.source : "manual", reference: task?.reference || "",
    cost: task?.cost?.typed != null ? String(task.cost.typed) : "",
    visitCost: task?.visit_cost != null ? String(task.visit_cost) : "",
    modes: new Set((task?.failure_modes || []).map((m) => m.id)),
    ...restorationForm(task),
  };
}

// The trades this task's labour uses with no rate yet: a box each, saved with the task.
function RateBoxes({ trades, rates, onRates, disabled }) {
  if (!trades.length) return null;
  return (
    <div className="mt-rates" role="group" aria-label="Trade rates">
      <p className="field-help">Its labour has no rate for {trades.join(", ")}. An hourly rate prices that trade on every task.</p>
      {trades.map((t) => (
        <Field key={t} label={`${t} (${workspaceCurrency()} an hour)`} className="mt-rate">
          <TextInput type="number" min="0" step="any" inputMode="decimal" value={rates[t] ?? ""} disabled={disabled}
                     aria-label={`Hourly rate for ${t}`} onChange={(e) => onRates({ ...rates, [t]: e.target.value })} />
        </Field>
      ))}
    </div>
  );
}

// When a saved task by use is next due and where that date comes from: the moment the meter reaches
// its next reading through the position's operating plan (and the stop after it), or the meter's
// recent rate. Calendar limits need no words (the dates show under How often).
function DueBasis({ task, positionId = null, root = null }) {
  const lines = (task.limits || []).filter((l) => l.basis && (l.next_due || l.note));
  if (!lines.length) return null;
  return (
    <div className="mt-due-basis" role="note">
      {lines.map((l, i) => (
        <p key={i} className="field-help">
          {l.next_due ? (
            <>Due by use {l.due_moment ? `at ${l.due_moment.slice(11)} on ${fmtDate(l.next_due)}` : `on ${fmtDate(l.next_due)}`}
              {l.due_at_reading != null ? ` (at ${l.due_at_reading.toLocaleString("en-GB")} ${l.counter?.unit || ""})` : ""}
              {l.stop_after && l.stop_after !== l.due_moment ? `; it stops at ${l.stop_after.slice(11)}${l.stop_after.slice(0, 10) !== l.next_due ? ` on ${fmtDate(l.stop_after.slice(0, 10))}` : ""}` : ""}. </>
          ) : <>{l.note[0].toUpperCase() + l.note.slice(1)}. </>}
          {l.basis.text}.
          {noDutyBasis(l.basis) && positionId ? <> <Link to={dutyHref(positionId, root)}>Set a duty in Operations</Link>.</> : null}
        </p>
      ))}
    </div>
  );
}

export default function MaintenanceTask({ row, taskId = null, taskName = "", head = null, headingRef = null, uses = null, onBack, onDone,
  onOptimise = null, needsOpen = false }) {
  const location = useLocation();
  const confirm = useConfirm();
  const adding = !taskId;
  const [loaded, setLoaded] = useState({ key: null, task: null, data: null, modes: [], error: null });
  // What it needs: a section of the form, folded until asked for (or opened by an address with ?needs=1).
  const [needsShown, setNeedsShown] = useState(needsOpen);
  const needsRef = useRef(null);
  const [f, setF] = useState(() => startFrom(null));
  const [rates, setRates] = useState({});
  const [attempt, setAttempt] = useState(0); // Try again after a failed load
  const key = `${row.key}:${taskId || "new"}`;

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const data = taskId ? await getTaskLsa(taskId) : null;
        const task = data ? data.task : null;
        // A position's failure modes, to say which the task prevents.
        const posId = task ? (task.subject?.kind === "position" ? task.subject.id : null) : (row.type === "pos" ? row.key : null);
        const modes = posId ? ((await getMaintenancePosition(posId)).failure_modes || []) : [];
        if (!live) return;
        setLoaded({ key, task, data, modes, error: null });
        setF(startFrom(task));
        setRates({});
      } catch (e) {
        if (live) setLoaded({ key, task: null, data: null, modes: [], error: e });
      }
    })();
    return () => { live = false; };
  }, [key, attempt]); // eslint-disable-line react-hooks/exhaustive-deps

  const task = loaded.key === key ? loaded.task : null;
  const needs = useNeeds(loaded.key === key ? loaded.data : null);
  useEffect(() => {
    if (needsOpen && needs.ready) setTimeout(() => needsRef.current?.scrollIntoView({ block: "start" }), 0);
  }, [needsOpen, needs.ready]);
  const ready = loaded.key === key && !loaded.error;
  const rcm = !!task && fromRcm(task);
  const set = (k) => (e) => setF((x) => ({ ...x, [k]: e.target.value }));
  // How often: interval and unit mirror it, for what reads them (its restoration fields).
  const setHow = (how) => setF((x) => ({ ...x, how, interval: how.every, unit: how.unit }));
  const flip = (id) => setF((x) => { const m = new Set(x.modes); if (m.has(id)) m.delete(id); else m.add(id); return { ...x, modes: m }; });
  const missing = task?.cost?.lsa?.missing_rates?.filter((t) => t !== "no trade") || [];
  const restoreProblem = f.outcome === "fixed_interval" ? restorationProblem(f) : null;
  const howProblem = howOftenProblem(f.how);
  const can = ready && !!f.name.trim() && !tooLong(f.name) && !howProblem && validMoney(f.cost) && validMoney(f.visitCost)
    && Object.values(rates).every(validMoney) && !restoreProblem;
  const subject = { kind: row.type === "loc" ? "location" : "position", id: row.key, name: row.ref?.name };

  const send = useSendOnce(async () => {
    for (const [trade, rate] of Object.entries(rates)) if (rate !== "") await setTradeRate(trade, Number(rate));
    const ids = [...f.modes];
    const how = taskBody(f.how, taskAnchor(task, workspaceToday()));
    const fields = { name: f.name.trim(), ...how, outcome: f.outcome || null };
    const needed = adding ? {} : needs.body();
    if (adding) {
      const made = await createSubjectTask(subject, {
        ...fields, also_interval: how.also_interval || null, rule: how.rule || null, source: f.source, reference: f.reference,
        ...(ids.length && subject.kind === "position" ? { failure_mode_ids: ids } : {}),
      });
      if (f.cost !== "") await updateMaintenanceTask(made.id, { cost: Number(f.cost) });
      const extra = restorationBody(null, f);
      if (Object.keys(extra).length) await updateMaintenanceTask(made.id, extra);
      onDone(`Added ${made.name}.`, made.id);
      return;
    }
    await updateMaintenanceTask(task.id, {
      ...fields, ...needed, ...(rcm ? {} : { source: f.source, reference: f.reference }),
      ...((task.cost?.typed ?? null) !== num(f.cost) ? { cost: num(f.cost) } : {}),
      ...(!task.package && (task.visit_cost ?? null) !== num(f.visitCost) ? { visit_cost: num(f.visitCost) } : {}),
    });
    // What it leaves the item as, how it's counted, its age at a shutdown: after its kind is saved.
    const extra = restorationBody(task, f);
    if (Object.keys(extra).length) await updateMaintenanceTask(task.id, extra);
    if (!rcm) {
      const had = new Set((task.failure_modes || []).map((m) => m.id));
      for (const id of ids) if (!had.has(id)) await linkTaskFailureMode(task.id, id);
      for (const id of had) if (!f.modes.has(id)) await unlinkTaskFailureMode(task.id, id);
    }
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
      {sub && <p className="rw-inside">{sub}</p>}
    </div>
  );
  const named = task?.name || taskName || "Maintenance task";
  const addTitle = `Add a task to ${row.ref?.name || "this row"}`;
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
  const units = taskUnits(subject.kind);
  const modes = loaded.modes;
  // The next three dates it gives: from when it was last done, else from today.
  const today = workspaceToday();
  const onPosition = subject.kind === "position";
  const preview = previewFor(f.how, { from: task?.last_done || today, after: !!task?.last_done, anchor: taskAnchor(task, today),
    positionId: onPosition ? subject.id : null });
  const showNeeds = () => {
    setNeedsShown(true);
    setTimeout(() => needsRef.current?.scrollIntoView({ block: "start", behavior: "smooth" }), 0);
  };
  const rcmPath = task ? explorerHere(location.pathname, location.search, { sel: task.subject?.id, tab: "rcm" }) : null;
  const nameNote = lengthNote(f.name, undefined, "say how in its LSA");
  const lsaCost = task?.cost?.lsa?.amount;
  return (
    <form className="mt-form" aria-label={adding ? "Add a task" : `Task: ${task.name}`}
          onSubmit={(e) => { e.preventDefault(); send.submit(); }}>
      {top(adding ? addTitle : task.name, adding ? null : fromText({ ...task, modes: task.failure_modes }))}
      <div className="rw-pbody pk-panel mt-pane">
        <Field label="Task: the action only" error={nameNote?.over ? nameNote.text : null}
               count={nameNote && !nameNote.over ? nameNote.text : null}>
          <TextInput autoFocus={adding} value={f.name} onChange={set("name")} placeholder="e.g. Inspect the guard" />
        </Field>
        <Section title="How often" className="ruled mt-sec"
                 action={onOptimise ? { label: "Optimise…", onClick: onOptimise, ariaLabel: `Optimise how often to do ${task.name}`, disabled: send.busy } : null}>
          <HowOften value={f.how} onChange={setHow} units={units} withAlso shutdowns={onPosition} disabled={send.busy}
                    problem={howProblem} preview={preview} />
          {task && <DueBasis task={task} positionId={task.subject?.kind === "position" ? task.subject.id : null}
                             root={new URLSearchParams(location.search).get("root")} />}
          {task && <RestsOn taskId={task.id} onOptimise={onOptimise} />}
        </Section>
        <Section title="What kind of task" className="ruled mt-sec">
          <Field label="What kind of task" labelHidden>
            <Select value={f.outcome} onChange={(v) => setF((x) => ({ ...x, outcome: v }))} options={KINDS}
                    ariaLabel="What kind of task" className="mt-kind" />
          </Field>
          {f.outcome === "fixed_interval" && <More summary="How replace at age is counted">{AGE_NOTE}</More>}
        </Section>
        {f.outcome === "fixed_interval" && (
          <RestorationFields f={f} setF={setF} task={task} problem={restoreProblem} />
        )}
        <Section title="Why it's done" className="ruled mt-sec">
          {rcm ? (
            <p className="field-help">
              From the RCM: its failure modes and why it&apos;s done are on the <Link to={rcmPath}>RCM tab</Link>.
            </p>
          ) : (
            <>
              <Field label="Reason" optional>
                <NativeSelect value={f.source} onChange={set("source")}>
                  {Object.entries(SOURCE_WORDS).map(([k, l]) => <option key={k} value={k}>{l[0].toUpperCase() + l.slice(1)}</option>)}
                </NativeSelect>
              </Field>
              <Field label="Reference" optional>
                <TextInput value={f.reference} onChange={set("reference")} placeholder="e.g. Owner's manual §7, AS 1851 table 5" />
              </Field>
              {modes.length > 0 && (
                <Field as="fieldset" label="Failure modes it prevents" optional className="mt-modes">
                  {modes.map((m) => (
                    <Checkbox key={m.id} checked={f.modes.has(m.id)} onChange={() => flip(m.id)} label={m.text} />
                  ))}
                </Field>
              )}
            </>
          )}
        </Section>
        <Section title="Cost" className="ruled mt-sec">
          <Field label={`Cost each time (${workspaceCurrency()})`} optional
                 help={adding ? "Leave it blank to work it out from its LSA." : null}>
            <TextInput type="number" inputMode="decimal" min="0" step="any" value={f.cost} onChange={set("cost")}
                       placeholder={lsaCost != null ? `${money(lsaCost)} from its LSA` : "e.g. 180"} />
          </Field>
          {adding ? (
            <More summary="How the cost is used">
              What it costs each time it&apos;s done. Left blank, it&apos;s worked out from its LSA (labour at trade rates, spares and
              consumables). The RCM uses this figure when it asks whether the task is worth doing.
            </More>
          ) : (
            <p className="field-help" role="note">
              <strong>{task.cost?.amount != null ? `${money(task.cost.amount)} each time. ` : ""}</strong>
              {costWhere(task.cost)}{" "}
              {f.cost !== "" && lsaCost != null ? `Clear the box to use its LSA's ${money(lsaCost)}. ` : ""}
              The RCM uses this figure. <button type="button" className="link" onClick={showNeeds}>What it needs</button>
            </p>
          )}
          {!adding && f.cost === "" && <RateBoxes trades={missing} rates={rates} onRates={setRates} disabled={send.busy} />}
          {/* A task in no package is a visit of its own: its call-out and setup (backend/maintenance/visit_costs.py). */}
          {!adding && !task.package && (
            <Field label={`Call-out and setup each time (${workspaceCurrency()})`} optional
                   help="Travel, setting up, the crew standing by: counted in the forecast's planned cost besides the task.">
              <TextInput type="number" inputMode="decimal" min="0" step="any" value={f.visitCost} onChange={set("visitCost")} />
            </Field>
          )}
          {!adding && task.package && (
            <p className="field-help" role="note">Done on {task.package.name}&apos;s visits: a visit&apos;s call-out and setup are set on the package.</p>
          )}
        </Section>
        {task && needs.ready && (
          <div ref={needsRef}>
            <NeedsSection data={loaded.data} needs={needs} open={needsShown} onToggle={() => setNeedsShown((o) => !o)} disabled={send.busy} />
          </div>
        )}
        {uses}
        {send.error && <p className="field-error" role="alert">{send.error}</p>}
      </div>
      {/* The shared footer: Save and Cancel; Retire… as red text at the right (it asks first). */}
      <div className="rw-panel-acts mt-acts">
        <span className="mt-acts-main">
          <button type="submit" disabled={!can || send.busy}>{send.busy ? "Saving…" : adding ? "Add task" : "Save"}</button>
          <button type="button" className="secondary" onClick={onBack} disabled={send.busy}>Cancel</button>
        </span>
        {!adding && !rcm && <button type="button" className="ghost rw-del" onClick={(e) => { if (e.detail < 2) retire(); }} disabled={send.busy}>Retire…</button>}
      </div>
    </form>
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
      <Field label="After the task">
        <NativeSelect value={f.restoreKind} onChange={set("restoreKind")}>
          {RESTORE_CHOICES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </NativeSelect>
      </Field>
      {f.restoreKind !== "as_new" && (
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
      <p className="field-help" role="note">
        {f.restoreKind === "as_new"
          ? "The item is as good as new after each task (replaced, or fully overhauled)."
          : `An overhaul that takes away ${f.restores || "X"}% of ${f.restoreKind === "kijima1" ? "the age gained since the last task" : "its whole age"}: 100% is as good as new, 0% as old as before.`}
        {f.replaceEvery !== "" && f.replacementCost === "" ? " With no replacement cost, a replacement is charged nothing until you set one." : ""}
      </p>
      {r?.source === "assumed" && (
        <p className="field-help" role="note">
          Not set yet: taken as restoring none of its age, as servicing work (greasing, cleaning, adjusting) usually
          does, so the forecast counts no failures off for it. Choose As new if it replaces or fully restores the item.
        </p>
      )}
      {r?.source === "decision" && (
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

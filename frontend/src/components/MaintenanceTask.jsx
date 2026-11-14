import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  createSubjectTask, getMaintenancePosition, getTaskLsa, linkTaskFailureMode, listTradeRates, retireMaintenanceTask,
  setTradeRate, unlinkTaskFailureMode, updateMaintenanceTask,
} from "../api.js";
import { Field, today as workspaceToday, useSendOnce } from "./MaintenanceParts.jsx";
import HowOften from "./HowOften.jsx";
import { formFromTask, howOftenPreview, howOftenProblem, taskAnchor, taskBody } from "../howOften.js";
import { useConfirm } from "./ConfirmProvider.jsx";
import { costWhere, fromRcm, fromText, money, SOURCE_WORDS } from "../lsaTab.js";
import { taskUnits } from "../maintenanceSubjects.js";
import { AGE_NOTE, tooLong } from "../maintenanceText.js";
import { explorerHere } from "../products.js";
import { workspaceCurrency } from "../money.js";
import TaskTwins from "./TaskTwins.jsx";
import { restorationBody, restorationForm, restorationProblem, RESTORE_CHOICES } from "../taskRestoration.js";

// A task on the Explorer's Maintenance tab, in the panel beside the tree (never a dialog):
// "Add task" (?addtask=<the row>) and a task opened from the table (?mtask=<id>), each with
// a back link to the table. The RCM says what is done: a task's name is the action alone
// ("Replace the seal"), and how it's done is its LSA (the LSA tab).
//
//   Add task:   name, how often (HowOften: every N unit, a pattern, a second limit), what kind, why it's done (own practice, the maker,
//               a law or standard, other) and a reference, the failure modes it prevents
//               (optional, a position's), and what it costs each time (optional).
//   A task:     the same fields, saved together. A task from an RCM decision keeps its
//               failure modes and reason on the RCM tab (a link says so). Its cost: typed
//               here, or from its LSA at the trade rates (a trade with no rate gets a box
//               for one, used by every task). "Retire…" for a task added directly.

const KINDS = [
  ["", "Routine work (lubricate, clean, adjust, inspect)"],
  ["fixed_interval", "Replace at age (every … since it was last done)"],
  ["failure_finding", "Check a hidden function (failure-finding)"],
  ["on_condition", "Check condition"],
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
    modes: new Set((task?.failure_modes || []).map((m) => m.id)),
    ...restorationForm(task),
  };
}

// The trades this task's labour uses with no rate yet: a box each, saved with the task.
function RateBoxes({ trades, rates, onRates, disabled }) {
  if (!trades.length) return null;
  return (
    <div className="mt-rates" role="group" aria-label="Trade rates">
      <p className="lib-date">Its labour has no rate for {trades.join(", ")}. An hourly rate prices that trade on every task.</p>
      {trades.map((t) => (
        <label key={t} className="lsa-num mt-rate">
          {t} ({workspaceCurrency()} an hour)
          <input type="number" min="0" step="any" inputMode="decimal" value={rates[t] ?? ""} disabled={disabled}
                 aria-label={`Hourly rate for ${t}`} onChange={(e) => onRates({ ...rates, [t]: e.target.value })} />
        </label>
      ))}
    </div>
  );
}

export default function MaintenanceTask({ row, taskId = null, onBack, onDone }) {
  const location = useLocation();
  const confirm = useConfirm();
  const adding = !taskId;
  const [loaded, setLoaded] = useState({ key: null, task: null, modes: [], error: null });
  const [f, setF] = useState(() => startFrom(null));
  const [rates, setRates] = useState({});
  const key = `${row.key}:${taskId || "new"}`;

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const task = taskId ? (await getTaskLsa(taskId)).task : null;
        // A position's failure modes, to say which the task prevents.
        const posId = task ? (task.subject?.kind === "position" ? task.subject.id : null) : (row.type === "pos" ? row.key : null);
        const modes = posId ? ((await getMaintenancePosition(posId)).failure_modes || []) : [];
        if (!live) return;
        setLoaded({ key, task, modes, error: null });
        setF(startFrom(task));
        setRates({});
      } catch (e) {
        if (live) setLoaded({ key, task: null, modes: [], error: e.message });
      }
    })();
    return () => { live = false; };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  const task = loaded.key === key ? loaded.task : null;
  const ready = loaded.key === key && !loaded.error;
  const rcm = !!task && fromRcm(task);
  const set = (k) => (e) => setF((x) => ({ ...x, [k]: e.target.value }));
  // How often: interval and unit mirror it, for what reads them (its restoration fields).
  const setHow = (how) => setF((x) => ({ ...x, how, interval: how.every, unit: how.unit }));
  const flip = (id) => setF((x) => { const m = new Set(x.modes); if (m.has(id)) m.delete(id); else m.add(id); return { ...x, modes: m }; });
  const missing = task?.cost?.lsa?.missing_rates?.filter((t) => t !== "no trade") || [];
  const restoreProblem = f.outcome === "fixed_interval" ? restorationProblem(f) : null;
  const howProblem = howOftenProblem(f.how);
  const can = ready && !!f.name.trim() && !tooLong(f.name) && !howProblem && validMoney(f.cost)
    && Object.values(rates).every(validMoney) && !restoreProblem;
  const subject = { kind: row.type === "loc" ? "location" : "position", id: row.key, name: row.ref?.name };

  const send = useSendOnce(async () => {
    for (const [trade, rate] of Object.entries(rates)) if (rate !== "") await setTradeRate(trade, Number(rate));
    const ids = [...f.modes];
    const how = taskBody(f.how, taskAnchor(task, workspaceToday()));
    const fields = { name: f.name.trim(), ...how, outcome: f.outcome || null };
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
      ...fields, ...(rcm ? {} : { source: f.source, reference: f.reference }),
      ...((task.cost?.typed ?? null) !== num(f.cost) ? { cost: num(f.cost) } : {}),
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

  const back = <button type="button" className="link pk-back" onClick={onBack} disabled={send.busy}>← All tasks here</button>;
  if (twinCheck) {
    return (
      <div className="pk-view mt-pane">
        {back}
        <p className="lib-date" role="status">Saved {twinCheck.name}.</p>
        <TaskTwins {...twinCheck}
                   onDone={(said) => onDone(said ? `Saved ${twinCheck.name}. ${said}` : `Saved ${twinCheck.name}.`, twinCheck.taskId)} />
      </div>
    );
  }
  if (loaded.key === key && loaded.error) return <div>{back}<div className="card error">Couldn&apos;t load the task: {loaded.error}</div></div>;
  if (!ready) return <div>{back}<p className="lib-date">Loading…</p></div>;
  const units = taskUnits(subject.kind);
  const modes = loaded.modes;
  // The next three dates it gives: from when it was last done, else from today.
  const today = workspaceToday();
  const shown = howOftenPreview(f.how, { from: task?.last_done || today, after: !!task?.last_done, anchor: taskAnchor(task, today) });
  const lsaPath = task ? explorerHere(location.pathname, location.search, { sel: task.subject?.id, tab: "lsa", task: task.id }) : null;
  const rcmPath = task ? explorerHere(location.pathname, location.search, { sel: task.subject?.id, tab: "rcm" }) : null;
  return (
    <form className="pk-view mt-pane" aria-label={adding ? "Add a task" : `Task: ${task.name}`}
          onSubmit={(e) => { e.preventDefault(); send.submit(); }}>
      {back}
      <h3 className="pk-view-name">{adding ? `Add a task to ${row.ref?.name || "this row"}` : task.name}</h3>
      {!adding && <p className="lib-date pk-sub">{fromText({ ...task, modes: task.failure_modes })}</p>}
      <div className="mt-fields">
        <Field label="Task: the action only" text={f.name} hint="say how in its LSA">
          <input autoFocus={adding} value={f.name} onChange={set("name")} placeholder="e.g. Inspect the guard" />
        </Field>
        <fieldset className="mt-how">
          <legend>How often</legend>
          <HowOften value={f.how} onChange={setHow} units={units} withAlso disabled={send.busy} problem={howProblem}
                    dates={shown.dates} datesLead={shown.lead} datesAfter={shown.after} datesNote={shown.note} />
        </fieldset>
        <Field label="What kind of task">
          <select value={f.outcome} onChange={set("outcome")}>{KINDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        </Field>
        {f.outcome === "fixed_interval" && <p className="lib-date mt-note">{AGE_NOTE}</p>}
        {f.outcome === "fixed_interval" && (
          <RestorationFields f={f} setF={setF} task={task} problem={restoreProblem} />
        )}
        {rcm ? (
          <p className="lib-date mt-note">
            From the RCM: its failure modes and why it&apos;s done are on the <Link to={rcmPath}>RCM tab</Link>.
          </p>
        ) : (
          <>
            <Field label="Why it's done (optional)">
              <select value={f.source} onChange={set("source")}>
                {Object.entries(SOURCE_WORDS).map(([k, l]) => <option key={k} value={k}>{l[0].toUpperCase() + l.slice(1)}</option>)}
              </select>
            </Field>
            <Field label="Reference (optional)">
              <input value={f.reference} onChange={set("reference")} placeholder="e.g. Owner's manual §7, AS 1851 table 5" />
            </Field>
            {modes.length > 0 && (
              <fieldset className="mt-modes">
                <legend>Failure modes it prevents (optional)</legend>
                {modes.map((m) => (
                  <label key={m.id} className="mt-mode">
                    <input type="checkbox" checked={f.modes.has(m.id)} onChange={() => flip(m.id)} /> {m.text}
                  </label>
                ))}
              </fieldset>
            )}
          </>
        )}
        <Field label={`Cost each time (${workspaceCurrency()}, optional)`}>
          <input type="number" inputMode="decimal" min="0" step="any" value={f.cost} onChange={set("cost")}
                 placeholder={task?.cost?.lsa?.amount != null ? `${task.cost.lsa.amount} from its LSA` : "e.g. 180"} />
        </Field>
        <p className="lib-date mt-note" role="note">
          {adding
            ? "What it costs each time it's done. Leave it blank to work it out from its LSA (labour at trade rates, spares and consumables). The RCM uses this figure when it asks whether the task is worth doing."
            : <>
              <strong>{task.cost?.amount != null ? `${money(task.cost.amount)} each time. ` : ""}</strong>
              {costWhere(task.cost)}{" "}
              {f.cost !== "" && task.cost?.lsa?.amount != null ? `Clear the box to use its LSA's ${money(task.cost.lsa.amount)}. ` : ""}
              The RCM uses this figure. <Link to={lsaPath}>What it needs (LSA)</Link>
            </>}
        </p>
        {!adding && f.cost === "" && <RateBoxes trades={missing} rates={rates} onRates={setRates} disabled={send.busy} />}
      </div>
      {send.error && <p className="field-error" role="alert">{send.error}</p>}
      <div className="mt-actions">
        <button type="submit" disabled={!can || send.busy}>{send.busy ? "Saving…" : adding ? "Add task" : "Save"}</button>
        <button type="button" className="secondary" onClick={onBack} disabled={send.busy}>Cancel</button>
        {!adding && !rcm && <button type="button" className="link mt-retire" onClick={retire} disabled={send.busy}>Retire…</button>}
      </div>
    </form>
  );
}

// What a replace-or-restore task leaves the item as (as new, or part of its age taken away, with
// every Nth task a full replacement), whether its interval counts running hours, and its age limit
// at a shutdown. A repairable RBD built on the position reads these (its Maintenance plan).
function RestorationFields({ f, setF, task, problem }) {
  const set = (k) => (e) => setF((x) => ({ ...x, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));
  const r = task?.restoration;
  const calendar = ["days", "weeks", "months", "years"].includes(f.unit);
  return (
    <fieldset className="mt-restore">
      <legend>What it leaves the item as</legend>
      <Field label="After the task">
        <select value={f.restoreKind} onChange={set("restoreKind")}>
          {RESTORE_CHOICES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      </Field>
      {f.restoreKind !== "as_new" && (
        <div className="maint-row mt-restore-row">
          <Field label="Restores (% of the age)">
            <input type="number" inputMode="decimal" min="0" max="100" step="any" value={f.restores} onChange={set("restores")}
                   placeholder="e.g. 70" />
          </Field>
          <Field label="Every Nth task is a full replacement (optional)">
            <input type="number" inputMode="numeric" min="2" max="100" step="1" value={f.replaceEvery} onChange={set("replaceEvery")}
                   placeholder="e.g. 3" />
          </Field>
          {f.replaceEvery !== "" && (
            <Field label={`Replacement cost (${workspaceCurrency()}, optional)`}>
              <input type="number" inputMode="decimal" min="0" step="any" value={f.replacementCost} onChange={set("replacementCost")} />
            </Field>
          )}
        </div>
      )}
      <p className="lib-date mt-note" role="note">
        {f.restoreKind === "as_new"
          ? "The item is as good as new after each task (replaced, or fully overhauled)."
          : `An overhaul that takes away ${f.restores || "X"}% of ${f.restoreKind === "kijima1" ? "the age gained since the last task" : "its whole age"}: 100% is as good as new, 0% as old as before.`}
        {f.replaceEvery !== "" && f.replacementCost === "" ? " With no replacement cost, a replacement is charged nothing until you set one." : ""}
      </p>
      {r?.source === "decision" && (
        <p className="lib-date mt-note" role="note">
          Its failure modes&apos; decisions set this for themselves ({r.by_mode.map((x) => `${x.text}: ${x.words}`).join("; ")}).
          {r.conflict ? " They disagree: an RBD takes the least restoring." : ""} Saving here sets it for every failure mode it serves.
        </p>
      )}
      {calendar && (
        <>
          <label className="mt-mode">
            <input type="checkbox" checked={f.runningHours} onChange={set("runningHours")} /> Counted in running hours
          </label>
          <p className="lib-date mt-note">
            Every {f.interval || "N"} {f.unit} of running, not of the calendar. An RBD turns it into calendar time through the
            block&apos;s Runs %; its due dates here stay on the calendar.
          </p>
        </>
      )}
      <div className="maint-row mt-restore-row">
        <Field label="At a shutdown, only if older than (optional)">
          <input type="number" inputMode="decimal" min="0" step="any" value={f.olderThan} onChange={set("olderThan")} placeholder="—" />
        </Field>
        <Field label="Unit">
          <select value={f.olderUnit} onChange={set("olderUnit")}>{["days", "weeks", "months", "years"].map((u) => <option key={u} value={u}>{u}</option>)}</select>
        </Field>
      </div>
      <p className="lib-date mt-note">Used when its work package is a shutdown: the item is replaced at a shut only once it&apos;s that old.</p>
      {problem && <p className="field-error" role="alert">{problem}</p>}
    </fieldset>
  );
}

// Every trade's hourly rate, in the panel beside the tree (?rates=1 on the Maintenance tab):
// the rates set, and the trades the tasks' labour uses with none yet. Each saves when it's left.
export function TradeRates({ onBack, onChanged }) {
  const [state, setState] = useState({ rates: null, error: null });
  const [draft, setDraft] = useState({});
  const [said, setSaid] = useState(null);
  const load = () => listTradeRates().then((d) => setState({ rates: d.rates, error: null }), (e) => setState({ rates: null, error: e.message }));
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
      <button type="button" className="link pk-back" onClick={onBack}>← All tasks here</button>
      <h3 className="pk-view-name">Trade rates</h3>
      <p className="lib-date">An hourly rate for each trade prices the labour in every task&apos;s LSA, and so its cost each time. Leave one blank to leave that trade unpriced.</p>
      {said && <p className="lib-date" role="status">{said}</p>}
      {state.error && <div className="card error">{state.error}</div>}
      {!state.rates && !state.error && <p className="lib-date">Loading…</p>}
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

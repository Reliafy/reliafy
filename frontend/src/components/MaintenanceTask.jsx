import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  createSubjectTask, getMaintenancePosition, getTaskLsa, linkTaskFailureMode, listTradeRates, retireMaintenanceTask,
  setTradeRate, unlinkTaskFailureMode, updateMaintenanceTask,
} from "../api.js";
import { Field, useSendOnce } from "./MaintenanceParts.jsx";
import { useConfirm } from "./ConfirmProvider.jsx";
import { costWhere, fromRcm, fromText, money, SOURCE_WORDS } from "../lsaTab.js";
import { taskUnits } from "../maintenanceSubjects.js";
import { tooLong } from "../maintenanceText.js";
import { explorerHere } from "../products.js";
import { workspaceCurrency } from "../money.js";

// A task on the Explorer's Maintenance tab, in the panel beside the tree (never a dialog):
// "Add task" (?addtask=<the row>) and a task opened from the table (?mtask=<id>), each with
// a back link to the table. The RCM says what is done: a task's name is the action alone
// ("Replace the seal"), and how it's done is its LSA (the LSA tab).
//
//   Add task:   name, every N unit, what kind, why it's done (own practice, the maker,
//               a law or standard, other) and a reference, the failure modes it prevents
//               (optional, a position's), and what it costs each time (optional).
//   A task:     the same fields, saved together. A task from an RCM decision keeps its
//               failure modes and reason on the RCM tab (a link says so). Its cost: typed
//               here, or from its LSA at the trade rates (a trade with no rate gets a box
//               for one, used by every task). "Retire…" for a task added directly.

const KINDS = [
  ["", "Routine work (lubricate, clean, adjust, inspect)"],
  ["fixed_interval", "Replace or restore at the interval"],
  ["failure_finding", "Check a hidden function (failure-finding)"],
  ["on_condition", "Check condition"],
];

const num = (v) => (v === "" || v == null ? null : Number(v));
const validMoney = (v) => v === "" || (Number.isFinite(Number(v)) && Number(v) >= 0);

// What the form starts from: a task's fields, or blanks for a new one.
function startFrom(task) {
  return {
    name: task?.name || "", interval: task?.interval != null ? String(task.interval) : "", unit: task?.unit || "months",
    outcome: task?.outcome || "", source: task && !fromRcm(task) ? task.source : "manual", reference: task?.reference || "",
    cost: task?.cost?.typed != null ? String(task.cost.typed) : "",
    modes: new Set((task?.failure_modes || []).map((m) => m.id)),
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
  const flip = (id) => setF((x) => { const m = new Set(x.modes); if (m.has(id)) m.delete(id); else m.add(id); return { ...x, modes: m }; });
  const missing = task?.cost?.lsa?.missing_rates?.filter((t) => t !== "no trade") || [];
  const can = ready && !!f.name.trim() && !tooLong(f.name) && Number(f.interval) > 0 && validMoney(f.cost)
    && Object.values(rates).every(validMoney);
  const subject = { kind: row.type === "loc" ? "location" : "position", id: row.key, name: row.ref?.name };

  const send = useSendOnce(async () => {
    for (const [trade, rate] of Object.entries(rates)) if (rate !== "") await setTradeRate(trade, Number(rate));
    const ids = [...f.modes];
    const fields = { name: f.name.trim(), interval: Number(f.interval), unit: f.unit, outcome: f.outcome || null };
    if (adding) {
      const made = await createSubjectTask(subject, {
        ...fields, source: f.source, reference: f.reference,
        ...(ids.length && subject.kind === "position" ? { failure_mode_ids: ids } : {}),
      });
      if (f.cost !== "") await updateMaintenanceTask(made.id, { cost: Number(f.cost) });
      onDone(`Added ${made.name}.`, made.id);
      return;
    }
    await updateMaintenanceTask(task.id, {
      ...fields, ...(rcm ? {} : { source: f.source, reference: f.reference }),
      ...((task.cost?.typed ?? null) !== num(f.cost) ? { cost: num(f.cost) } : {}),
    });
    if (!rcm) {
      const had = new Set((task.failure_modes || []).map((m) => m.id));
      for (const id of ids) if (!had.has(id)) await linkTaskFailureMode(task.id, id);
      for (const id of had) if (!f.modes.has(id)) await unlinkTaskFailureMode(task.id, id);
    }
    onDone(`Saved ${f.name.trim()}.`, task.id);
  }, can);

  const retire = async () => {
    const ok = await confirm({
      title: "Retire this task?", body: `“${task.name}” stops falling due and raising work orders. It stays in the history.`,
      confirmLabel: "Retire the task", pendingLabel: "Retiring…", failedWhat: "retire it",
      run: () => retireMaintenanceTask(task.id, "").then(() => true),
    });
    if (ok) onDone(`Retired ${task.name}.`, null);
  };

  const back = <button type="button" className="link pk-back" onClick={onBack} disabled={send.busy}>← All tasks here</button>;
  if (loaded.key === key && loaded.error) return <div>{back}<div className="card error">Couldn&apos;t load the task: {loaded.error}</div></div>;
  if (!ready) return <div>{back}<p className="lib-date">Loading…</p></div>;
  const units = taskUnits(subject.kind);
  const modes = loaded.modes;
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
        <Field label="Every">
          <div className="maint-row mt-every">
            <input type="number" inputMode="decimal" min="0" step="any" value={f.interval} onChange={set("interval")} aria-label="Interval" />
            <select value={f.unit} onChange={set("unit")} aria-label="Interval unit">{units.map((u) => <option key={u} value={u}>{u}</option>)}</select>
          </div>
        </Field>
        <Field label="What kind of task">
          <select value={f.outcome} onChange={set("outcome")}>{KINDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        </Field>
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

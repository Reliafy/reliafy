import { useEffect, useId, useRef, useState } from "react";
import { CloseIcon } from "./icons.jsx";
import { unitAbbr } from "./rbdModelText.js";
import { costLabel, workspaceCurrency } from "../money.js";
import {
  RESTORATIONS, TASKS, costText, dutyText, dutyWords, fmt, hasDuty, intervalBasis, operatingAllowed, parseCost,
  parseDuty, parseNumber, planColumns, planCounts, planRows, rowProblems, schedule, setCrewPriority, setDuty,
  setGroup, setInterval, setIntervalBasis, setScheduleField, setTask, toCalendar,
} from "../rbdMaintenancePlan.js";
import "../views/Maintenance.css";
import "./RbdMaintenancePlan.css";

// The Maintenance plan of a repairable RBD (D5: the one place its planned work is edited): a table
// under the canvas, the diagram kept in view, one row per block with its duty, its task, how often,
// how long it takes, what it costs, what it restores, its maintenance group and (with limited
// crews) its place in the crew queue, each edited where it stands. Selecting blocks on the canvas
// shows just their rows. The block dialog shows a summary with "Edit in the plan".
//
//   nodes, unit        the diagram's nodes and time unit
//   crews              limited repair crews are set (the crew column shows)
//   groupNames         the maintenance groups in use (the group field suggests them)
//   selected           ids of the component blocks selected on the canvas (filters the table)
//   onChange(id, data) a block's new data      onShowAll()  clear the selection
//   onCrewsAndGroups() open Crews and groups…  onClose()
export default function RbdMaintenancePlan({ nodes, unit = "", crews = false, groupNames = [], selected = [],
                                             onChange, onShowAll, onCrewsAndGroups, onClose }) {
  const all = planRows(nodes);
  const filtered = selected.length ? all.filter((r) => selected.includes(r.id)) : all;
  const counts = planCounts(all);
  const cols = planColumns({ crews });
  const u = unitAbbr(unit);
  const listId = useId();
  const [open, setOpen] = useState({});
  const standby = nodes.filter((n) => n.type === "standby").length;

  return (
    <section className="rbd-plan" aria-label="Maintenance plan" data-wt="rbd-plan">
      <div className="rbd-plan-head">
        <h3>Maintenance plan</h3>
        <span className="rbd-plan-counts muted">
          {counts.planned} of {counts.blocks} block{counts.blocks === 1 ? "" : "s"} with planned work
          {counts.withDuty ? ` · ${counts.withDuty} with a duty` : ""}
          {counts.problems ? ` · ${counts.problems} to finish` : ""}
        </span>
        <div className="rbd-plan-btns">
          <button type="button" className="secondary sm" onClick={onCrewsAndGroups}
                  title="Repair crews shared by planned work and repairs, and each maintenance group's set-up cost">
            Crews and groups…
          </button>
          <button type="button" className="ghost sm rw-x" onClick={onClose} aria-label="Close the maintenance plan"
                  title="Close the maintenance plan"><CloseIcon /></button>
        </div>
      </div>
      <details className="rbd-plan-duty">
        <summary><strong>Duty</strong> is the share of the time a block runs. Set it when its life is in running hours.</summary>
        <p>
          A block with a duty ages only while it runs, so its life is stretched onto the calendar: a pump that runs
          25% of the time lasts four times as long in calendar time. Planned work given in running time (every
          500 running hours) is turned into calendar time through the duty; without a duty it can't be, and the
          row says so. Repairs and planned work still take calendar time. Leave it blank for a block that runs
          all the time, or whose life was measured in calendar time.
        </p>
      </details>
      {selected.length > 0 && (
        <p className="rbd-plan-filter">
          Showing the {filtered.length === 1 ? "selected block" : `${filtered.length} selected blocks`}.{" "}
          <button type="button" className="link" onClick={onShowAll}>Show all {all.length}</button>
        </p>
      )}
      {all.length === 0 ? (
        <p className="muted rbd-plan-empty">Add a block to plan its maintenance.</p>
      ) : (
        <div className="maint-scroll rbd-plan-scroll">
          <table className="calc-table rbd-plan-table">
            <thead>
              <tr>
                <th scope="col">Block</th>
                <th scope="col" title="The share of the time it runs (blank: all the time)">Duty</th>
                <th scope="col">Task</th>
                <th scope="col" title="How often: on the calendar, or in running time through the duty">Every</th>
                <th scope="col" title="How long it takes the block off-line (blank: no downtime)">Takes</th>
                <th scope="col" title="Per task; a range like 300–700 is drawn afresh each time">{costLabel("Cost", workspaceCurrency())}</th>
                <th scope="col" title="What the task leaves the block as">Restores</th>
                <th scope="col" title="Blocks in a group share a set-up cost at each stop">Group</th>
                {cols.includes("crew") && <th scope="col" title="Its place in the repair-crew queue: higher first">Crew priority</th>}
                <th scope="col"><span className="sr-only">More</span></th>
              </tr>
            </thead>
            {filtered.map((r) => (
              <PlanRow key={r.id} row={r} unit={unit} u={u} crews={cols.includes("crew")} listId={listId}
                       open={!!open[r.id]} onToggle={() => setOpen((o) => ({ ...o, [r.id]: !o[r.id] }))}
                       onChange={(data) => onChange(r.id, data)} />
            ))}
          </table>
          <datalist id={listId}>{groupNames.map((g) => <option value={g} key={g} />)}</datalist>
        </div>
      )}
      <p className="muted rbd-plan-note">
        Every task leaves the block as good as new.{" "}
        {standby ? "Standby groups take no planned work, so they aren't listed. " : ""}
        Times are in {unit ? unit.toLowerCase() : "the diagram's unit"}; the Calculator splits downtime and cost into planned and unplanned.
      </p>
    </section>
  );
}

// One block: its row, then (when open) its task's extra settings, then what's left to set.
function PlanRow({ row, unit, u, crews, listId, open, onToggle, onChange }) {
  const { data, task } = row;
  const s = schedule(data) || {};
  const problems = rowProblems(data, unit);
  const preventive = task !== "none" && task !== "test";
  // Running time can be chosen before a number is typed, so the row remembers the choice until then.
  const dataBasis = intervalBasis(data);
  const [basis, setBasis] = useState(dataBasis);
  useEffect(() => {
    if (dataBasis === "operating") setBasis("operating");
    else if (s.interval != null) setBasis("calendar");
  }, [dataBasis, s.interval]);
  const operating = preventive && basis === "operating";
  const modelled = s.duration != null && typeof s.duration === "object";
  const extras = task === "condition" || task === "test" || (task === "age" && data.maintenance_group);
  const name = row.label;
  const span = 9 + (crews ? 1 : 0);
  return (
    <tbody className={"rbd-plan-block" + (problems.length ? " has-problem" : "")}>
      <tr>
        <th scope="row" className="calc-row-label rbd-plan-name">{name}</th>
        <td className="rbd-plan-duty-cell">
          <span className="rbd-plan-with-suffix">
            <DraftInput value={dutyText(data.duty)} parse={parseDuty} placeholder="100" label={`${name}: duty, % of the time it runs`}
                        onCommit={(v) => onChange(setDuty(data, v))} className="rbd-plan-num rbd-plan-pct" />
            <span aria-hidden="true">%</span>
          </span>
          <small className="muted">{hasDuty(data) && data.duty < 1 ? dutyWords(data.duty, unit).replace(/^Runs \S+ of the time · /, "") : "all the time"}</small>
        </td>
        <td>
          <select value={task} aria-label={`${name}: task`} title={TASKS.find((t) => t.id === task)?.help}
                  onChange={(e) => onChange(setTask(data, e.target.value))}>
            {TASKS.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
          </select>
        </td>
        <td className="rbd-plan-every">
          {task === "none" ? <span className="muted">—</span> : (
            <>
              <span className="rbd-plan-with-suffix">
                <DraftInput value={String((operating ? s.operating_interval : s.interval) ?? "")}
                            parse={(t) => parseNumber(t, { positive: true })} placeholder="—"
                            label={`${name}: every`} className="rbd-plan-num"
                            onCommit={(v) => onChange(setInterval(data, v, operating ? "operating" : "calendar"))} />
                {preventive && operatingAllowed(unit) ? (
                  <select value={operating ? "operating" : "calendar"} aria-label={`${name}: interval in`}
                          className="rbd-plan-basis" onChange={(e) => { setBasis(e.target.value); onChange(setIntervalBasis(data, e.target.value)); }}>
                    <option value="calendar">{u || "calendar"}</option>
                    <option value="operating">running {u}</option>
                  </select>
                ) : <span>{u}</span>}
              </span>
              {operating && hasDuty(data) && (
                <small className="muted">= {fmt(toCalendar(Number(s.operating_interval), Number(data.duty)))} {u} on the calendar</small>
              )}
            </>
          )}
        </td>
        <td>
          {task === "none" ? <span className="muted">—</span> : modelled ? (
            <span className="muted" title="Set as a distribution (by the assistant or an import). Type a number to replace it.">modelled
              <DraftInput value="" parse={(t) => parseNumber(t)} placeholder="replace" label={`${name}: takes`}
                          className="rbd-plan-num" onCommit={(v) => v != null && onChange(setScheduleField(data, "duration", v))} />
            </span>
          ) : (
            <span className="rbd-plan-with-suffix">
              <DraftInput value={String(s.duration ?? "")} parse={(t) => parseNumber(t)} placeholder="none"
                          label={`${name}: takes`} className="rbd-plan-num"
                          onCommit={(v) => onChange(setScheduleField(data, "duration", v || null))} />
              <span>{u}</span>
            </span>
          )}
        </td>
        <td>
          {task === "none" ? <span className="muted">—</span> : (
            <DraftInput value={costText(s.cost)} parse={parseCost} placeholder="—" label={`${name}: cost per task`}
                        className="rbd-plan-cost" inputMode="decimal"
                        onCommit={(v) => onChange(setScheduleField(data, "cost", v))} />
          )}
        </td>
        <td>
          {task === "none" || task === "test"
            ? <span className="muted" title={task === "test" ? "A test finds hidden failures; the repair that follows restores the block" : undefined}>—</span>
            : <span title="A replacement leaves the block as good as new">{RESTORATIONS.as_new}</span>}
        </td>
        <td>
          {task === "test" ? <span className="muted" title="A proof-tested block can't be in a maintenance group: nobody knows it has failed when the group stops">—</span> : (
            <DraftInput value={data.maintenance_group || ""} parse={(t) => ({ value: t.trim() || null, error: null })}
                        placeholder="—" label={`${name}: maintenance group`} list={listId} type="text" className="rbd-plan-group"
                        onCommit={(v) => onChange(setGroup(data, v))} />
          )}
        </td>
        {crews && (
          <td>
            <DraftInput value={String(data.crew_priority ?? "")} placeholder="0" label={`${name}: crew priority`} className="rbd-plan-num"
                        parse={(t) => (t.trim() === "" ? { value: null, error: null } : Number.isFinite(Number(t)) ? { value: Number(t), error: null } : { value: null, error: "A number" })}
                        onCommit={(v) => onChange(setCrewPriority(data, v))} />
          </td>
        )}
        <td>
          {extras ? (
            <button type="button" className="ghost sm rbd-plan-more" aria-expanded={open} onClick={onToggle}
                    aria-label={`${name}: ${open ? "fewer" : "more"} settings`}>{open ? "Less" : "More"}</button>
          ) : null}
        </td>
      </tr>
      {open && extras && (
        <tr className="rbd-plan-extra">
          <td colSpan={span}>
            <div className="rbd-plan-pin"><ExtraFields data={data} task={task} name={name} u={u} onChange={onChange} /></div>
          </td>
        </tr>
      )}
      {problems.length > 0 && (
        <tr className="rbd-plan-problem">
          <td colSpan={span} role="status"><span className="rbd-plan-pin">{problems.join(" ")}</span></td>
        </tr>
      )}
    </tbody>
  );
}

// A task's own settings: the threshold and inspection cost of a replacement on condition, early
// renewal at a group stop, a proof test's first test, coverage and full test.
function ExtraFields({ data, task, name, u, onChange }) {
  const s = schedule(data) || {};
  const field = (key, label, hint, parse, extra = {}) => (
    <label className="rbd-plan-field">
      <span>{label}</span>
      <DraftInput value={key === "inspection_cost" ? costText(s[key]) : String(s[key] ?? "")} parse={parse}
                  placeholder="—" label={`${name}: ${label.toLowerCase()}`} className="rbd-plan-num" {...extra}
                  onCommit={(v) => onChange(setScheduleField(data, key, v))} />
      {hint && <small className="muted">{hint}</small>}
    </label>
  );
  return (
    <div className="rbd-plan-fields">
      {task === "condition" && field("threshold", "Replace above", "chance of failing before the next inspection, e.g. 0.05",
        (t) => parseNumber(t, { max: 1 }))}
      {task === "condition" && field("inspection_cost", "Cost per inspection", "optional", parseCost)}
      {task === "age" && field("opportunity", "Renew early from age", `${u} · at a stop of its group`, (t) => parseNumber(t))}
      {task === "test" && field("offset", "First test at", `${u} · stagger redundant channels`, (t) => parseNumber(t))}
      {task === "test" && field("coverage", "Coverage", "share of failures a test finds · blank = all", (t) => parseNumber(t, { max: 1 }))}
      {task === "test" && Number(s.coverage) < 1 && s.coverage != null &&
        field("full_test", "Full test every", `${u} · a multiple of the test interval`, (t) => parseNumber(t, { positive: true }))}
    </div>
  );
}

// An input that keeps what's being typed and commits only what parses ("300–" isn't a cost yet).
// It follows the value from outside unless it has the focus.
function DraftInput({ value, parse, onCommit, label, placeholder, className = "", type = "text", list, inputMode }) {
  const [text, setText] = useState(value);
  const [error, setError] = useState(null);
  const focused = useRef(false);
  useEffect(() => {
    if (!focused.current) {
      setText(value);
      setError(null);
    }
  }, [value]);
  return (
    <input type={type} value={text} placeholder={placeholder} aria-label={label} list={list}
           inputMode={inputMode || (type === "text" && !list ? "decimal" : undefined)}
           className={className + (error ? " is-invalid" : "")} aria-invalid={!!error || undefined}
           title={error || undefined}
           onFocus={() => { focused.current = true; }}
           onBlur={() => { focused.current = false; if (!error) setText(value); }}
           onChange={(e) => {
             const t = e.target.value;
             setText(t);
             const p = parse(t);
             setError(p.error);
             if (!p.error) onCommit(p.value);
           }} />
  );
}

import { useEffect, useRef, useState } from "react";
import { getTaskLsa, listMaintenanceParts, updateMaintenanceTask } from "../api.js";
import { cleanSection, kindText, modeLine, num, sectionDraft } from "../lsaTab.js";
import { whenText } from "../rcmWorksheet.js";
import { formatCost, workspaceCurrency } from "../money.js";
import { Link, useLocation } from "react-router-dom";
import { explorerHere } from "../products.js";
import { taskKey } from "../explorerRcm.js";
import LoadFailed from "./LoadFailed.jsx";
import Loading from "./ui/Loading.jsx";

// One task's LSA in the Explorer's LSA tab (?task=<id>, with a back link): the
// task's name, kind, interval, position and the failure modes it serves, then
// what doing it needs, each section saved when you leave it (✓ Saved): Labour
// (trade, people, hours), Tools and instruments (with the measuring point or
// channel an instrument reads: the sensor binding lives here, not on the RCM
// decision), Spares (from the parts register, or free text), Consumables,
// Access and downtime, Method and the task's Instructions.

const SAVED_FOR = 2500;

// A section: saves when focus leaves it (not when it moves inside it) and says so.
function Section({ title, hint, state, onLeave, children }) {
  return (
    <section className="lsa-sec" aria-label={title}
             onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) onLeave(); }}>
      <h4 className="td-sublabel lsa-sec-head">
        {title}
        {state === "saving" && <span className="lib-date lsa-state" role="status">Saving…</span>}
        {state === "saved" && <span className="lsa-state lsa-saved" role="status">✓ Saved</span>}
        {state && state.error && <span className="lsa-state lsa-err" role="alert">{state.error}</span>}
      </h4>
      {hint && <p className="lib-date lsa-hint">{hint}</p>}
      {children}
    </section>
  );
}

// One input with its label shown above it (not only a placeholder): a typed value
// can't land in a field you can't name.
function Cell({ label, className = "", children }) {
  return (
    <label className={`lsa-cell ${className}`.trim()}>
      <span className="lsa-cell-label">{label}</span>
      {children}
    </label>
  );
}

function Rows({ rows, onRows, blank, addLabel, render, label }) {
  return (
    <>
      {rows.length > 0 && (
        <ul className="lsa-rows" aria-label={label}>
          {rows.map((r, i) => (
            <li key={i} className="lsa-row">
              {render(r, (patch) => onRows(rows.map((x, j) => (j === i ? { ...x, ...patch } : x))), i)}
              <button type="button" className="link lsa-remove" aria-label={`Remove line ${i + 1}`} title="Remove this line"
                      onClick={() => onRows(rows.filter((_, j) => j !== i), true)}>✕</button>
            </li>
          ))}
        </ul>
      )}
      <button type="button" className="link lsa-add" onClick={() => onRows([...rows, { ...blank }])}>{addLabel}</button>
    </>
  );
}

const SECTIONS = ["labour", "tools", "spares", "consumables", "access", "method", "duration_hours"];
// Typing also saves once it pauses (not only when focus leaves the section), so a
// reload or a closed tab doesn't lose what was typed, and emptying a field clears it.
const TYPING_PAUSE = 1200;
// Sections saved together (the Labour section holds the elapsed time too).
const GROUP = { labour: ["labour", "duration_hours"], duration_hours: ["labour", "duration_hours"] };

export default function LsaTask({ taskId, onBack, onChanged }) {
  const location = useLocation();
  const [state, setState] = useState({ id: null, data: null, error: null });
  const [draft, setDraft] = useState(null);
  const [instructions, setInstructions] = useState("");
  const [saved, setSaved] = useState({});
  const [parts, setParts] = useState(null);
  const last = useRef({});
  const timers = useRef({});
  const typing = useRef({});
  const latest = useRef(null);

  useEffect(() => {
    let live = true;
    getTaskLsa(taskId).then((data) => {
      if (!live) return;
      setState({ id: taskId, data, error: null });
      const r = data.task.resources || {};
      const d = Object.fromEntries(SECTIONS.map((k) => [k, sectionDraft(k, r)]));
      setDraft(d);
      latest.current = d;
      setInstructions(data.task.instructions || "");
      last.current = Object.fromEntries(SECTIONS.map((k) => [k, JSON.stringify(cleanSection(k, d[k]))]));
      last.current.instructions = data.task.instructions || "";
    }).catch((e) => live && setState({ id: taskId, data: null, error: e.message }));
    return () => { live = false; };
  }, [taskId]);
  useEffect(() => () => {
    Object.values(timers.current).forEach(clearTimeout);
    Object.values(typing.current).forEach(clearTimeout);
  }, []);

  const flash = (key, value) => {
    setSaved((s) => ({ ...s, [key]: value }));
    clearTimeout(timers.current[key]);
    if (value === "saved") timers.current[key] = setTimeout(() => setSaved((s) => ({ ...s, [key]: null })), SAVED_FOR);
  };
  const save = async (key, body) => {
    flash(key, "saving");
    try {
      const view = await updateMaintenanceTask(taskId, body);
      setState((s) => (s.data ? { ...s, data: { ...s.data, task: view } } : s));
      flash(key, "saved");
      onChanged?.();
    } catch (e) {
      flash(key, { error: e.message });
    }
  };
  // Leaving a section: saved when it changed (cleaned, as the server keeps it).
  const leave = (keys, from = latest.current || draft) => {
    const changes = {};
    for (const k of keys) {
      const clean = cleanSection(k, from[k]);
      if (JSON.stringify(clean) !== last.current[k]) {
        changes[k] = clean;
        last.current[k] = JSON.stringify(clean);
      }
    }
    if (Object.keys(changes).length) save(keys[0], { resources: changes });
  };
  const set = (key, value, now = false) => {
    const next = { ...(latest.current || draft), [key]: value };
    latest.current = next;
    setDraft(next);
    const keys = GROUP[key] || [key];
    clearTimeout(typing.current[keys[0]]);
    if (now) leave(keys, next); // a line removed: saved at once
    else typing.current[keys[0]] = setTimeout(() => leave(keys, latest.current), TYPING_PAUSE);
  };
  const leaveInstructions = (text = instructions) => {
    clearTimeout(typing.current.instructions);
    if (text === last.current.instructions) return;
    last.current.instructions = text;
    save("instructions", { instructions: text });
  };
  const typeInstructions = (text) => {
    setInstructions(text);
    clearTimeout(typing.current.instructions);
    typing.current.instructions = setTimeout(() => leaveInstructions(text), TYPING_PAUSE);
  };
  const needParts = () => {
    if (parts) return;
    setParts([]);
    listMaintenanceParts().then((d) => setParts(d.parts || [])).catch(() => setParts([]));
  };

  const back = <button type="button" className="link pk-back" onClick={onBack}>← All tasks here</button>;
  if (state.error && state.id === taskId) return <div>{back}<LoadFailed what="Couldn't load the task." error={state.error} /></div>;
  const data = state.id === taskId ? state.data : null;
  if (!data || !draft) return <div>{back}<Loading /></div>;
  const t = data.task;
  const r = t.resources || {};
  const kind = kindText({ ...t, kind: t.outcome });
  const when = t.on_event ? "" : whenText({ interval: t.interval, interval_unit: t.unit, trigger: t.trigger });
  const register = [...(data.parts || []), ...((parts || []).filter((p) => !(data.parts || []).some((q) => q.id === p.id)))];
  const partLabel = (p) => `${p.part_number} ${p.name}`;
  return (
    <div className="lsa-task">
      {back}
      <div className="pk-view-head">
        <div>
          <h3 className="pk-view-name">{t.name}</h3>
          <p className="lib-date pk-sub">{[kind, when, t.subject?.name && `on ${t.subject.name}`, t.trade].filter(Boolean).join(" · ")}</p>
        </div>
      </div>
      {data.modes.length > 0 ? (
        <div className="lsa-modes">
          <span className="lib-date">Serves:</span>
          {/* Each a link to the task's row under that failure mode on the RCM tab. */}
          <ul>{data.modes.map((m) => (
            <li key={m.id}>
              <Link to={explorerHere(location.pathname, location.search, { sel: taskKey(m.id, t.id), tab: "rcm" })} title="Show this task under the failure mode on the RCM tab">{m.text}</Link>
              {modeLine(m) && <span className="lib-date"> · {modeLine(m)}</span>}
            </li>
          ))}</ul>
        </div>
      ) : <p className="lib-date">Serves no failure mode (a task added directly).</p>}
      <p className="lsa-total" aria-live="polite">
        {r.labour_hours ? `${num(r.labour_hours)} h labour` : "No labour set yet"}
        {r.people ? ` · ${r.people} ${r.people === 1 ? "person" : "people"}` : ""}
        {r.duration_hours != null ? ` · ${num(r.duration_hours)} h elapsed` : ""}
        {r.materials_cost != null ? ` · materials ${formatCost(r.materials_cost)}` : ""}
      </p>

      <Section title="Labour" hint="Who does it: each trade, how many people and the hours each." state={saved.labour} onLeave={() => leave(["labour", "duration_hours"])}>
        <Rows label="Labour lines" rows={draft.labour} onRows={(v, now) => set("labour", v, now)} blank={{ trade: t.trade || "", people: "1", hours: "" }} addLabel="+ Add labour"
              render={(x, patch, i) => (
                <>
                  <Cell label="Trade" className="lsa-wide"><input aria-label={`Trade, line ${i + 1}`} placeholder="e.g. Fitter" value={x.trade} maxLength={200} onChange={(e) => patch({ trade: e.target.value })} /></Cell>
                  <Cell label="People" className="lsa-num"><input type="number" min="1" step="1" inputMode="numeric" aria-label={`People, line ${i + 1}`} value={x.people} onChange={(e) => patch({ people: e.target.value })} /></Cell>
                  <Cell label="Hours each" className="lsa-num"><input type="number" min="0" step="0.25" inputMode="decimal" aria-label={`Hours each, line ${i + 1}`} value={x.hours} onChange={(e) => patch({ hours: e.target.value })} /></Cell>
                </>
              )} />
        <Cell label="Elapsed, start to finish (h; empty: not set)" className="lsa-duration">
          <input type="number" min="0" step="0.25" inputMode="decimal" aria-label="Elapsed hours" value={draft.duration_hours} onChange={(e) => set("duration_hours", e.target.value)} />
        </Cell>
      </Section>

      <Section title="Tools and instruments" hint="Tools and test equipment. An instrument can name the measuring point or channel it reads." state={saved.tools} onLeave={() => leave(["tools"])}>
        <Rows label="Tool lines" rows={draft.tools} onRows={(v, now) => set("tools", v, now)} blank={{ name: "", qty: "", note: "", point_id: "" }} addLabel="+ Add a tool"
              render={(x, patch, i) => (
                <>
                  <Cell label="Tool" className="lsa-wide"><input aria-label={`Tool, line ${i + 1}`} placeholder="e.g. Torque wrench" value={x.name} maxLength={200} onChange={(e) => patch({ name: e.target.value })} /></Cell>
                  <Cell label="How many" className="lsa-num"><input type="number" min="0" step="1" inputMode="numeric" aria-label={`How many, line ${i + 1}`} value={x.qty} onChange={(e) => patch({ qty: e.target.value })} /></Cell>
                  {data.points.length > 0 && (
                    <Cell label="Reads" className="lsa-wide"><select aria-label={`Reads, line ${i + 1}`} value={x.point_id} onChange={(e) => patch({ point_id: e.target.value })}>
                      <option value="">Reads no point</option>
                      {data.points.map((p) => <option key={p.id} value={p.id}>{p.name}{p.unit ? ` (${p.unit})` : ""}{p.kind === "channel" ? " · channel" : ""}{p.on ? ` · ${p.on}` : ""}</option>)}
                    </select></Cell>
                  )}
                  <Cell label="Note" className="lsa-wide"><input aria-label={`Note, line ${i + 1}`} value={x.note} maxLength={200} onChange={(e) => patch({ note: e.target.value })} /></Cell>
                </>
              )} />
      </Section>

      <Section title="Spares" hint="Parts to bring: pick from the parts register, or type a name." state={saved.spares} onLeave={() => leave(["spares"])}>
        <Rows label="Spare lines" rows={draft.spares} onRows={(v, now) => set("spares", v, now)} blank={{ part_id: "", name: "", qty: "1", part_number: "" }} addLabel="+ Add a spare"
              render={(x, patch, i) => (
                <>
                  <Cell label="Spare" className="lsa-wide"><input list="lsa-parts" aria-label={`Spare, line ${i + 1}`} placeholder="Part number or name"
                         value={x.part_id ? `${x.part_number ? `${x.part_number} ` : ""}${x.name}` : x.name} maxLength={200} onFocus={needParts}
                         onChange={(e) => {
                           const hit = register.find((p) => partLabel(p) === e.target.value);
                           patch(hit ? { part_id: hit.id, name: hit.name, part_number: hit.part_number } : { part_id: "", name: e.target.value, part_number: "" });
                         }} /></Cell>
                  <Cell label="Quantity" className="lsa-num"><input type="number" min="0" step="1" inputMode="decimal" aria-label={`Quantity, line ${i + 1}`} value={x.qty} onChange={(e) => patch({ qty: e.target.value })} /></Cell>
                  {x.part_id ? <span className="lib-date">from the register</span> : null}
                </>
              )} />
        <datalist id="lsa-parts">{register.map((p) => <option key={p.id} value={partLabel(p)} />)}</datalist>
      </Section>

      <Section title="Consumables" hint="Used up by the job: grease, test reagents, rags. Cost is for the quantity given." state={saved.consumables} onLeave={() => leave(["consumables"])}>
        <Rows label="Consumable lines" rows={draft.consumables} onRows={(v, now) => set("consumables", v, now)} blank={{ name: "", qty: "1", unit: "", cost: "" }} addLabel="+ Add a consumable"
              render={(x, patch, i) => (
                <>
                  <Cell label="Consumable" className="lsa-wide"><input aria-label={`Consumable, line ${i + 1}`} placeholder="e.g. Grease" value={x.name} maxLength={200} onChange={(e) => patch({ name: e.target.value })} /></Cell>
                  <Cell label="Quantity" className="lsa-num"><input type="number" min="0" step="any" inputMode="decimal" aria-label={`Quantity, line ${i + 1}`} value={x.qty} onChange={(e) => patch({ qty: e.target.value })} /></Cell>
                  <Cell label="Unit" className="lsa-num"><input aria-label={`Unit, line ${i + 1}`} placeholder="e.g. litre" value={x.unit} maxLength={20} onChange={(e) => patch({ unit: e.target.value })} /></Cell>
                  <Cell label={`Cost (${workspaceCurrency()})`} className="lsa-num"><input type="number" min="0" step="any" inputMode="decimal" aria-label={`Cost, line ${i + 1}`} value={x.cost} onChange={(e) => patch({ cost: e.target.value })} /></Cell>
                </>
              )} />
      </Section>

      <Section title="Access and downtime" state={saved.access} onLeave={() => leave(["access"])}>
        <div className="lsa-grid">
          <label className="lsa-field"><span>Downtime (h; empty: none)</span>
            <input type="number" min="0" step="0.25" inputMode="decimal" value={draft.access.downtime_hours} onChange={(e) => set("access", { ...draft.access, downtime_hours: e.target.value })} /></label>
          <label className="lsa-field"><span>Permits (comma between)</span>
            <input value={draft.access.permits} placeholder="e.g. Hot work, Confined space" onChange={(e) => set("access", { ...draft.access, permits: e.target.value })} /></label>
          <label className="lsa-field"><span>Isolation</span>
            <input value={draft.access.isolation} maxLength={200} placeholder="e.g. Lock out the pump starter" onChange={(e) => set("access", { ...draft.access, isolation: e.target.value })} /></label>
          <label className="lsa-field"><span>Access equipment</span>
            <input value={draft.access.access_equipment} maxLength={200} placeholder="e.g. Scaffold, EWP" onChange={(e) => set("access", { ...draft.access, access_equipment: e.target.value })} /></label>
        </div>
      </Section>

      <Section title="Method" hint="How it's done, in a line: “On site with a test kit”, “Sent to the workshop”." state={saved.method} onLeave={() => leave(["method"])}>
        <input className="lsa-full" aria-label="Method" value={draft.method} maxLength={500} onChange={(e) => set("method", e.target.value)} />
      </Section>

      <Section title="Instructions" hint="The steps, as they go on its work orders." state={saved.instructions} onLeave={() => leaveInstructions()}>
        <textarea className="lsa-full" rows={4} aria-label="Instructions" value={instructions} maxLength={4000} onChange={(e) => typeInstructions(e.target.value)} />
      </Section>
    </div>
  );
}

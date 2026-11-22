import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import TablePane from "./TablePane.jsx";
import Section from "./ui/Section.jsx";
import Field from "./ui/Field.jsx";
import InputGroup from "./ui/InputGroup.jsx";
import { Select as NativeSelect, TextInput } from "./ui/Controls.jsx";
import Select from "./Select.jsx";
import ResultSummary from "./ui/ResultSummary.jsx";
import ReplacementResult from "./ReplacementResult.jsx";
import LoadFailed from "./LoadFailed.jsx";
import PlaceholderRows from "./PlaceholderRows.jsx";
import { listDegradationModels, listModels, optimiseTask, useTaskOptimise } from "../api.js";
import { saveErrorText } from "../confirm.js";
import { explorerHere } from "../products.js";
import { workspaceCurrency } from "../money.js";
import { pct } from "../rcmIntervals.js";
import { bodyFor, every, modelSource, modelWords, startText, useLabel, usedText } from "../taskOptimise.js";
import "./TaskOptimisePane.css";

// Optimise… on a maintenance task, in the Explorer's table area beside the tree (the Maintenance
// tab's task row ⋯, and the task's panel; Derryn, 22 Nov 2026: "an 'optimise' option for a task").
// For each failure mode the task prevents: the life model its interval rests on (changeable), the
// inputs it starts from with where each came from (editable, costs especially), the answer in plain
// words with its range across the model's 90% bounds, the curve, and "Use every N", which sets the
// task's interval and saves the calculation as the mode's evidence (task_optimise.py).
//
//   task     {id, name}           position  the task's position {id, name}
//   onUsed   (text) after a Use: the tasks are read again
export default function TaskOptimisePane({ task, position, phone = false, headingRef = null, onClose, onUsed }) {
  const [state, setState] = useState({ data: null, error: null });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    // Read again after a Use: what's shown stays until the new answer comes (so "✓ Set to…" stays too).
    setState((s) => ({ data: s.data, error: null }));
    optimiseTask(task.id).then((data) => live && setState({ data, error: null }),
      (error) => live && setState({ data: null, error }));
    return () => { live = false; };
  }, [task.id, attempt]);
  const modes = state.data?.modes || [];
  const t = state.data?.task;
  return (
    <TablePane title="Optimise" subject={task.name || "Task"} phone={phone} headingRef={headingRef} onClose={onClose}
               closeLabel="Close Optimise" className="optimise-pane">
      <div className="to-body">
        <p className="to-what">
          How often to do it, worked out from the life model of each failure mode it prevents.
          {t?.interval != null && <> Now every <b>{every(t.interval, t.unit)}</b>.</>}
        </p>
        {state.error && <LoadFailed what="Couldn't work out this task's interval." error={state.error} onRetry={() => setAttempt((n) => n + 1)} />}
        {!state.data && !state.error && <PlaceholderRows shape="fields" rows={4} label="Working it out…" />}
        {state.data && !modes.length && (
          <p className="to-none">This task prevents no failure mode yet, so there&apos;s no failure model to work its interval
            out from. Link the failure modes it prevents on its panel, or decide them on the RCM tab.</p>
        )}
        {modes.map((row) => (
          <ModeOptimise key={row.id} task={t} start={row} many={modes.length > 1} position={position}
                        onUsed={(text) => { setAttempt((n) => n + 1); onUsed?.(text); }} />
        ))}
      </div>
    </TablePane>
  );
}

// One failure mode's optimisation: its model, its inputs, the answer and Use.
function ModeOptimise({ task, start, many, position, onUsed }) {
  const location = useLocation();
  const [row, setRow] = useState(start);
  const [edits, setEdits] = useState({});
  // The edits the answer shown was worked out from: Use sends the same, so it saves what's shown.
  const [workedOn, setWorkedOn] = useState("{}");
  const [model, setModel] = useState(null); // a model chosen here: {type, id}
  const [busy, setBusy] = useState(null); // "work" | "use"
  const [said, setSaid] = useState(null);
  const [failed, setFailed] = useState(null);
  const [library, setLibrary] = useState(null);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);
  useEffect(() => { setRow(start); }, [start]);
  const dirty = JSON.stringify(edits) !== workedOn;
  const set = (k) => (e) => { const v = e.target.value; setEdits((x) => ({ ...x, [k]: v })); };
  const body = (over = model) => bodyFor(row.id, edits, over);

  const work = async (over = model) => {
    setBusy("work");
    setFailed(null);
    setSaid(null);
    try {
      const out = await optimiseTask(task.id, body(over));
      if (alive.current) { setRow(out.modes[0]); setWorkedOn(JSON.stringify(edits)); }
    } catch (e) {
      if (alive.current) setFailed(saveErrorText(e, { offline: navigator.onLine === false }));
    } finally {
      if (alive.current) setBusy(null);
    }
  };
  const use = async () => {
    setBusy("use");
    setFailed(null);
    try {
      const out = await useTaskOptimise(task.id, body());
      if (!alive.current) return;
      const text = usedText(out);
      setSaid(text);
      onUsed?.(`${task.name}: ${text}`);
    } catch (e) {
      if (alive.current) setFailed(saveErrorText(e, { offline: navigator.onLine === false }));
    } finally {
      if (alive.current) setBusy(null);
    }
  };
  // The user's own models, read when the model picker is first opened.
  useEffect(() => {
    if (row.calculator === "pf" || library) return;
    let live = true;
    Promise.all([listModels().catch(() => ({ models: [] })), listDegradationModels().catch(() => [])]).then(([a, b]) => {
      if (!live) return;
      const life = (a.models || []).filter((m) => m.kind === "distribution").map((m) => ({ type: "model", id: m.id, name: m.name, unit: m.unit }));
      const deg = (Array.isArray(b) ? b : b.models || []).map((m) => ({ type: "degradation_model", id: m.id, name: m.name, unit: m.unit }));
      setLibrary([...life, ...deg]);
    });
    return () => { live = false; };
  }, [row.calculator]); // eslint-disable-line react-hooks/exhaustive-deps

  const title = many ? row.text : `For ${row.text}`;
  if (!row.calculator) {
    return (
      <Section title={title} className="ruled to-mode">
        <p className="to-none">{row.nothing}</p>
      </Section>
    );
  }
  const m = row.model;
  const options = modelOptions(row, library);
  const fitPath = explorerHere(location.pathname, location.search, { sel: row.position_id, tab: "models" });
  const pick = (value) => {
    const [type, id] = String(value).split(":");
    if (!id) return;
    const chosen = { type, id };
    setModel(chosen);
    work(chosen);
  };
  return (
    <Section title={title} className="ruled to-mode">
      {row.calculator !== "pf" && (
        <div className="to-model">
          {m?.usable ? (
            <p className="to-line">
              Based on{" "}
              {m.path ? <Link to={m.path}>{m.name}</Link> : <b>{m.name}</b>}
              {modelWords(m) && <span className="to-quiet"> · {modelWords(m)}</span>}
              {modelSource(m) && <span className="to-quiet">. {modelSource(m)}</span>}
            </p>
          ) : (
            <p className="to-line to-missing" role="note">
              {row.no_model} <Link to={fitPath}>Fit one on the Modelling tab</Link>.
            </p>
          )}
          <Field label={m?.usable ? "Use another model" : "Link a model"} optional={!!m?.usable}>
            <Select value={m?.id ? `${m.type}:${m.id}` : ""} onChange={pick} options={options} searchable
                    placeholder={library ? "Choose a model…" : "Reading your models…"} ariaLabel={`Model for ${row.text}`}
                    disabled={!!busy} />
          </Field>
        </div>
      )}
      {row.moved && (
        <p className="to-line to-moved" role="note">
          ! The model has been refitted since this interval was set: its optimum may have moved. Re-optimise and use the new answer if it suits.
        </p>
      )}
      <form className="to-inputs" onSubmit={(e) => { e.preventDefault(); work(); }}>
        {row.calculator === "replacement" && (
          <div className="to-row">
            <Field label={`Planned replacement (${workspaceCurrency()})`} help={row.inputs?.planned_cost?.text}>
              <TextInput type="number" inputMode="decimal" min="0" step="any" disabled={!!busy}
                         value={edits.planned_cost ?? startText(row.inputs?.planned_cost)} onChange={set("planned_cost")} />
            </Field>
            <Field label={`A failure (${workspaceCurrency()})`} help={row.inputs?.unplanned_cost?.text}>
              <TextInput type="number" inputMode="decimal" min="0" step="any" disabled={!!busy} placeholder="e.g. 900"
                         value={edits.unplanned_cost ?? startText(row.inputs?.unplanned_cost)} onChange={set("unplanned_cost")} />
            </Field>
          </div>
        )}
        {row.calculator === "pf" && (
          <div className="to-row">
            <Field label="P-F interval" as="fieldset" help={row.inputs?.pf_interval?.text}>
              <InputGroup label="P-F interval">
                <TextInput type="number" inputMode="decimal" min="0" step="any" aria-label="P-F interval" disabled={!!busy}
                           value={edits.pf_interval ?? startText(row.inputs?.pf_interval)} onChange={set("pf_interval")} placeholder="e.g. 127" />
                <NativeSelect aria-label="P-F interval unit" value={edits.pf_unit ?? row.inputs?.pf_unit ?? "hours"} onChange={set("pf_unit")} disabled={!!busy}>
                  {unitChoices(row.inputs?.pf_unit, task?.unit).map((u) => <option key={u} value={u}>{u}</option>)}
                </NativeSelect>
              </InputGroup>
            </Field>
            <Field label="Time needed to act" optional help="From finding the warning to the fix being done, in the P-F interval's unit.">
              <TextInput type="number" inputMode="decimal" min="0" step="any" disabled={!!busy} placeholder="0"
                         value={edits.act_time ?? startText(row.inputs?.act_time)} onChange={set("act_time")} />
            </Field>
          </div>
        )}
        {row.calculator === "ff" && (
          <Field label="Target unavailability (%)" help={row.inputs?.target_unavailability?.text}>
            <TextInput type="number" inputMode="decimal" min="0" max="100" step="any" disabled={!!busy}
                       value={edits.target ?? (row.inputs?.target_unavailability?.value != null ? String(Number((row.inputs.target_unavailability.value * 100).toPrecision(6))) : "")}
                       onChange={set("target")} />
          </Field>
        )}
        {dirty && (
          <div className="to-go">
            <button type="submit" className="secondary" disabled={!!busy}>{busy === "work" ? "Working it out…" : "Work it out again"}</button>
          </div>
        )}
      </form>
      {row.problem && !dirty && <p className="field-help to-problem" role="note">{row.problem}</p>}
      {failed && <p className="field-error" role="alert">{failed}</p>}
      <Answer row={row} />
      {row.use && (
        <div className="to-use">
          <button type="button" className={many ? "secondary" : undefined} onClick={use} disabled={!!busy || dirty}
                  aria-busy={busy === "use" || undefined} title={dirty ? "Work it out again first" : undefined}>
            {busy === "use" ? "Saving…" : useLabel(row.use)}
          </button>
          <span className="to-quiet">Sets the task&apos;s interval and saves this as the failure mode&apos;s evidence.</span>
        </div>
      )}
      {said && <p className="to-said" role="status">✓ {said}</p>}
    </Section>
  );
}

// The answer: words first, with the range, then the curve (a replacement), or the check's numbers.
function Answer({ row }) {
  const r = row.result;
  if (!r) return null;
  if (row.calculator === "replacement") {
    return (
      <div className="to-answer">
        {row.use && (
          <p className="to-words">
            {row.words}
            {row.converted && <span className="to-quiet"> ({row.converted}.)</span>}
          </p>
        )}
        <ReplacementResult result={r} name={row.text} />
      </div>
    );
  }
  const pf = row.calculator === "pf";
  const stats = pf ? [
    { label: "Check every", value: every(row.use?.value, row.use?.unit) },
    { label: r.basis === "net_pf" ? "Net P-F interval" : "Half the P-F interval", value: every(r.interval, r.unit) },
    r.current && { label: "Now", value: every(r.current.value, r.current.unit), hint: r.current.within ? "within the P-F limit" : "longer than the P-F limit: warnings can be missed" },
  ] : [
    { label: "Test every", value: every(row.use?.value, row.use?.unit) },
    r.at_recommended && { label: "Failed when needed", value: pct(r.at_recommended.mean_unavailability), hint: "of the time, on average" },
    r.current && { label: "Now", value: pct(r.current.mean_unavailability), hint: r.current.meets_target === false ? "misses the target" : "meets the target" },
  ];
  return (
    <div className="to-answer">
      <ResultSummary tone={row.use ? "neutral" : "caveat"} sentence={row.words} stats={row.use ? stats : []}>
        {row.range_note}
      </ResultSummary>
    </div>
  );
}

// The models offered: the position's rows for this mode first, then the user's own.
function modelOptions(row, library) {
  const out = [];
  const seen = new Set();
  if (row.choices?.length) {
    out.push({ heading: "On this position" });
    for (const c of row.choices) {
      seen.add(c.id);
      out.push({ value: `${c.type}:${c.id}`, label: c.name, disabled: !c.usable, hint: c.usable ? (c.for_mode ? "For this failure mode" : "For every failure here") : c.why });
    }
  }
  const mine = (library || []).filter((x) => !seen.has(x.id));
  if (mine.length) {
    out.push({ heading: "Your models" });
    for (const x of mine) out.push({ value: `${x.type}:${x.id}`, label: x.name, hint: [x.type === "degradation_model" ? "Degradation, time to the limit" : "Non-repairable", x.unit].filter(Boolean).join(" · ") });
  }
  if (row.model?.id && !seen.has(row.model.id) && !mine.some((x) => x.id === row.model.id)) {
    out.unshift({ value: `${row.model.type}:${row.model.id}`, label: row.model.name });
  }
  return out;
}

function unitChoices(...given) {
  const out = ["hours", "days", "weeks", "months", "years"];
  for (const u of given) if (u && !out.includes(u)) out.push(u);
  return out;
}

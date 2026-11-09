import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  createModelFromParams, getMaintenancePosition, getPositionModel, linkPositionModel, listAltModels, listDegradationModels, listModels,
  listPositionModels, listRbds, listRecurrentModels, unlinkPositionModel,
} from "../api.js";
import Chip from "./ui/Chip.jsx";
import Field from "./ui/Field.jsx";
import { Select, TextInput } from "./ui/Controls.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import Modal from "./Modal.jsx";
import Plot from "./Plot.jsx";
import PredictionResult from "./PredictionResult.jsx";
import { predictionPath } from "../predictions.js";
import { CloseIcon, ExpandIcon, ShrinkIcon } from "./icons.jsx";
import { ACCENT, BAND_FILL } from "../plotTheme.js";
import { saveErrorText } from "../confirm.js";
import { explorerHere } from "../products.js";
import {
  MODEL_COLUMNS, b10Text, boundsLabel, countsText, fmt, forText, headline, meanText, rowActions, unitWord, usedText, withBounds,
} from "../explorerModels.js";
import "./MeasurementTable.css";
import "./ModelTable.css";
import LibraryRecordPicker, { PickedRecord } from "./LibraryRecordPicker.jsx";

// The Explorer's Modelling tab is the tree with each position's life models in it
// (explorerModels.js), like the RCM and Measurements tabs. This file has what the page
// needs for it: the read of every attached model; each row's cells; its phone line;
// the details beside the table for a row picked (the plot, the parameters with bounds,
// the data behind it, what uses it, notes); and the dialogs that attach a model (fit
// from history, assign a saved one, the class's) and take one off.

export { MODEL_COLUMNS } from "../explorerModels.js";
export { MODEL_TREE_HEAD } from "../explorerModels.js";

// Every attached model, read when the tab is on (and again on `load`).
export function useTreeModels({ on }) {
  const [state, setState] = useState({ links: null, error: null });
  const load = useCallback(() => listPositionModels()
    .then((d) => setState({ links: d.links || [], error: null }))
    .catch((e) => setState((s) => ({ links: s.links, error: e.message }))), []);
  useEffect(() => { if (on) load(); }, [on, load]);
  return { links: state.links, error: state.error, load };
}

const QUALITY_TONE = { success: "success", warning: "warning", neutral: "neutral" };

// One cell of a model row (the tree row `r`, its link r.ref.link).
export function ModelCell({ r, col }) {
  const link = r.ref.link;
  const model = link.model;
  if (!model) {
    return col.id === "kind" ? <Chip tone="warning" title="The saved model was deleted, or isn't yours to open any more">Missing</Chip>
      : col.id === "source" ? <span className="ml-src" title={link.source_text}>{link.source_text}</span> : <span className="rw-blank">—</span>;
  }
  switch (col.id) {
    case "kind":
      return (
        <span className="ml-kind">
          <Chip tone={model.family === "life" ? "accent" : "neutral"} className="pk-kind">{model.kind || "Model"}</Chip>
          {link.in_use && r.ref.many && <Chip tone="success" className="ml-inuse" title="The position's model in use: what its roll-up, the RCM and a parent's RBD take">In use</Chip>}
        </span>
      );
    case "source":
      return (
        <span className="ml-src" title={`${link.source_text}. For: ${forText(link)}.`}>
          {link.source_text}
          {link.failure_modes?.length > 0 && <span className="rw-sum">For: {forText(link)}</span>}
        </span>
      );
    case "numbers": {
      const text = headline(model);
      return text ? <span className="ml-num" title={text}>{text}</span> : <span className="rw-blank">—</span>;
    }
    case "mean": return <span className="ml-num">{meanText(model)}</span>;
    case "b10": return <span className="ml-num">{b10Text(model)}</span>;
    case "quality":
      return (
        <span className="ml-q">
          {link.stale ? <Chip tone="warning" title={link.stale}>Stale</Chip>
            : model.quality?.word ? <Chip tone={QUALITY_TONE[model.quality.tone] || "neutral"} title={model.quality.why}>{model.quality.word}</Chip> : null}
          <span className="rw-sum">{countsText(model)}</span>
        </span>
      );
    case "used": {
      const text = usedText(link);
      return text ? <span>{text}</span> : <span className="rw-blank">—</span>;
    }
    default: return null;
  }
}

// A row's second line on a phone: its kind and headline; the quality as its chip.
export function modelPhoneRow(r, rollup) {
  if (r.type !== "pmodel") return { line: rollup || "", status: null };
  const link = r.ref.link;
  const model = link.model;
  if (!model) return { line: link.source_text, status: <Chip tone="warning">Missing</Chip> };
  return {
    line: [model.kind, headline(model) || meanText(model)].filter((x) => x && x !== "—").join(" · "),
    status: link.stale ? <Chip tone="warning" title={link.stale}>Stale</Chip>
      : model.quality?.word ? <Chip tone={QUALITY_TONE[model.quality.tone] || "neutral"} title={model.quality.why}>{model.quality.word}</Chip> : null,
  };
}

export const modelRowActions = (r, opts) => rowActions(r, opts);

// The plot: reliability (with its 95% bounds, or a Bayesian update's credible band) or hazard over age, or a repairable
// model's expected failures so far.
function ModelPlot({ curves, unit, name }) {
  const [on, setOn] = useState("sf");
  if (!curves) return <p className="rim-tquiet">No plot for this kind of model here: open it in Models.</p>;
  const u = unitWord(unit);
  const xTitle = `Age${u ? ` (${u})` : ""}`;
  if (curves.mcf) {
    return (
      <Plot data={[{ x: curves.x, y: curves.mcf, mode: "lines", line: { color: ACCENT, width: 2 }, name: "Expected failures" }]}
            layout={{ height: 240, xaxis: { title: { text: xTitle } }, yaxis: { title: { text: "Expected failures so far" }, rangemode: "tozero" } }}
            download={`${name} — expected failures`} />
    );
  }
  const hazard = on === "hf" && curves.hf;
  const traces = [];
  if (!hazard && curves.sf_lower && curves.sf_upper) {
    traces.push({ x: curves.x, y: curves.sf_upper, mode: "lines", line: { width: 0 }, hoverinfo: "skip", showlegend: false });
    const band = curves.band?.kind === "credible" ? `${Math.round(curves.band.level * 100)}% credible band` : "95% bounds";
    traces.push({ x: curves.x, y: curves.sf_lower, mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: BAND_FILL, name: band, hoverinfo: "skip" });
  }
  traces.push({ x: curves.x, y: hazard ? curves.hf : curves.sf, mode: "lines", line: { color: ACCENT, width: 2 }, name: hazard ? "Hazard rate" : curves.what || "Reliability" });
  return (
    <>
      {curves.hf && (
        <SegmentedControl size="sm" label="What to plot" value={on} onChange={setOn}
                          options={[{ value: "sf", label: "Reliability" }, { value: "hf", label: "Hazard" }]} />
      )}
      <Plot data={traces}
            layout={{ height: 240, xaxis: { title: { text: xTitle } },
              yaxis: hazard ? { title: { text: `Failures per ${u ? u.replace(/s$/, "") : "unit of time"}` }, rangemode: "tozero" }
                : { title: { text: "Reliability" }, range: [0, 1.02] } }}
            download={`${name} — ${hazard ? "hazard" : "reliability"}`} />
    </>
  );
}

// The details beside the table for a model row picked: what it says, where it came
// from, the plot, its parameters with bounds, the data behind it, what uses it and
// notes. Its actions go in the heading's "…" (onMenu).
export function ModelSide({ r, phone, expanded, onExpand, onCollapse, onClose, headingRef, onMenu, onAction }) {
  const link = r.ref.link;
  const location = useLocation();
  const [state, setState] = useState({ id: null, data: null, error: null });
  const [age, setAge] = useState("");
  const askAge = link.model_type === "rbd" && Number(age) > 0 ? Number(age) : null;
  useEffect(() => {
    let live = true;
    const t = setTimeout(() => getPositionModel(link.id, { age: askAge }).then((data) => live && setState({ id: link.id, data, error: null }),
      (e) => live && setState({ id: link.id, data: null, error: e.message })), askAge ? 300 : 0);
    return () => { live = false; clearTimeout(t); };
  }, [link.id, askAge]);
  useEffect(() => {
    onMenu?.(rowActions(r).filter((a) => a.id !== "model-open").map((a) => ({
      ...a, id: `side-${a.id}`, onSelect: () => onAction(r, a.id),
    })));
    return () => onMenu?.(null);
  }, [link.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const d = state.id === link.id ? state.data : null;
  const model = link.model;
  const unit = model?.unit || "";
  return (
    <aside className={"rw-panel mt-panel ml-panel" + (phone ? " sheet" : "") + (expanded ? " is-expanded" : "")} aria-label="Details"
           onKeyDown={(e) => {
             if (e.key !== "Escape" || e.defaultPrevented || e.target.closest("input, textarea, select")) return;
             e.stopPropagation();
             if (expanded) onCollapse(); else onClose();
           }}>
      <div className="rw-panel-top">
        <div className="rw-panel-head">
          <div className="rw-panel-kind">{model ? `Life model · ${model.kind}` : "Life model"}</div>
          <div className="rw-panel-btns">
            {!phone && (expanded ? (
              <button type="button" className="ghost sm rw-x" onClick={onCollapse} title="Show the table again, with these details beside it (Esc)" aria-label="Back to table"><ShrinkIcon /></button>
            ) : (
              <button type="button" className="ghost sm rw-x" onClick={onExpand} title="Show these details across the table, the tree kept beside them" aria-label="Expand the details"><ExpandIcon /></button>
            ))}
            <button type="button" className="ghost sm rw-x" onClick={onClose} aria-label="Close the details" title="Close (Esc)"><CloseIcon /></button>
          </div>
        </div>
        <h2 className="rw-panel-title" tabIndex={-1} ref={headingRef}>{r.ref.name}</h2>
      </div>
      <div className="rw-pbody mt-pbody ml-pbody">
        {!model ? (
          <p className="field-error">The saved model behind this is gone (deleted, or not yours to open any more). Replace it with another, or unlink it.</p>
        ) : (
          <>
            <p className="ml-lead">
              <strong>{headline(model) || meanText(model)}</strong>
              {model.quality?.word && <> · <Chip tone={QUALITY_TONE[model.quality.tone] || "neutral"} title={model.quality.why}>{model.quality.word}</Chip></>}
            </p>
            {link.stale && <p className="ml-stale" role="note">{link.stale}.</p>}
            <p className="rim-tquiet">{link.source_text}. For: {forText(link)}.{" "}
              {link.model_type === "rbd" ? (
                // The diagram in the RBD builder: in the table area, or on its own page.
                <>
                  <button type="button" className="link sm" onClick={() => onAction(r, "model-rbd-pane")}>Open in the pane</button>
                  {model.path && <> · <Link to={model.path}>Open full page</Link></>}
                </>
              ) : model.path && <Link to={model.path}>Open in Models</Link>}</p>
            {state.error && <p className="field-error">Couldn't read it: {state.error}</p>}
            {!d && !state.error && <p className="rim-tquiet">Reading the model…</p>}
            {d?.stress_note && <p className="rim-tquiet ml-stress">{d.stress_note}</p>}
            {link.model_type === "rbd" && <RbdDetails d={d} model={model} age={age} onAge={setAge} />}
            {d && <ModelPlot curves={d.curves} unit={unit} name={r.ref.name} />}
            {d?.prediction && (
              <section aria-label="The parts count">
                <h3 className="ml-h">The parts count <Link className="rw-sum" to={predictionPath(d.prediction.id)}>Open in Predictions</Link></h3>
                <PredictionResult results={d.prediction.results} name={d.prediction.name} />
              </section>
            )}
            {d?.params?.length > 0 && (
              <section aria-label="Parameters">
                <h3 className="ml-h">Parameters</h3>
                <div className="maint-scroll">
                  <table className="ml-params">
                    <thead><tr><th>Parameter</th><th className="num">{model.credible ? "Median" : "Value"}</th><th className="num">{boundsLabel(model)}</th></tr></thead>
                    <tbody>
                      {d.params.map((p) => (
                        <tr key={`${p.label}:${p.name}`} title={p.meaning || undefined}>
                          <td>{p.label ? `${p.label}: ` : ""}{p.name}</td>
                          <td className="num">{fmt(p.value)}</td>
                          <td className="num">{p.lower != null && p.upper != null ? `${fmt(p.lower)}–${fmt(p.upper)}` : "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}
            <section aria-label="The data behind it">
              <h3 className="ml-h">The data behind it</h3>
              <dl className="ml-dl">
                <dt>Data</dt><dd>{countsText(model) || "—"}</dd>
                <dt>Unit</dt><dd>{unit || "—"}</dd>
                <dt>Time starts</dt><dd>{d?.origin || "…"}</dd>
                {(model.numbers || []).filter((n) => n.id === "mean" || n.id === "b10").map((n) => (
                  <span key={n.id} className="ml-dlrow"><dt>{n.label}</dt><dd>{withBounds(n, model.credible_level)}</dd></span>
                ))}
              </dl>
            </section>
          </>
        )}
        <section aria-label="Used by">
          <h3 className="ml-h">Used by</h3>
          {!link.used_by?.decisions?.length && !link.used_by?.rbds?.length ? (
            <p className="rim-tquiet">Nothing links it yet. Link it as a failure mode's evidence on the RCM tab (“Based on:”).</p>
          ) : (
            <ul className="ml-used">
              {(link.used_by?.decisions || []).map((x) => (
                <li key={x.failure_mode_id}>
                  <Link to={explorerHere(location.pathname, location.search, { sel: x.failure_mode_id, tab: "rcm" })}>{x.text}</Link>
                  <span className="rw-sum"> · decision on {x.position}</span>
                </li>
              ))}
              {(link.used_by?.rbds || []).map((x) => (
                <li key={x.id}><Link to={`/systems/b/${x.id}`}>{x.name}</Link><span className="rw-sum"> · RBD block</span></li>
              ))}
            </ul>
          )}
        </section>
        {(link.note || d?.model_notes) && (
          <section aria-label="Notes">
            <h3 className="ml-h">Notes</h3>
            {link.note && <p className="ml-note">{link.note}</p>}
            {d?.model_notes && <p className="ml-note rim-tquiet">{d.model_notes}</p>}
          </section>
        )}
      </div>
    </aside>
  );
}

// An RBD row's details: the system figures (and its reliability at an age you name), the
// placeholder warning, and every block with its model and the position it came from.
function RbdDetails({ d, model, age, onAge }) {
  const u = (model?.unit || "").toLowerCase();
  const blocks = d?.blocks || [];
  return (
    <section aria-label="The diagram" className="ml-rbd">
      {model?.placeholders?.length > 0 && (
        <p className="ml-stale" role="note">Placeholders stand in for {model.placeholders.join(", ")}: the figures aren't real until they have models.</p>
      )}
      {model?.repairable && <p className="rim-tquiet">A repairable diagram: its availability is simulated on its own page.</p>}
      <Field label={`System reliability at an age${u ? ` (${u})` : ""}`} optional>
        <TextInput inputMode="decimal" value={age} onChange={(e) => onAge(e.target.value)} placeholder={u ? `An age in ${u}` : "An age"} />
      </Field>
      {d?.model?.at_age && <p className="ml-lead">{Math.round(d.model.at_age.reliability * 1000) / 10}% chance the system survives {fmt(d.model.at_age.age)} {u}.</p>}
      <h3 className="ml-h">Blocks</h3>
      <div className="maint-scroll">
        <table className="ml-params ml-blocks">
          <thead><tr><th>Block</th><th>Model</th><th>From</th></tr></thead>
          <tbody>
            {blocks.map((b) => (
              <tr key={b.id}>
                <td>{b.label}</td>
                <td>{b.placeholder ? <Chip tone="warning" title="A placeholder: no model in use for this position yet">Placeholder</Chip> : b.model}</td>
                <td>{b.position ? b.position.name : <span className="rw-blank">—</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// "Link an existing RBD…": the user's diagrams and the samples. Linked, it opens in the table area.
export function RbdLinkModal({ position, onClose, onDone }) {
  const [list, setList] = useState(null);
  const [chosen, setChosen] = useState(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(null);
  useEffect(() => { listRbds().then((d) => setList(d.rbds || d.items || []), () => setList([])); }, []);
  const save = async () => {
    setBusy(true);
    try {
      const made = await linkPositionModel(position.id, { rbd_id: chosen });
      onDone(made, `Linked ${made.name} to ${position.name}.`);
    } catch (e) {
      setBusy(false);
      setFailed(saveErrorText(e, { offline: navigator.onLine === false }));
    }
  };
  const groups = [["Yours", (list || []).filter((x) => !x.is_sample)], ["Samples", (list || []).filter((x) => x.is_sample)]];
  return (
    <Modal title="Link an existing RBD" onClose={onClose} locked={busy} trapFocus className="ml-dialog"
           footer={(
             <>
               <button type="button" className="secondary" onClick={onClose} disabled={busy}>Cancel</button>
               <button type="button" onClick={save} disabled={busy || !chosen} aria-busy={busy || undefined}>{busy ? "Linking…" : "Link"}</button>
             </>
           )}>
      <p className="rw-fhelp">Links a diagram to {position.name} as it is: it isn’t copied, so edits to it show here.</p>
      {list === null ? <p className="rim-tquiet">Loading diagrams…</p> : !list.length ? <p className="rim-tquiet">No RBDs yet.</p> : (
        <div className="evidence-picker" role="radiogroup" aria-label="RBDs">
          {groups.filter(([, g]) => g.length).map(([title, g]) => (
            <div key={title}>
              <div className="ml-group">{title}</div>
              {g.map((x) => (
                <label key={x.id} className={"evidence-option" + (chosen === x.id ? " selected" : "")}>
                  <input type="radio" name="ml-rbd" checked={chosen === x.id} onChange={() => setChosen(x.id)} />
                  <span className="evidence-name">{x.name}</span>
                </label>
              ))}
            </div>
          ))}
        </div>
      )}
      {failed && <p className="field-error" role="alert">{failed}</p>}
    </Modal>
  );
}

// "Enter parameters…" (Life model ›): a model from numbers you have (a data sheet, a handbook,
// a vendor's figures), saved to Models through the usual save from parameters and attached here.
const PARAMS = {
  weibull: [["alpha", "Characteristic life (alpha)"], ["beta", "Shape (beta)"]],
  exponential: [["failure_rate", "Failure rate (per unit of time)"]],
  lognormal: [["mu", "mu (log of the median)"], ["sigma", "sigma (spread)"]],
  normal: [["mu", "Mean (mu)"], ["sigma", "Standard deviation (sigma)"]],
  gamma: [["alpha", "alpha (shape)"], ["beta", "beta (rate)"]],
};
export function ParamsModal({ position, onClose, onDone }) {
  const [distribution, setDistribution] = useState("weibull");
  const [values, setValues] = useState({});
  const [unit, setUnit] = useState("hours");
  const [name, setName] = useState(`${position.name} (entered)`);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(null);
  const names = PARAMS[distribution];
  const ok = name.trim() && names.every(([k]) => Number(values[k]) > 0 || (k === "mu" && Number.isFinite(Number(values[k])) && values[k] !== ""));
  const save = async () => {
    setBusy(true);
    setFailed(null);
    try {
      const model = await createModelFromParams(name.trim(), distribution, names.map(([k]) => ({ name: k, value: Number(values[k]) })), { unit });
      const made = await linkPositionModel(position.id, { model_id: model.id, model_type: "model" });
      onDone(made, `Saved ${model.name} and attached it to ${position.name}.`);
    } catch (e) {
      setBusy(false);
      setFailed(saveErrorText(e, { offline: navigator.onLine === false }));
    }
  };
  return (
    <Modal title="Enter parameters" onClose={onClose} locked={busy} trapFocus className="ml-dialog"
           footer={(
             <>
               <button type="button" className="secondary" onClick={onClose} disabled={busy}>Cancel</button>
               <button type="button" onClick={save} disabled={busy || !ok} aria-busy={busy || undefined}>{busy ? "Saving…" : "Save and attach"}</button>
             </>
           )}>
      <p className="rw-fhelp">A life model from numbers you have: a data sheet, a handbook or the vendor’s figures. It’s saved to Models (with no data behind it, so its row says Assumed) and attached to {position.name}.</p>
      <div className="ml-row">
        <Field label="Distribution">
          <Select value={distribution} onChange={(e) => { setDistribution(e.target.value); setValues({}); }}>
            <option value="weibull">Weibull</option><option value="exponential">Exponential</option>
            <option value="lognormal">Lognormal</option><option value="normal">Normal</option><option value="gamma">Gamma</option>
          </Select>
        </Field>
        <Field label="Unit">
          <Select value={unit} onChange={(e) => setUnit(e.target.value)}>
            {["hours", "days", "weeks", "months", "years", "cycles"].map((x) => <option key={x} value={x}>{x}</option>)}
          </Select>
        </Field>
      </div>
      <div className="ml-row">
        {names.map(([k, label]) => (
          <Field key={k} label={label}>
            <TextInput inputMode="decimal" value={values[k] || ""} onChange={(e) => setValues((v) => ({ ...v, [k]: e.target.value }))} />
          </Field>
        ))}
      </div>
      <Field label="Name"><TextInput value={name} onChange={(e) => setName(e.target.value)} /></Field>
      {failed && <p className="field-error" role="alert">{failed}</p>}
    </Modal>
  );
}

// Life model › From the data library…: a record attached as the position's model (a rate per hour
// becomes an exponential with the source's 5–95% range, cited). The record comes from "Pick a library
// record" (a modal over this one, opened at once), which lists only the records that can be a model.
export function LibraryAttachModal({ position, onClose, onDone, onBind = null }) {
  const [rec, setRec] = useState(null);
  const [picking, setPicking] = useState(false);
  // Opened once this dialog is up, so the picker stacks above it (Escape closes the picker first).
  useEffect(() => setPicking(true), []);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(null);
  const save = async () => {
    setBusy(true);
    try {
      const made = await linkPositionModel(position.id, { library_record_id: rec.id });
      onDone(made, `Attached ${rec.label} (${rec.source}) to ${position.name}.`);
    } catch (e) {
      setBusy(false);
      setFailed(saveErrorText(e, { offline: navigator.onLine === false }));
    }
  };
  return (
    <Modal title="From the data library" onClose={onClose} locked={busy} trapFocus className="ml-dialog"
           footer={(
             <>
               <button type="button" className="secondary" onClick={onClose} disabled={busy}>Cancel</button>
               <button type="button" onClick={save} disabled={busy || !rec} aria-busy={busy || undefined}>{busy ? "Attaching…" : "Attach"}</button>
             </>
           )}>
      <p className="rw-fhelp">A published failure rate as {position.name}’s model: an exponential at the record’s mean rate, its 5–95% range as the source’s uncertainty, and the record cited.</p>
      <PickedRecord record={rec} onPick={() => setPicking(true)} />
      {failed && <p className="field-error" role="alert">{failed}</p>}
      {picking && (
        <LibraryRecordPicker use={onBind ? "attach" : "model"} selectedId={rec?.id} onClose={() => setPicking(false)}
                             onPick={(r) => {
                               setPicking(false);
                               // A covariate model (NSWC-11): its covariates are fixed at the position next.
                               if (r.kind === "covariate_model" && onBind) onBind(r);
                               else setRec(r);
                             }} />
      )}
    </Modal>
  );
}

// The position's failure modes, read for the dialogs' "What is it for?" choice.
export function useModes(positionId) {
  const [modes, setModes] = useState(null);
  useEffect(() => {
    let live = true;
    getMaintenancePosition(positionId).then((p) => live && setModes(p.failure_modes || []), () => live && setModes([]));
    return () => { live = false; };
  }, [positionId]);
  return modes;
}

// "What is it for?": every failure of the position (none ticked), or the failure modes ticked.
export function ModesField({ modes, value, onChange }) {
  if (modes === null) return <p className="rim-tquiet">Reading its failure modes…</p>;
  return (
    <Field label="What is it for?" as="fieldset" help="Leave all unticked for every failure of this position.">
      {modes.length === 0 ? <p className="rim-tquiet">No failure modes yet: it's for every failure of this position.</p> : (
        <div className="ml-modes">
          {modes.map((m) => (
            <label key={m.id} className="ml-mode">
              <input type="checkbox" checked={value.includes(m.id)}
                     onChange={(e) => onChange(e.target.checked ? [...value, m.id] : value.filter((x) => x !== m.id))} />
              {m.text}
            </label>
          ))}
        </div>
      )}
    </Field>
  );
}

const KINDS = [
  { value: "model", label: "Non-repairable", load: listModels },
  { value: "recurrent_model", label: "Repairable", load: listRecurrentModels },
  { value: "degradation_model", label: "Degradation", load: listDegradationModels },
  { value: "alt_model", label: "Accelerated life", load: listAltModels },
];

// The model library: the user's models and the samples, of one kind.
function ModelPicker({ kind, onKind, value, onChange }) {
  const [list, setList] = useState(null);
  const [q, setQ] = useState("");
  useEffect(() => {
    let live = true;
    setList(null);
    (KINDS.find((k) => k.value === kind)?.load || listModels)()
      .then((out) => live && setList(out.models || []), () => live && setList([]));
    return () => { live = false; };
  }, [kind]);
  const shown = useMemo(() => (list || []).filter((m) => !q.trim() || m.name.toLowerCase().includes(q.trim().toLowerCase())), [list, q]);
  const groups = [["Yours", shown.filter((m) => !m.is_sample)], ["Samples", shown.filter((m) => m.is_sample)]];
  return (
    <div className="ml-picker">
      <SegmentedControl size="sm" label="Kind of model" value={kind} onChange={(v) => { onKind(v); onChange(null); }}
                        options={KINDS.map((k) => ({ value: k.value, label: k.label }))} />
      <TextInput type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search models" aria-label="Search models" />
      {list === null ? <p className="rim-tquiet">Loading models…</p> : shown.length === 0 ? (
        <p className="rim-tquiet">No models of this kind{q.trim() ? ` matching “${q.trim()}”` : ""}. Fit one under Models first.</p>
      ) : (
        <div className="evidence-picker" role="radiogroup" aria-label="Saved models">
          {groups.filter(([, g]) => g.length).map(([title, g]) => (
            <div key={title}>
              <div className="ml-group">{title}</div>
              {g.map((m) => (
                <label key={m.id} className={"evidence-option" + (value === m.id ? " selected" : "")}>
                  <input type="radio" name="ml-model" checked={value === m.id} onChange={() => onChange(m.id)} />
                  <span className="evidence-name">{m.name}</span>
                  <span className="evidence-meta">{[m.distribution, m.unit].filter(Boolean).join(" · ")}</span>
                </label>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// The dialogs: {kind: "fit" | "assign" | "class", position: {id, name}, link?: the model
// row's link (Refit… and Replace with… take its place)}.
export function ModelDialogs({ modal, onClose, onDone }) {
  if (!modal) return null;
  return <AttachModal key={`${modal.kind}:${modal.position.id}:${modal.link?.id || ""}`} modal={modal} onClose={onClose} onDone={onDone} />;
}

const TITLES = { fit: "Fit a model from history", assign: "Assign a saved model", class: "Assign the class's model" };

function AttachModal({ modal, onClose, onDone }) {
  const { kind, position, link } = modal;
  const modes = useModes(position.id);
  const [chosen, setChosen] = useState(() => (link?.failure_modes || []).map((f) => f.id));
  const [distribution, setDistribution] = useState(link?.source?.distribution || "weibull");
  const [scope, setScope] = useState(link?.source?.scope === "class" ? "class" : "auto");
  const [mkind, setMkind] = useState(link?.model_type || "model");
  const [modelId, setModelId] = useState(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(null);
  const refit = kind === "fit" && link;
  const title = refit ? "Refit the model" : link && kind === "assign" ? "Replace with another model" : TITLES[kind];
  const save = async () => {
    setBusy(true);
    setFailed(null);
    const body = { failure_mode_ids: chosen, ...(link ? { replace_link_id: link.id } : {}),
      ...(kind === "fit" ? { fit: true, distribution, scope } : kind === "class" ? { from_class: true } : { model_id: modelId, model_type: mkind }) };
    try {
      const made = await linkPositionModel(position.id, body);
      onDone(made, refit ? `Refitted ${made.name}.` : `Attached ${made.name} to ${position.name}.`);
    } catch (e) {
      setBusy(false);
      setFailed(saveErrorText(e, { offline: navigator.onLine === false }));
    }
  };
  return (
    <Modal title={title} onClose={onClose} locked={busy} trapFocus className="ml-dialog"
           footer={(
             <>
               <button type="button" className="secondary" onClick={onClose} disabled={busy}>Cancel</button>
               <button type="button" onClick={save} disabled={busy || (kind === "assign" && !modelId)} aria-busy={busy || undefined}>
                 {busy ? (kind === "fit" ? "Fitting…" : "Saving…") : kind === "fit" ? (refit ? "Refit" : "Fit and attach") : link ? "Replace" : "Attach"}
               </button>
             </>
           )}>
      <p className="rw-fhelp">
        {kind === "fit" && <>Fits a life distribution to {position.name}’s failures: each item’s days in service, ended by a failure or still running. With fewer than two failures of its own it pools its class’s positions instead. The model is saved to Models and linked here.</>}
        {kind === "assign" && <>Links a model from your library (or a sample) to {position.name}. It isn’t copied: a change in Models shows here.</>}
        {kind === "class" && <>Links the model fitted to {position.name}’s position class, pooled from every position of that class.</>}
      </p>
      {kind === "fit" && (
        <div className="ml-row">
          <Field label="Distribution">
            <Select value={distribution} onChange={(e) => setDistribution(e.target.value)}>
              <option value="weibull">Weibull (shape and life)</option>
              <option value="exponential">Exponential (a constant failure rate)</option>
              <option value="lognormal">Lognormal</option>
              <option value="gamma">Gamma</option>
              <option value="best">The best fit of these</option>
            </Select>
          </Field>
          <Field label="History">
            <Select value={scope} onChange={(e) => setScope(e.target.value)}>
              <option value="auto">Its own, else its class’s</option>
              <option value="position">Its own only</option>
              <option value="class">Its class’s pooled history</option>
            </Select>
          </Field>
        </div>
      )}
      {kind === "assign" && <ModelPicker kind={mkind} onKind={setMkind} value={modelId} onChange={setModelId} />}
      <ModesField modes={modes} value={chosen} onChange={setChosen} />
      {kind === "fit" && chosen.length > 0 && <p className="rim-tquiet">Failures by other modes count as still running at that age (suspensions).</p>}
      {failed && <p className="field-error" role="alert">{failed}</p>}
    </Modal>
  );
}

// Unlink… on a row: the model stays in Models.
export function unlinkModel(confirm, link, onDone) {
  const used = usedText(link);
  return confirm({
    title: `Unlink ${link.model?.name || link.name || "this model"}?`,
    body: `It comes off this position. The model stays in Models${used ? `; ${used} still use it there` : ""}.`,
    confirmLabel: "Unlink", pendingLabel: "Unlinking…", failedWhat: "unlink it",
    run: () => unlinkPositionModel(link.id).then(() => { onDone(`Unlinked ${link.model?.name || link.name}.`); return true; }),
  });
}

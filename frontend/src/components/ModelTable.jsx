import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  createModelFromParams, getMaintenancePosition, getPositionModel, linkPositionModel, listAltModels, listDegradationModels, listModels,
  listPositionModels, listRbds, listRecurrentModels, unlinkPositionModel, updateModelParams,
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
  MODEL_COLUMNS, b10Text, boundsLabel, countsText, enteredParams, enteredStart, exponentialLabel, fmt, forText, headline,
  implausibleExponential, meanText, rowActions, unitOne, unitWord, usedText, withBounds,
} from "../explorerModels.js";
import "./MeasurementTable.css";
import "./ModelTable.css";
import LibraryRecordPicker, { PickedRecord } from "./LibraryRecordPicker.jsx";

// The Explorer's Modelling tab is the tree with each position's life models in it
// (explorerModels.js), like the RCM and Measurements tabs. This file has what the page
// needs for it: the read of every attached model; each row's cells; its phone line;
// the details beside the table for a row picked (the plot, the parameters with bounds,
// the data behind it, what uses it, notes); and the dialogs that attach a model (assign a saved
// one, the class's) and take one off. Fitting is the fit pane (FitLifeModel.jsx).

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
    case "b10": return <span className="ml-num" title={(model.numbers || []).find((n) => n.id === "b10")?.note || undefined}>{b10Text(model)}</span>;
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

// The plot: reliability (with its 90% bounds, or a Bayesian update's credible band) or hazard over age, or a repairable
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
    const band = curves.band?.kind === "credible" ? `${Math.round(curves.band.level * 100)}% credible band`
      : `${Math.round((curves.band?.level ?? 0.9) * 100)}% bounds`;
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
                  <span key={n.id} className="ml-dlrow"><dt>{n.label}</dt><dd>{withBounds(n, model.credible_level)}
                    {n.note && <span className="rw-sum"> · {n.note}</span>}</dd></span>
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
          <thead><tr><th>Block</th><th>Model</th><th>Where its model came from</th><th>From</th></tr></thead>
          <tbody>
            {blocks.map((b) => (
              <tr key={b.id}>
                <td>{b.label}</td>
                <td>{b.placeholder ? <Chip tone="warning" title="A placeholder: no model in use for this position yet">Placeholder</Chip> : b.model}</td>
                <td>{b.placeholder ? "No model in use, from its class or inside it" : b.source || <span className="rw-blank">—</span>}</td>
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

// "New blank RBD…" (RBD ›): a diagram of the position's own, any position (a leaf included),
// linked here as its RBD (as a built one is) and opened in the table area. Which kind (default
// non-repairable), and what it starts with: empty, or one block for the position itself with its
// life model in use (the obvious start for a leaf; a placeholder, flagged, where it has none).
export function NewRbdModal({ position, hasInside = false, hasModel = false, onClose, onDone }) {
  const [repairable, setRepairable] = useState(false);
  const [start, setStart] = useState(!hasInside ? "self" : "blank");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(null);
  const save = async () => {
    setBusy(true);
    try {
      const made = await linkPositionModel(position.id, { new_rbd: { repairable, start } });
      onDone(made, `Started ${made.name}.${made.placeholders?.length ? " Its block is a placeholder until the position has a life model." : ""}`);
    } catch (e) {
      setBusy(false);
      setFailed(saveErrorText(e, { offline: navigator.onLine === false }));
    }
  };
  return (
    <Modal title="New blank RBD" onClose={onClose} locked={busy} trapFocus className="ml-dialog"
           footer={(
             <>
               <button type="button" className="secondary" onClick={onClose} disabled={busy}>Cancel</button>
               <button type="button" onClick={save} disabled={busy} aria-busy={busy || undefined}>{busy ? "Starting…" : "Start the RBD"}</button>
             </>
           )}>
      <p className="rw-fhelp">A new diagram for {position.name}, saved in your RBDs and linked here as its RBD. It opens beside the tree.</p>
      <Field label="Kind">
        <SegmentedControl label="Kind of RBD" value={repairable ? "repairable" : "non"} onChange={(v) => setRepairable(v === "repairable")}
                          options={[{ value: "non", label: "Non-repairable" }, { value: "repairable", label: "Repairable" }]} />
      </Field>
      <p className="rw-fhelp">{repairable
        ? "Repairable: blocks are repaired when they fail, and the answer is availability (with maintenance read from the tree)."
        : "Non-repairable: the answer is the system's reliability and life."}</p>
      <div className="evidence-picker" role="radiogroup" aria-label="Start with">
        <label className={"evidence-option" + (start === "self" ? " selected" : "")}>
          <input type="radio" name="nr-start" checked={start === "self"} onChange={() => setStart("self")} />
          <span className="evidence-name">One block for {position.name}</span>
          <span className="rim-tquiet"> {hasModel ? "its life model in use" : "a placeholder until it has a life model"}</span>
        </label>
        <label className={"evidence-option" + (start === "blank" ? " selected" : "")}>
          <input type="radio" name="nr-start" checked={start === "blank"} onChange={() => setStart("blank")} />
          <span className="evidence-name">Empty</span>
          <span className="rim-tquiet"> just In and Out: draw the blocks yourself</span>
        </label>
      </div>
      {failed && <p className="field-error" role="alert">{failed}</p>}
    </Modal>
  );
}

// "Enter parameters…" (Life model ›): a model from numbers you have (a data sheet, a handbook,
// a vendor's figures), saved to Models through the usual save from parameters and attached here.
// An exponential is given as an MTBF (a handbook's figure) or a failure rate, the unit shown, and a
// figure that can't be what was meant says so. With `link` (Edit parameters… on a row whose model
// was typed in), the same form changes that model's numbers in place.
const PARAMS = {
  weibull: [["alpha", "Characteristic life (alpha)"], ["beta", "Shape (beta)"]],
  exponential: [["failure_rate", "Failure rate"]],
  lognormal: [["mu", "mu (log of the median)"], ["sigma", "sigma (spread)"]],
  normal: [["mu", "Mean (mu)"], ["sigma", "Standard deviation (sigma)"]],
  gamma: [["alpha", "alpha (shape)"], ["beta", "beta (rate)"]],
};
const PARAM_UNITS = ["hours", "days", "weeks", "months", "years", "cycles"];
export function ParamsModal({ position, link = null, onClose, onDone }) {
  const entered = link?.model?.entered || null;
  const [distribution, setDistribution] = useState(entered?.distribution && PARAMS[entered.distribution] ? entered.distribution : "weibull");
  const [values, setValues] = useState(() => (entered ? enteredStart(entered) : {}));
  const [unit, setUnit] = useState(() => {
    const u = String(entered?.unit || "hours").toLowerCase();
    return PARAM_UNITS.includes(u) ? u : "hours";
  });
  // An exponential's figure: an MTBF (what handbooks give) or a failure rate.
  const [expAs, setExpAs] = useState("mtbf");
  const [name, setName] = useState(link ? (link.model?.name || link.name || "") : `${position.name} (entered)`);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(null);
  const names = PARAMS[distribution];
  const ok = (link || name.trim()) && names.every(([k]) => Number(values[k]) > 0 || (k === "mu" && Number.isFinite(Number(values[k])) && values[k] !== ""));
  const odd = distribution === "exponential" ? implausibleExponential(expAs, values.failure_rate, unit) : null;
  const save = async () => {
    setBusy(true);
    setFailed(null);
    const params = enteredParams(distribution, names, values, expAs);
    try {
      if (link) {
        const model = await updateModelParams(link.model_id, { distribution, params, unit });
        onDone(null, `Changed ${model.name}'s parameters: everything using it now takes them.`);
        return;
      }
      const model = await createModelFromParams(name.trim(), distribution, params, { unit });
      const made = await linkPositionModel(position.id, { model_id: model.id, model_type: "model" });
      onDone(made, `Saved ${model.name} and attached it to ${position.name}.`);
    } catch (e) {
      setBusy(false);
      setFailed(saveErrorText(e, { offline: navigator.onLine === false }));
    }
  };
  return (
    <Modal title={link ? "Edit parameters" : "Enter parameters"} onClose={onClose} locked={busy} trapFocus className="ml-dialog"
           footer={(
             <>
               <button type="button" className="secondary" onClick={onClose} disabled={busy}>Cancel</button>
               <button type="button" onClick={save} disabled={busy || !ok} aria-busy={busy || undefined}>
                 {busy ? "Saving…" : link ? "Save" : "Save and attach"}
               </button>
             </>
           )}>
      <p className="rw-fhelp">
        {link
          ? `${name || "This model"}'s parameters were typed in. Change them here: every position, RBD block and calculation that uses it takes the new numbers.`
          : `A life model from numbers you have: a data sheet, a handbook or the vendor’s figures. It’s saved to Models (with no data behind it, so its row says Assumed) and attached to ${position.name}.`}
      </p>
      <div className="ml-row">
        <Field label="Distribution">
          <Select value={distribution} onChange={(e) => { setDistribution(e.target.value); setValues({}); }}>
            <option value="weibull">Weibull</option><option value="exponential">Exponential</option>
            <option value="lognormal">Lognormal</option><option value="normal">Normal</option><option value="gamma">Gamma</option>
          </Select>
        </Field>
        <Field label="Unit">
          <Select value={unit} onChange={(e) => setUnit(e.target.value)}>
            {PARAM_UNITS.map((x) => <option key={x} value={x}>{x}</option>)}
          </Select>
        </Field>
      </div>
      {distribution === "exponential" && (
        <Field label="Give it as" as="fieldset">
          <div className="ml-modes">
            <label className="ml-mode">
              <input type="radio" name="exp-as" checked={expAs === "mtbf"}
                     onChange={() => { setExpAs("mtbf"); setValues({}); }} />
              MTBF ({unit} between failures)
            </label>
            <label className="ml-mode">
              <input type="radio" name="exp-as" checked={expAs === "rate"}
                     onChange={() => { setExpAs("rate"); setValues({}); }} />
              Failure rate (failures per {unitOne(unit)})
            </label>
          </div>
        </Field>
      )}
      <div className="ml-row">
        {names.map(([k, label]) => (
          <Field key={k} label={distribution === "exponential" ? exponentialLabel(expAs, unit) : label}>
            <TextInput inputMode="decimal" value={values[k] || ""} onChange={(e) => setValues((v) => ({ ...v, [k]: e.target.value }))} />
          </Field>
        ))}
      </div>
      {odd && <p className="field-warning" role="status">{odd}</p>}
      {!link && <Field label="Name"><TextInput value={name} onChange={(e) => setName(e.target.value)} /></Field>}
      {failed && <p className="field-error" role="alert">{failed}</p>}
    </Modal>
  );
}

// Life model › From the data library…: a record attached as the position's model. A published record
// goes on to the fix-covariates pane (its covariates fixed here, the rest set in the RBD); a life
// record from a library of your own is attached as it is. The record comes from "Pick a library
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
                               // A record with covariates (every published one but a life model): which are
                               // fixed at the position, and which are set in the RBD, next.
                               if (r.kind !== "life" && onBind) onBind(r);
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

// The dialogs: {kind: "assign" | "class", position: {id, name}, link?: the model row's link
// (Replace with… takes its place)}.
export function ModelDialogs({ modal, onClose, onDone }) {
  if (!modal) return null;
  return <AttachModal key={`${modal.kind}:${modal.position.id}:${modal.link?.id || ""}`} modal={modal} onClose={onClose} onDone={onDone} />;
}

const TITLES = { assign: "Assign a saved model", class: "Assign the class's model" };

function AttachModal({ modal, onClose, onDone }) {
  const { kind, position, link } = modal;
  const modes = useModes(position.id);
  const [chosen, setChosen] = useState(() => (link?.failure_modes || []).map((f) => f.id));
  const [mkind, setMkind] = useState(link?.model_type || "model");
  const [modelId, setModelId] = useState(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(null);
  const title = link && kind === "assign" ? "Replace with another model" : TITLES[kind];
  const save = async () => {
    setBusy(true);
    setFailed(null);
    const body = { failure_mode_ids: chosen, ...(link ? { replace_link_id: link.id } : {}),
      ...(kind === "class" ? { from_class: true } : { model_id: modelId, model_type: mkind }) };
    try {
      const made = await linkPositionModel(position.id, body);
      onDone(made, `Attached ${made.name} to ${position.name}.`);
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
                 {busy ? "Saving…" : link ? "Replace" : "Attach"}
               </button>
             </>
           )}>
      <p className="rw-fhelp">
        {kind === "assign" && <>Links a model from your library (or a sample) to {position.name}. It isn’t copied: a change in Models shows here.</>}
        {kind === "class" && <>Links the model fitted to {position.name}’s position class, pooled from every position of that class.</>}
      </p>
      {kind === "assign" && <ModelPicker kind={mkind} onKind={setMkind} value={modelId} onChange={setModelId} />}
      <ModesField modes={modes} value={chosen} onChange={setChosen} />
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

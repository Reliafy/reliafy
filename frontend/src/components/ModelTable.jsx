import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  getMaintenancePosition, getPositionModel, linkPositionModel, listAltModels, listDegradationModels, listModels,
  listPositionModels, listRecurrentModels, unlinkPositionModel,
} from "../api.js";
import Chip from "./ui/Chip.jsx";
import Field from "./ui/Field.jsx";
import { Select, TextInput } from "./ui/Controls.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import Modal from "./Modal.jsx";
import Plot from "./Plot.jsx";
import { CloseIcon, ExpandIcon, ShrinkIcon } from "./icons.jsx";
import { ACCENT, BAND_FILL } from "../plotTheme.js";
import { saveErrorText } from "../confirm.js";
import { explorerHere } from "../products.js";
import {
  MODEL_COLUMNS, b10Text, boundsLabel, countsText, fmt, forText, headline, meanText, rowActions, unitWord, usedText, withBounds,
} from "../explorerModels.js";
import "./MeasurementTable.css";
import "./ModelTable.css";

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
    case "kind": return <Chip tone={model.family === "life" ? "accent" : "neutral"} className="pk-kind">{model.kind || "Model"}</Chip>;
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
  useEffect(() => {
    let live = true;
    getPositionModel(link.id).then((data) => live && setState({ id: link.id, data, error: null }),
      (e) => live && setState({ id: link.id, data: null, error: e.message }));
    return () => { live = false; };
  }, [link.id]);
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
              {model.path && <Link to={model.path}>Open in Models</Link>}</p>
            {state.error && <p className="field-error">Couldn't read it: {state.error}</p>}
            {!d && !state.error && <p className="rim-tquiet">Reading the model…</p>}
            {d && <ModelPlot curves={d.curves} unit={unit} name={r.ref.name} />}
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

// The position's failure modes, read for the dialogs' "What is it for?" choice.
function useModes(positionId) {
  const [modes, setModes] = useState(null);
  useEffect(() => {
    let live = true;
    getMaintenancePosition(positionId).then((p) => live && setModes(p.failure_modes || []), () => live && setModes([]));
    return () => { live = false; };
  }, [positionId]);
  return modes;
}

// "What is it for?": every failure of the position (none ticked), or the failure modes ticked.
function ModesField({ modes, value, onChange }) {
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

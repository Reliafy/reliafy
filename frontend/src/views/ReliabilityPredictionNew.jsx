import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  computePrediction, getPrediction, getPredictionEnvironments, getPredictionLinesFromProduct, listProducts,
  savePrediction, updatePrediction,
} from "../api.js";
import { useAppConfig } from "../ConfigProvider.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";
import { CapRefusal } from "../components/StorageCap.jsx";
import Field from "../components/ui/Field.jsx";
import { TextArea, TextInput } from "../components/ui/Controls.jsx";
import InputGroup, { Addon } from "../components/ui/InputGroup.jsx";
import Select from "../components/Select.jsx";
import Chip from "../components/ui/Chip.jsx";
import PartTypeCell from "../components/PartTypeCell.jsx";
import ConditionsModal from "../components/ConditionsModal.jsx";
import { conditionsLabel, isCovariateLine } from "../predictionPane.js";
import PredictionResult from "../components/PredictionResult.jsx";
import { TrashIcon } from "../components/LibRows.jsx";
import { ShowMe } from "../components/SectionPage.jsx";
import { useConfirm } from "../components/ConfirmProvider.jsx";
import { itemName } from "../components/LibRows.jsx";
import {
  DEFAULT_ENVIRONMENT, DEFAULT_MISSION_HOURS, PREDICTIONS_GUIDE, PREDICTIONS_LABEL, PREDICTIONS_PATH, blankLine,
  defaultQuality, lineFromServer, linesForServer, linesFromSaved, linesProblem, parsePartsList, predictionPath,
  qualityHint,
} from "../predictions.js";
import { productPath } from "../products.js";
import "./Predictions.css";

const HELP = { guide: PREDICTIONS_GUIDE };
const PASTE_HINT = "One part per line: name, quantity, assembly (commas or tabs), or \"4 x Motor\". The quantity is 1 when left out.";

// The builder: a parts list (typed, pasted, or a product's), each line's
// handbook part type and quality factor, the environment and the mission
// time; Calculate, then Save. ?product= starts from a product's parts list;
// ?from= from a saved prediction (yours: Save changes it; a sample or someone
// else's: Save makes your own copy).
export default function ReliabilityPredictionNew() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const fromId = params.get("from");
  const productId = params.get("product");
  const { maintenance } = useAppConfig();
  const confirm = useConfirm();

  const [name, setName] = useState("");
  const [environment, setEnvironment] = useState(DEFAULT_ENVIRONMENT);
  const [missionTime, setMissionTime] = useState(String(DEFAULT_MISSION_HOURS));
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState([blankLine()]);
  const [product, setProduct] = useState(null);
  const [editing, setEditing] = useState(null); // the saved prediction being changed (own)
  const [envs, setEnvs] = useState([]);
  const [products, setProducts] = useState(null);
  const [chosenProduct, setChosenProduct] = useState("");
  const [paste, setPaste] = useState(null); // the paste box's text, or null when closed
  const [loading, setLoading] = useState(Boolean(fromId || productId));
  const [loadError, setLoadError] = useState(null);
  const [results, setResults] = useState(null);
  const [computedFor, setComputedFor] = useState(null);
  const [computing, setComputing] = useState(false);
  const [error, setError] = useState(null);
  const [capError, setCapError] = useState(null); // a save refused at the Free storage limit
  const [conditionsOf, setConditionsOf] = useState(null); // the line whose NSWC-11 conditions are open
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getPredictionEnvironments()
      .then((d) => setEnvs(d.environments || []))
      .catch(() => setEnvs([]));
  }, []);
  useEffect(() => {
    if (!maintenance) return;
    listProducts().then((d) => setProducts(d.products || [])).catch(() => setProducts([]));
  }, [maintenance]);

  // Prefill from a saved prediction or a product.
  useEffect(() => {
    let live = true;
    if (fromId) {
      getPrediction(fromId)
        .then((doc) => {
          if (!live) return;
          const own = !doc.read_only;
          setEditing(own ? doc : null);
          setName(own ? doc.name : `${itemName(doc)} (copy)`);
          setEnvironment(doc.inputs?.environment || DEFAULT_ENVIRONMENT);
          setMissionTime(String(doc.inputs?.mission_time ?? DEFAULT_MISSION_HOURS));
          setNotes(doc.inputs?.notes || "");
          setProduct(doc.inputs?.product || null);
          setLines(linesFromSaved(doc));
          setResults(doc.results || null);
          // The key of what the builder will send for these lines unchanged,
          // so a saved prediction opens with its results current, not stale.
          const edit = linesFromSaved(doc);
          setComputedFor(keyOf(linesForServer(edit), doc.inputs?.environment, doc.inputs?.mission_time, edit));
        })
        .catch((e) => live && setLoadError(e.message))
        .finally(() => live && setLoading(false));
    } else if (productId) {
      loadProduct(productId, { silent: true }).finally(() => live && setLoading(false));
    }
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fromId, productId]);

  async function loadProduct(id, { silent = false } = {}) {
    try {
      const out = await getPredictionLinesFromProduct(id);
      const kept = lines.filter((l) => String(l.name || "").trim());
      if (!silent && kept.length && !(await confirm({
        title: "Replace the parts list?",
        body: `The ${kept.length} ${kept.length === 1 ? "line" : "lines"} here will be replaced by the parts list of ${out.product.name}.`,
        confirmLabel: "Replace",
      }))) return;
      setProduct(out.product);
      setLines(out.lines.length ? out.lines.map(lineFromServer) : [blankLine()]);
      if (!name.trim()) setName(out.product.name);
      setError(out.warnings?.length ? out.warnings.join(" ") : null);
      setResults(null);
    } catch (e) {
      setError(`The product's parts list didn't load: ${e.message}`);
    }
  }

  const inputs = useMemo(() => ({
    lines: linesForServer(lines),
    environment,
    mission_time: Number(missionTime),
    ...(product ? { product } : {}),
    ...(notes.trim() ? { notes: notes.trim() } : {}),
  }), [lines, environment, missionTime, product, notes]);
  const problem = linesProblem(lines)
    || (!(Number(missionTime) > 0) ? "Give a mission time in hours." : null);
  const key = keyOf(inputs.lines, environment, Number(missionTime), lines);
  const stale = results && computedFor !== key;

  const setLine = (i, patch) => setLines((cur) => cur.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  const removeLine = (i) => setLines((cur) => (cur.length > 1 ? cur.filter((_, j) => j !== i) : [blankLine()]));
  const addLine = () => setLines((cur) => [...cur, blankLine()]);
  const addPasted = () => {
    const parsed = parsePartsList(paste);
    if (!parsed.length) {
      setError("Nothing to add: one part per line, with its quantity after a comma.");
      return;
    }
    setLines((cur) => [...cur.filter((l) => String(l.name || "").trim()), ...parsed]);
    setPaste(null);
    setError(null);
  };

  const calculate = async () => {
    setComputing(true);
    setError(null);
    try {
      const out = await computePrediction(inputs.lines, environment, Number(missionTime));
      setResults(out);
      setComputedFor(key);
    } catch (e) {
      setError(e.message);
    } finally {
      setComputing(false);
    }
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    setCapError(null);
    try {
      const doc = editing
        ? await updatePrediction(editing.id, { name: name.trim(), inputs })
        : await savePrediction(name.trim(), inputs);
      navigate(predictionPath(doc.id));
    } catch (e) {
      if (e.code === "cap") setCapError(e);
      else setError(e.message);
      setSaving(false);
    }
  };

  const envOptions = envs.map((e) => ({ value: e.code, label: `${e.code} · ${e.name}`, hint: e.covers }));
  const envCovers = envs.find((e) => e.code === environment)?.covers;
  const typed = lines.filter((l) => String(l.name || "").trim());
  const assigned = typed.filter((l) => !l.excluded && (l.record_id || String(l.user_rate ?? "").trim() !== "")).length;
  const leftOut = typed.filter((l) => l.excluded).length;
  const canSave = Boolean(results && !stale && name.trim() && !problem);

  if (loadError) {
    return (
      <div className="app">
        <PageHeader crumbs={[{ label: PREDICTIONS_LABEL, to: PREDICTIONS_PATH }]} title="New prediction" />
        <div className="card error">It didn't load: {loadError} <Link to={PREDICTIONS_PATH}>Back to predictions</Link></div>
      </div>
    );
  }
  if (loading) return <div className="app"><div className="card empty">Loading…</div></div>;

  return (
    <div className="app pred-new">
      <PageHeader
        crumbs={[{ label: PREDICTIONS_LABEL, to: PREDICTIONS_PATH }]}
        title={editing ? `Edit ${editing.name}` : "New prediction"}
        badges={editing ? null : (fromId ? <Chip>Copy</Chip> : null)}
        meta={<>A parts count: each line's handbook rate for the environment × a quality factor × its quantity, added up. <ShowMe help={HELP} /></>}
        primary={<button onClick={save} disabled={!canSave || saving}>{saving ? "Saving…" : editing ? "Save changes" : "Save prediction"}</button>}
      />

      <div className="pred-grid">
        <section className="card pred-setup">
          <h2>Conditions</h2>
          <Field label="Name">
            <TextInput value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Controller box, rev B" />
          </Field>
          <Field label="Environment" help={envCovers || "Where the equipment works: the handbook's factor for each part depends on it."}>
            <Select ariaLabel="Environment" value={environment} onChange={(v) => setEnvironment(v)}
                    options={envOptions.length ? envOptions : [{ value: environment, label: environment }]} />
          </Field>
          <Field label="Mission time" help="Reliability is the chance of no failure over this long: R(t) = exp(−λt).">
            <InputGroup label="Mission time">
              <TextInput type="number" inputMode="decimal" min="0" step="any" value={missionTime} onChange={(e) => setMissionTime(e.target.value)} />
              <Addon>hours</Addon>
            </InputGroup>
          </Field>
          <Field label="Notes" optional>
            <TextArea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Where the parts list came from, what's left out…" />
          </Field>
          {product && (
            <p className="hint">
              From the product <b>{product.name}</b>{product.rev ? `, rev ${product.rev}` : ""}{product.part_number ? ` (part ${product.part_number})` : ""}
              {product.id && maintenance ? <> · <Link to={productPath(product.id, "parts")}>its parts list</Link></> : null}.
            </p>
          )}
        </section>

        <section className="card pred-lines">
          <div className="card-head">
            <h2>Parts list</h2>
            <div className="card-head-actions pred-lines-actions">
              {maintenance && products && products.length > 0 && (
                <div className="pred-from-product">
                  <Select ariaLabel="Product" placeholder="From a product…" value={chosenProduct} onChange={setChosenProduct}
                          options={products.map((p) => ({ value: p.id, label: p.name }))} />
                  <button type="button" className="secondary sm" disabled={!chosenProduct} onClick={() => loadProduct(chosenProduct)}>Load parts list</button>
                </div>
              )}
              <button type="button" className="secondary sm" onClick={() => setPaste((p) => (p == null ? "" : null))} aria-expanded={paste != null}>Paste a list</button>
              <button type="button" className="secondary sm" onClick={addLine}>Add a line</button>
            </div>
          </div>
          {paste != null && (
            <div className="pred-paste">
              <Field label="Parts to add" help={PASTE_HINT}>
                <TextArea rows={5} value={paste} onChange={(e) => setPaste(e.target.value)} placeholder={"Ceramic capacitor, 48, Flight controller\nChip resistor, 62, Flight controller\n4 x Brushless motor"} />
              </Field>
              <div className="row pred-paste-actions">
                <button type="button" className="secondary" onClick={() => setPaste(null)}>Cancel</button>
                <button type="button" onClick={addPasted}>Add these lines</button>
              </div>
            </div>
          )}
          <div className="pred-scroll">
            <table className="lib-table pred-table pred-edit">
              <thead>
                <tr>
                  <th>Part</th>
                  <th>Assembly</th>
                  <th className="num">Qty</th>
                  <th>Handbook part type</th>
                  <th className="num" title="πQ: the handbook's factor for the part's quality grade. Left blank, the part type's default (1, or the lowest grade for a parts-count type such as a commercial microcircuit); each part type's grades show on the box.">Quality factor</th>
                  <th><span className="sr-only">Remove</span></th>
                </tr>
              </thead>
              <tbody>
                {lines.map((l, i) => (
                  <tr key={i}>
                    <td>
                      <input type="text" value={l.name} aria-label={`Part ${i + 1}`} placeholder="Part" onChange={(e) => setLine(i, { name: e.target.value })} />
                      {l.reference && <div className="lib-date">{l.reference}</div>}
                    </td>
                    <td><input type="text" value={l.assembly} aria-label={`Assembly of part ${i + 1}`} placeholder="optional" onChange={(e) => setLine(i, { assembly: e.target.value })} /></td>
                    <td className="num"><input type="number" inputMode="decimal" min="0" step="any" value={l.quantity} aria-label={`Quantity of part ${i + 1}`} onChange={(e) => setLine(i, { quantity: e.target.value })} /></td>
                    <td>
                      <PartTypeCell name={`part ${i + 1}`} record={l.record} rate={l.user_rate} rateMode={l.rate_mode} excluded={l.excluded}
                                    onChange={(c) => setLine(i, {
                                      ...("record" in c ? { record: c.record, record_id: c.record ? c.record.id : null, conditions: {}, cycles_per_hour: "" } : {}),
                                      ...("rate" in c ? { user_rate: c.rate } : {}),
                                      ...("rateMode" in c ? { rate_mode: c.rateMode } : {}),
                                      ...("excluded" in c ? { excluded: c.excluded } : {}),
                                    })} />
                    </td>
                    <td className="num">
                      {isCovariateLine(l) ? (
                        <button type="button" className="secondary sm" aria-label={`Conditions of part ${i + 1}`} onClick={() => setConditionsOf(i)}>
                          {conditionsLabel(l)}
                        </button>
                      ) : (
                        <input type="number" inputMode="decimal" min="0" step="any" value={l.quality_factor} placeholder={defaultQuality(l.record)} aria-label={`Quality factor of part ${i + 1}`}
                               title={qualityHint(l.record)}
                               disabled={!l.record_id || l.excluded} onChange={(e) => setLine(i, { quality_factor: e.target.value })} />
                      )}
                    </td>
                    <td className="lib-actions">
                      <div className="lib-acts">
                        <button type="button" className="act del" title="Remove" aria-label={`Remove part ${i + 1}`} onClick={() => removeLine(i)}><TrashIcon /></button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="hint pred-count">
            {typed.length} {typed.length === 1 ? "line" : "lines"}, {assigned} with a part type or a rate{leftOut ? `, ${leftOut} not electronic` : ""}.
            {" "}The handbook covers electronic parts only: tick “Not electronic” for mechanical parts (airframe, propellers) to leave them out,
            and give a part it doesn’t have (a battery) a rate of your own. Lines with neither stay in the list and are left out of the total.
          </p>
        </section>
      </div>

      <div className="pred-actions">
        <button onClick={calculate} disabled={Boolean(problem) || computing}>{computing ? "Calculating…" : "Calculate"}</button>
        {problem && <span className="hint">{problem}</span>}
        {!problem && stale && <span className="hint">The inputs changed: calculate again before saving.</span>}
        {!problem && results && !stale && !name.trim() && <span className="hint">Give it a name, then Save prediction.</span>}
      </div>
      {error && <div className="card error" role="alert">{error}</div>}
      <CapRefusal error={capError} />

      {results && (
        <section className={"card pred-result-card" + (stale ? " is-stale" : "")} aria-live="polite">
          <PredictionResult results={results} name={name || "Reliability prediction"} />
        </section>
      )}
      {conditionsOf != null && lines[conditionsOf] && (
        <ConditionsModal line={{ ...lines[conditionsOf], name: lines[conditionsOf].name || `part ${conditionsOf + 1}` }}
                         onClose={() => setConditionsOf(null)}
                         onDone={(c) => { setLine(conditionsOf, c); setConditionsOf(null); }} />
      )}
    </div>
  );
}

// What a result was computed for, so a changed input marks it stale.
function keyOf(serverLines, environment, missionTime, editLines) {
  const records = (editLines || []).map((l) => (l.excluded ? "excluded" : l.record_id || ""));
  return JSON.stringify([serverLines, environment, Number(missionTime), records]);
}

import { useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { SectionHeader } from "../components/SectionPage.jsx";
import { CapRefusal } from "../components/StorageCap.jsx";
import Card from "../components/ui/Card.jsx";
import Field from "../components/ui/Field.jsx";
import InputGroup, { Addon } from "../components/ui/InputGroup.jsx";
import { TextInput } from "../components/ui/Controls.jsx";
import Modal from "../components/Modal.jsx";
import Select from "../components/Select.jsx";
import MaintainabilityResult from "../components/MaintainabilityResult.jsx";
import { PlusIcon, TrashIcon } from "../components/LibRows.jsx";
import { useAppConfig } from "../ConfigProvider.jsx";
import {
  analyseMaintainability, getProductMaintainabilityLines, listProducts, saveMaintainabilityPrediction,
} from "../api.js";
import { formatNumber } from "../format.js";
import {
  ELEMENTS, MAINTAINABILITY_GUIDE, MAINTAINABILITY_PATH, RATE_UNITS, UNITS, emptyForm, emptyLine, formProblem,
  fromInputs, hasElements, isBlank, lineMttr, linesFromProduct, parsePartsList, rateUnitText, toInputs,
} from "../maintainability.js";
import "./Maintainability.css";

const HELP = { guide: MAINTAINABILITY_GUIDE };

// Modelling › Maintainability prediction › New: a parts list (a product's,
// pasted, or typed), each line's repair time by element and its failure
// rate, then Compute (nothing saved) and Save.
export default function MaintainabilityNewPage() {
  const { maintenance } = useAppConfig();
  const { state } = useLocation();
  const [form, setForm] = useState(() => (state?.inputs ? fromInputs(state.inputs) : emptyForm()));
  const [result, setResult] = useState(null);
  const [ranWith, setRanWith] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [capError, setCapError] = useState(null); // a save refused at the Free storage limit
  const [paste, setPaste] = useState(null); // the pasted text while the dialog is open
  const [products, setProducts] = useState(null);
  const [productNote, setProductNote] = useState(null);
  const [saving, setSaving] = useState(null); // { name } while the save dialog is open
  const [savedId, setSavedId] = useState(null);
  // The five element columns show only when asked for (or when a line has
  // them): the common case is one repair time per line, in a short table.
  const [split, setSplit] = useState(() => (state?.inputs?.lines || []).some((l) => l.elements && Object.keys(l.elements).length));

  useEffect(() => {
    if (!maintenance) return;
    listProducts().then((d) => setProducts(d.products || [])).catch(() => setProducts([]));
  }, [maintenance]);
  const anyElements = form.lines.some(hasElements);
  useEffect(() => {
    if (anyElements) setSplit(true);
  }, [anyElements]);

  const problem = useMemo(() => formProblem(form), [form]);
  const set = (patch) => setForm((f) => ({ ...f, ...patch }));
  const setLine = (i, patch) => setForm((f) => {
    const lines = f.lines.map((l, k) => (k === i ? { ...l, ...patch } : l));
    // Always a blank row at the end to type into.
    if (i === lines.length - 1 && !isBlank(lines[i])) lines.push(emptyLine());
    return { ...f, lines };
  });
  const setElement = (i, key, value) => setForm((f) => {
    const lines = f.lines.map((l, k) => (k === i ? { ...l, elements: { ...l.elements, [key]: value } } : l));
    if (i === lines.length - 1 && !isBlank(lines[i])) lines.push(emptyLine());
    return { ...f, lines };
  });
  const removeLine = (i) => setForm((f) => {
    const lines = f.lines.filter((_, k) => k !== i);
    return { ...f, lines: lines.length ? lines : [emptyLine()] };
  });
  const replaceLines = (lines) => setForm((f) => ({ ...f, lines: [...lines, emptyLine()] }));

  const pickProduct = async (id) => {
    const product = (products || []).find((p) => p.id === id) || null;
    setProductNote(null);
    if (!product) {
      set({ product: null });
      return;
    }
    try {
      const data = await getProductMaintainabilityLines(id);
      const lines = linesFromProduct(data);
      set({ product: { id: product.id, name: product.name }, lines: [...lines, emptyLine()] });
      if (data.note) setProductNote(data.note);
      else if (data.rates?.source === "reliability_prediction") {
        setProductNote(`${lines.length} lines from ${product.name}'s parts list; failure rates from the reliability prediction “${data.rates.prediction?.name}” on ${data.rates.matched} of them.`);
      } else setProductNote(`${lines.length} lines from ${product.name}'s parts list. Type each line's repair times; add failure rates to weight them.`);
    } catch (e) {
      setError(e.message);
    }
  };

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const inputs = toInputs(form);
      setResult(await analyseMaintainability(inputs));
      setRanWith(inputs);
      setSavedId(null);
    } catch (e) {
      setError(e.message);
      setResult(null);
    } finally {
      setBusy(false);
    }
  };

  const onSave = async () => {
    setBusy(true);
    setError(null);
    setCapError(null);
    try {
      const doc = await saveMaintainabilityPrediction(saving.name.trim(), ranWith);
      setSavedId(doc.id);
      setSaving(null);
    } catch (e) {
      if (e.code === "cap") {
        setSaving(null);
        setCapError(e);
      } else {
        setError(e.message);
      }
    } finally {
      setBusy(false);
    }
  };

  const defaultName = form.product?.name ? `${form.product.name} — maintainability` : (state?.name || "Maintainability prediction");
  const unitWord = form.unit === "hours" ? "h" : "min";
  const productOptions = [{ value: "", label: "Start from a product…" },
    ...(products || []).map((p) => ({ value: p.id, label: p.name, hint: p.part?.part_number || "" }))];

  return (
    <div className="app">
      <SectionHeader
        section="maintainability"
        title="New maintainability prediction"
        purpose="List what can fail and how long each repair takes; Reliafy works out the mean repair time, the time most repairs are done by, availability and what drives them."
        help={HELP}
      />

      <Card>
        <div className="mp-start">
          {maintenance && products && products.length > 0 && (
            <Select ariaLabel="Start from a product" value={form.product?.id || ""} onChange={pickProduct} options={productOptions} />
          )}
          <button type="button" className="secondary" onClick={() => setPaste("")}>Paste a parts list</button>
          {!form.lines.some((l) => !isBlank(l)) && <span className="muted-line">…or type the lines below.</span>}
          {form.product && <span className="muted-line">Product: <Link to={`/products/${encodeURIComponent(form.product.id)}`}>{form.product.name}</Link></span>}
        </div>
        {productNote && <p className="muted-line">{productNote}</p>}

        <div className="mp-settings">
          <Field label="Repair times in" help="Every time below, and the results.">
            <Select ariaLabel="Repair times in" value={form.unit} onChange={(v) => set({ unit: v })} options={UNITS} />
          </Field>
          <Field label="Failure rates in" help="How often each line fails: its weight. Leave the column blank for equal weights.">
            <Select ariaLabel="Failure rate unit" value={form.failure_rate_unit} onChange={(v) => set({ failure_rate_unit: v })} options={RATE_UNITS} />
          </Field>
          <Field label="Most repairs done by" help="M_max is the time this share of repairs are done by; 95 is usual.">
            <InputGroup label="Most repairs done by">
              <TextInput inputMode="decimal" value={form.percentile} onChange={(e) => set({ percentile: e.target.value })} />
              <Addon>%</Addon>
            </InputGroup>
          </Field>
          <Field label="System MTBF" optional help="For availability, instead of 1 ÷ the summed failure rates.">
            <InputGroup label="System MTBF">
              <TextInput inputMode="decimal" value={form.mtbf} onChange={(e) => set({ mtbf: e.target.value })} />
              <Addon>hours</Addon>
            </InputGroup>
          </Field>
        </div>

        <label className="mp-split" title={anyElements ? "Some lines have elements: clear them to give one time per line." : undefined}>
          <input type="checkbox" checked={split || anyElements} disabled={anyElements} onChange={(e) => setSplit(e.target.checked)} />
          <span>Split repair times into elements (isolate, access, replace, restore, check out)</span>
        </label>

        <div className={"mp-lines maint-scroll" + (split || anyElements ? " is-split" : "")}>
          <table className="lib-table">
            <thead>
              <tr>
                <th>Ref</th>
                <th>Name</th>
                <th>Assembly</th>
                <th className="mp-el">Qty</th>
                <th className="mp-el">Failure rate<span className="th-unit">{rateUnitText(form.failure_rate_unit)}</span></th>
                {(split || anyElements) && ELEMENTS.map((e) => <th key={e.key} className="mp-el" title={`${e.label}: ${e.help}`}>{e.short} ({unitWord})</th>)}
                <th className="mp-el" title={split || anyElements ? "The line's mean repair time: the sum of its elements, or typed when they're blank" : "The line's mean time to repair"}>MTTR ({unitWord})</th>
                <th className="mp-el" title="Optional: the time most (95%) of this line's repairs are done by. It gives the spread, which M_max needs.">Most done by ({unitWord})</th>
                <th><span className="sr-only">Remove</span></th>
              </tr>
            </thead>
            <tbody>
              {form.lines.map((l, i) => {
                const t = lineMttr(l);
                const split = hasElements(l);
                return (
                  <tr key={i}>
                    <td className="mp-cell"><input type="text" aria-label={`Line ${i + 1} ref`} value={l.ref} onChange={(e) => setLine(i, { ref: e.target.value })} placeholder="Part no." /></td>
                    <td className="mp-text"><input type="text" aria-label={`Line ${i + 1} name`} value={l.name} onChange={(e) => setLine(i, { name: e.target.value })} placeholder="What can fail" /></td>
                    <td className="mp-text"><input type="text" aria-label={`Line ${i + 1} assembly`} value={l.assembly} onChange={(e) => setLine(i, { assembly: e.target.value })} placeholder="Propulsion › Arm 1" /></td>
                    <td className="mp-cell mp-qty"><input type="text" inputMode="decimal" aria-label={`Line ${i + 1} quantity`} value={l.quantity} onChange={(e) => setLine(i, { quantity: e.target.value })} /></td>
                    <td className="mp-cell"><input type="text" inputMode="decimal" aria-label={`Line ${i + 1} failure rate`} value={l.failure_rate} onChange={(e) => setLine(i, { failure_rate: e.target.value })} placeholder="optional" /></td>
                    {(split || anyElements) && ELEMENTS.map((e) => (
                      <td key={e.key} className="mp-cell">
                        <input type="text" inputMode="decimal" aria-label={`Line ${i + 1} ${e.label.toLowerCase()}`} value={l.elements[e.key]}
                          onChange={(ev) => setElement(i, e.key, ev.target.value)} />
                      </td>
                    ))}
                    <td className="mp-cell">
                      {split
                        ? <span className="mp-sum" title="The sum of the elements">{t != null && !Number.isNaN(t) ? formatNumber(t, { sig: 4 }) : "—"}</span>
                        : <input type="text" inputMode="decimal" aria-label={`Line ${i + 1} MTTR`} value={l.mttr} onChange={(e) => setLine(i, { mttr: e.target.value })} />}
                    </td>
                    <td className="mp-cell"><input type="text" inputMode="decimal" aria-label={`Line ${i + 1} most done by`} value={l.maximum} onChange={(e) => setLine(i, { maximum: e.target.value })} placeholder="optional" /></td>
                    <td>
                      {!isBlank(l) && (
                        <button type="button" className="act del mp-remove" aria-label={`Remove line ${i + 1}`} title="Remove" onClick={() => removeLine(i)}><TrashIcon /></button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="mp-add">
          <button type="button" className="secondary sm" onClick={() => setForm((f) => ({ ...f, lines: [...f.lines, emptyLine()] }))}><PlusIcon /> Add line</button>
          <span className="muted-line">
            {split || anyElements
              ? "Enter each step of a repair; its MTTR is their sum. "
              : "Give each line its mean time to repair (MTTR). "}
            “Most done by” is optional: the time 95% of that line's repairs are done by, which is what gives M_max.
          </span>
        </div>

        <div className="mp-compute">
          <button onClick={run} disabled={!!problem || busy} aria-describedby={problem ? "mp-why" : undefined}>
            {busy && !saving ? "Computing…" : "Compute"}
          </button>
          {problem && <span id="mp-why" className="compute-why">{problem}</span>}
        </div>

        {error && <div className="error" role="alert">{error}</div>}
        <CapRefusal error={capError} />

        {result && (
          <MaintainabilityResult
            result={result}
            actions={savedId ? (
              <span className="saved-note" role="status">
                <span className="saved-note-tick" aria-hidden="true">✓</span> Saved ·{" "}
                <Link to={`${MAINTAINABILITY_PATH}/${savedId}`}>Open prediction</Link>
              </span>
            ) : (
              <button className="secondary" onClick={() => setSaving({ name: defaultName })}>Save prediction</button>
            )}
          />
        )}
      </Card>

      {paste !== null && (
        <Modal
          title="Paste a parts list"
          onClose={() => setPaste(null)}
          footer={
            <div className="row" style={{ margin: 0, marginLeft: "auto" }}>
              <button className="secondary" onClick={() => setPaste(null)}>Cancel</button>
              <button onClick={() => { replaceLines(parsePartsList(paste)); setPaste(null); }} disabled={!parsePartsList(paste).length}>
                Use these lines
              </button>
            </div>
          }
        >
          <div className="mp-paste">
            <p className="muted-line">
              One line per row, from a spreadsheet or typed: <code>part number, name, quantity</code> (or just the
              name). A header row names the columns, so a sheet with <code>failure rate</code>, <code>mttr</code> or
              the elements fills those too.
            </p>
            <textarea value={paste} onChange={(e) => setPaste(e.target.value)} aria-label="Parts list"
              placeholder={"SQ-M2210, Brushless motor, 4\nSQ-ESC30, Speed controller, 4\nFlight controller, 1"} autoFocus />
            <p className="muted-line">{parsePartsList(paste).length} lines found. These replace the lines in the table.</p>
          </div>
        </Modal>
      )}

      {saving && (
        <Modal
          title="Save this prediction"
          className="modal-sm"
          onClose={() => setSaving(null)}
          locked={busy}
          footer={
            <div className="row" style={{ margin: 0, marginLeft: "auto" }}>
              <button className="secondary" onClick={() => setSaving(null)} disabled={busy}>Cancel</button>
              <button onClick={onSave} disabled={busy || !saving.name.trim()}>{busy ? "Saving…" : "Save"}</button>
            </div>
          }
        >
          <label className="login-field">
            <span>Name</span>
            <input type="text" value={saving.name} autoFocus onChange={(e) => setSaving({ name: e.target.value })} />
          </label>
          <p className="muted-line">The lines are kept with the result, computed again on the server when saved.</p>
        </Modal>
      )}
    </div>
  );
}

import { useEffect, useState } from "react";
import Select from "./Select.jsx";
import { getRecurrentProjection, runRecurrentProjection } from "../api.js";
import { unitInText } from "./unitText.js";
import ResultSummary, { ResultDetails } from "./ui/ResultSummary.jsx";
import { ScrollCard, TablePanel } from "./model/ModelLayouts.jsx";

const fmt = (v, d = 4) =>
  v == null || !Number.isFinite(v)
    ? "—"
    : Math.abs(v) >= 1e-6 || v === 0
    ? Number(v).toLocaleString(undefined, { maximumSignificantDigits: d })
    : Number(v).toExponential(2);

const KIND_OPTIONS = [
  { value: "A", label: "A — not fixed" },
  { value: "BD", label: "BD — fixed after the test" },
  { value: "BC", label: "BC — fixed during the test" },
];

// Rows of the mode table from the data's modes and any saved settings.
function initialRows(modes, settings, defaultFef) {
  const fef = settings?.fef || {};
  const bc = new Set(settings?.bc || []);
  return (modes || [])
    .filter((m) => m.label != null)
    .map((m) => ({
      label: m.label,
      failures: m.failures,
      first: m.first,
      kind: m.label in fef ? "BD" : bc.has(m.label) ? "BC" : "A",
      fef: m.label in fef ? String(fef[m.label]) : String(defaultFef),
    }));
}

// Reliability growth projection (AMSAA-Crow, MIL-HDBK-189C §6.2; #232): the
// MTBF a test-analyse-and-fix programme reaches once the fixes found in the
// test are put in. Each failure mode is A (not fixed), BD (fixed after the
// test, with a fix-effectiveness factor) or BC (fixed during it). Exact and
// quick; saved with the model when the viewer can edit it. Laid out for the
// model frame's Plan ahead tab: the inputs and the modes on the left (the
// table scrolls inside its card), the answer on the right.
export default function RecurrentProjection({ modelId, unit: rawUnit }) {
  const unit = rawUnit ? String(rawUnit).toLowerCase() : rawUnit;
  const [view, setView] = useState(null);
  const [modeColumn, setModeColumn] = useState("");
  const [rows, setRows] = useState([]);
  const [testEnd, setTestEnd] = useState("");
  const [result, setResult] = useState(null);
  const [saved, setSaved] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const u = unit ? ` ${unit}` : "";
  const ut = unit ? unitInText(unit) : "";
  const perUnit = unit ? ` per ${String(unit).replace(/s$/i, "").toLowerCase()}` : " per unit time";

  const load = (column) => {
    setError(null);
    getRecurrentProjection(modelId, column)
      .then((v) => {
        setView(v);
        setModeColumn(v.mode_column || "");
        const sameColumn = !column || column === v.settings?.mode_column;
        setRows(initialRows(v.modes, sameColumn ? v.settings : null, v.default_fef ?? 0.7));
        if (!column) {
          setResult(v.result || null);
          setTestEnd(v.settings?.test_end != null ? String(v.settings.test_end) : "");
        }
      })
      .catch((e) => setError(e.message));
  };
  useEffect(() => { load(null); }, [modelId]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!view) {
    return error ? <div className="error" role="alert">{error}</div> : <p className="muted-line">Loading…</p>;
  }

  const setRow = (idx, key, value) => setRows((rs) => rs.map((r, i) => (i === idx ? { ...r, [key]: value } : r)));
  const bdRows = rows.filter((r) => r.kind === "BD");
  const badFef = bdRows.some((r) => !(Number(r.fef) >= 0 && Number(r.fef) <= 1) || r.fef === "");
  const unlabelled = (view.modes || []).find((m) => m.label == null);

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      const fef = Object.fromEntries(bdRows.map((r) => [r.label, Number(r.fef)]));
      const bc = rows.filter((r) => r.kind === "BC").map((r) => r.label);
      const out = await runRecurrentProjection(modelId, {
        fef, bc, testEnd: testEnd === "" ? null : Number(testEnd), modeColumn,
      });
      setResult(out.result);
      setSaved(out.saved);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const modeRows = Object.fromEntries((result?.modes || []).map((m) => [m.label, m]));

  const table = rows.length > 0 && (
    <ScrollCard title="Failure modes" sub="mark how each is fixed" className="gp-card">
      <table className="lib-table gp-table">
        <thead>
          <tr>
            <th>Mode</th>
            <th className="num">Failures</th>
            <th className="num">First{unit ? ` (${String(unit).toLowerCase()})` : ""}</th>
            <th>Fix</th>
            <th className="num" title="Fix-effectiveness factor: the share of a BD mode's failures the fix removes">FEF</th>
            {result && <th className="num">Intensity</th>}
            {result && <th className="num">After fix</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, idx) => {
            const m = modeRows[r.label];
            return (
              <tr key={r.label}>
                <td className="gp-mode">{r.label}</td>
                <td className="num">{r.failures}</td>
                <td className="num">{fmt(r.first)}</td>
                <td className="gp-kind">
                  <Select className="sel-embedded" value={r.kind} options={KIND_OPTIONS} ariaLabel={`How ${r.label} is fixed`}
                          onChange={(v) => setRow(idx, "kind", v)} />
                </td>
                <td className="num">
                  <input className="cell-input gp-fef" type="number" inputMode="decimal" min="0" max="1" step="0.05"
                         aria-label={`Fix effectiveness for ${r.label}`}
                         value={r.kind === "BD" ? r.fef : ""} disabled={r.kind !== "BD"}
                         placeholder={r.kind === "BD" ? "0.7" : "—"}
                         onChange={(e) => setRow(idx, "fef", e.target.value)} />
                </td>
                {result && <td className="num">{m ? fmt(m.intensity, 3) : "—"}</td>}
                {result && (
                  <td className="num" title={m?.kind === "BC" ? "Fixed during the test: already in the demonstrated intensity" : undefined}>
                    {m?.kind === "BD" ? fmt(m.projected, 3) : m?.kind === "A" ? fmt(m.intensity, 3) : "—"}
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </ScrollCard>
  );

  return (
    <TablePanel
      className="rec-plan-panel growth-projection"
      main={
        <>
          <section className="gof-card mf-flex-none rec-plan-form" aria-labelledby="gp-title">
            <div className="gofh mf-card-head">
              <h3 className="mf-card-title" id="gp-title">Reliability growth projection</h3>
              <span className="gof-sub">AMSAA-Crow, MIL-HDBK-189C</span>
            </div>
            <p className="mf-note">
              The MTBF once the fixes found in the test are in. Mark each failure mode A (not fixed), BD (fixed after
              the test) or BC (fixed during it).
            </p>
            {view.available && (
              <div className="strategy-costs rec-plan-inputs">
                <label className="calc-t">
                  <span>Failure-mode column</span>
                  <Select
                    value={modeColumn}
                    onChange={(v) => { setModeColumn(v); setResult(null); load(v); }}
                    placeholder="Choose a column…"
                    options={(view.columns || []).map((c) => ({ value: c, label: c }))}
                  />
                </label>
                <label className="calc-t" title="Every system is tested from 0 to the same time T. Leave it blank when the data has each system's end of test (its observation window, or a c = 1 row).">
                  <span>End of test, T{u ? ` (${unit})` : ""}</span>
                  <input type="number" inputMode="decimal" min="0" step="any" value={testEnd} placeholder="from the data"
                         onChange={(e) => setTestEnd(e.target.value)} />
                </label>
                <button onClick={run} disabled={loading || !rows.length || badFef || !!unlabelled}>
                  {loading ? "Projecting…" : "Project MTBF"}
                </button>
              </div>
            )}
            {!view.available && <p className="mf-note">{view.reason}</p>}
            {view.available && view.reason && <p className="mf-note">{view.reason}</p>}
            {unlabelled && (
              <p className="mf-note fleet-alert-warn">
                {unlabelled.failures} failure{unlabelled.failures === 1 ? " has" : "s have"} no mode: every failure
                needs one to project growth.
              </p>
            )}
            {(badFef || saved != null) && (
              <p className="mf-note" role="status">
                {badFef ? "Each fix-effectiveness factor is from 0 to 1. " : ""}
                {saved === true ? "Saved with the model." : saved === false ? "Not saved: you can view this model but not edit it." : ""}
              </p>
            )}
          </section>
          {table}
        </>
      }
      side={
        <>
          {error && <div className="error" role="alert">{error}</div>}
          {result ? (
            <>
              <ResultSummary
                tone={result.basis_note || view.basis_note ? "caveat" : "neutral"}
                sentence={
                  <>
                    With these fixes in, MTBF reaches about <b>{fmt(result.projected?.mtbf)}{ut && ` ${ut}`}</b>.
                  </>
                }
                stats={[
                  {
                    label: `Average over the test${u && ` (${unit})`}`,
                    value: fmt(result.demonstrated?.mtbf),
                    hint: "Test time ÷ failures",
                  },
                  { label: `Projected MTBF${u && ` (${unit})`}`, value: fmt(result.projected?.mtbf) },
                  { label: `Growth potential${u && ` (${unit})`}`, value: fmt(result.growth_potential?.mtbf) },
                ]}
              >
                {result.basis_note || view.basis_note}
              </ResultSummary>
              <ResultDetails>
                <p className="rs-note">
                  {result.systems} system{result.systems === 1 ? "" : "s"} to T = {fmt(result.T)}{u && ` ${ut}`}:{" "}
                  {result.failures?.A ?? 0} A, {result.failures?.BC ?? 0} BC and {result.failures?.BD ?? 0} BD
                  failures ({result.n_bd_modes} BD mode{result.n_bd_modes === 1 ? "" : "s"}, mean FEF{" "}
                  {fmt(result.mean_fef, 3)}). New BD modes were still appearing at h(T) ={" "}
                  {fmt(result.new_mode_intensity, 3)}{perUnit}; the projection allows for the ones not seen yet,
                  which these fixes don’t reach.
                </p>
                <p className="rs-note">
                  Projected intensity {fmt(result.projected?.intensity, 3)} = {fmt(result.components?.unfixed, 3)} not
                  fixed (A{result.failures?.BC ? " and BC" : ""}) + {fmt(result.components?.bd_residual, 3)} left by the
                  BD fixes + {fmt(result.components?.unseen_bd, 3)} from BD modes not yet seen.
                  {result.demonstrated_basis === "crow_amsaa"
                    ? " With BC modes the demonstrated intensity is the Crow-AMSAA fit’s at T (Crow’s extended model)."
                    : ""}
                </p>
              </ResultDetails>
            </>
          ) : view.available ? (
            <div className="rec-plan-empty">
              <p className="muted-line">Mark how each failure mode is fixed, then press <b>Project MTBF</b> to see the MTBF the fixes reach.</p>
            </div>
          ) : null}
        </>
      }
    />
  );
}

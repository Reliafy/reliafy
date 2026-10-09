import { useEffect, useState } from "react";
import Select from "./Select.jsx";
import { getRecurrentProjection, runRecurrentProjection } from "../api.js";
import { unitInText } from "./unitText.js";
import { CardHeader } from "./ui/Card.jsx";

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
// quick; saved with the model when the viewer can edit it.
export default function RecurrentProjection({ modelId, unit }) {
  const [view, setView] = useState(null);
  const [modeColumn, setModeColumn] = useState("");
  const [rows, setRows] = useState([]);
  const [testEnd, setTestEnd] = useState("");
  const [result, setResult] = useState(null);
  const [saved, setSaved] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const u = unit ? ` ${unit}` : "";
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

  if (!view) return error ? <div className="error">{error}</div> : null;

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

  return (
    <div className="strategy-tool growth-projection">
      <CardHeader
        title="Reliability growth projection"
        subtitle={
          <>
            The MTBF once the fixes found in the test are in (AMSAA-Crow, MIL-HDBK-189C). Mark each failure mode
            A (not fixed), BD (fixed after the test, with a fix-effectiveness factor) or BC (fixed during it).
          </>
        }
      />

      {!view.available ? (
        <p className="hint">{view.reason}</p>
      ) : (
        <>
          <div className="strategy-form">
            <div className="strategy-costs">
              <label className="calc-t">
                <span>Failure-mode column</span>
                <Select
                  value={modeColumn}
                  onChange={(v) => { setModeColumn(v); setResult(null); load(v); }}
                  placeholder="Choose a column…"
                  options={(view.columns || []).map((c) => ({ value: c, label: c }))}
                />
              </label>
              <label className="calc-t">
                <span>End of test, T{u ? ` (${unit})` : ""}</span>
                <input type="number" min="0" step="any" value={testEnd} placeholder="from the data"
                       onChange={(e) => setTestEnd(e.target.value)} />
              </label>
            </div>
            <p className="hint">
              Every system is tested from 0 to the same time T. Leave T blank when the data has each
              system’s end of test (its observation window, or a c = 1 row).
            </p>
          </div>

          {view.reason && <p className="hint">{view.reason}</p>}
          {unlabelled && (
            <p className="hint fleet-alert-warn">
              {unlabelled.failures} failure{unlabelled.failures === 1 ? " has" : "s have"} no mode — every failure
              needs one to project growth.
            </p>
          )}

          {rows.length > 0 && (
            <div className="gp-table-wrap">
              <table className="lib-table gp-table">
                <thead>
                  <tr>
                    <th>Mode</th>
                    <th className="num">Failures</th>
                    <th className="num">First{u}</th>
                    <th>Fix</th>
                    <th className="num">FEF</th>
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
                          <Select className="sel-embedded" value={r.kind} options={KIND_OPTIONS}
                                  onChange={(v) => setRow(idx, "kind", v)} />
                        </td>
                        <td className="num">
                          <input className="cell-input gp-fef" type="number" min="0" max="1" step="0.05"
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
            </div>
          )}

          <div className="gp-actions">
            <button onClick={run} disabled={loading || !rows.length || badFef || !!unlabelled}>
              {loading ? "Projecting…" : "Project MTBF"}
            </button>
            {badFef && <span className="hint">Each fix-effectiveness factor is from 0 to 1.</span>}
            {saved === true && <span className="hint">Saved with the model.</span>}
            {saved === false && <span className="hint">Not saved — you can view this model but not edit it.</span>}
          </div>
        </>
      )}

      {error && <div className="error">{error}</div>}

      {result && (
        <>
          {(result.basis_note || view.basis_note) && (
            <p className="hint fleet-alert-warn gp-basis">{result.basis_note || view.basis_note}</p>
          )}
          <div className="params gp-mtbfs">
            <div className="stat">
              <div className="value">{fmt(result.demonstrated?.mtbf)}</div>
              <div className="name" title="Total test time ÷ failures: the average over the whole test (MIL-HDBK-189C demonstrated MTBF). The MTBF now, at the end of the test, is on the Rates card.">average MTBF over the test{u}</div>
            </div>
            <div className="stat gp-projected">
              <div className="value">{fmt(result.projected?.mtbf)}</div>
              <div className="name">projected MTBF{u}</div>
            </div>
            <div className="stat">
              <div className="value">{fmt(result.growth_potential?.mtbf)}</div>
              <div className="name">growth potential{u}</div>
            </div>
          </div>
          <div className="strategy-reco">
            <span className="strategy-reco-icon">✓</span>
            <span>
              {result.systems} system{result.systems === 1 ? "" : "s"} to T = {fmt(result.T)}{u && ` ${unitInText(unit)}`}:{" "}
              {result.failures?.A ?? 0} A, {result.failures?.BC ?? 0} BC and {result.failures?.BD ?? 0} BD
              failures ({result.n_bd_modes} BD mode{result.n_bd_modes === 1 ? "" : "s"}, mean FEF{" "}
              {fmt(result.mean_fef, 3)}). New BD modes were still appearing at h(T) ={" "}
              {fmt(result.new_mode_intensity, 3)}{perUnit}; the projection allows for the ones not seen yet,
              which these fixes don’t reach.
            </span>
          </div>
          <p className="hint">
            Projected intensity {fmt(result.projected?.intensity, 3)} = {fmt(result.components?.unfixed, 3)} not
            fixed (A{result.failures?.BC ? " and BC" : ""}) + {fmt(result.components?.bd_residual, 3)} left by the
            BD fixes + {fmt(result.components?.unseen_bd, 3)} from BD modes not yet seen.
            {result.demonstrated_basis === "crow_amsaa"
              ? " With BC modes the demonstrated intensity is the Crow-AMSAA fit’s at T (Crow’s extended model)."
              : ""}
          </p>
        </>
      )}
    </div>
  );
}

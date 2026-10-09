import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import Plot from "./Plot.jsx";
import { bandPair, fitLine } from "../plotTheme.js";
import { altBounds, evaluateAlt, getRbdJob } from "../api.js";
import { stressName } from "./stressName.js";
import { unitInText } from "./unitText.js";

const fmt = (v) =>
  v == null || !Number.isFinite(v)
    ? "—"
    : Math.abs(v) >= 1e-4 || v === 0
      ? Number(v).toLocaleString(undefined, { maximumSignificantDigits: 5 })
      : Number(v).toExponential(3);
const pct = (v) => (v == null || !Number.isFinite(v) ? "—" : `${(v * 100).toPrecision(4).replace(/\.?0+$/, "")}%`);

const FUNCS = [
  { id: "sf", label: "Reliability R(t)", y: "Reliability" },
  { id: "ff", label: "Unreliability F(t)", y: "Unreliability" },
  { id: "hf", label: "Hazard rate h(t)", y: "Hazard" },
];

// SurPyval 0.23's bound methods (#231). The bootstrap refits the model 200
// times (a paid feature, run on the calculation service) and isn't available
// for inspection (interval-censored) data.
const METHODS = [
  { id: "wald", label: "Wald", hint: "Fisher matrix — instant" },
  { id: "lr", label: "Likelihood ratio", hint: "a second or two" },
  { id: "bootstrap", label: "Bootstrap", hint: "200 refits — Pro" },
];
const LEVELS = [0.9, 0.95, 0.99];
const POLL_FIRST_MS = 1500;
const POLL_MAX_MS = 6000;

// Use-level calculator for an ALT model: enter the field/use stress (below the
// tested stresses) and read the extrapolated reliability curve with its
// confidence band, characteristic / mean / BX lives (with lower bounds), the
// reliability over a mission, and the acceleration factor against a reference
// (test) stress. Evaluation happens on the server (the fitted model lives there).
export default function AltCalculator({ modelId, results }) {
  const stresses = results.stresses || [];
  const levels = results.levels || [];
  const unit = results.unit || "";
  const methods = results.bounds_methods || ["wald", "lr", "bootstrap"];
  const interval = !!results.interval_censored;

  // Sensible defaults: use level = the mildest tested stress; reference = the
  // harshest. (For most accelerations "mild" is the lowest value.)
  const perDim = (j) => levels.map((l) => l.stress[j]).filter((v) => v != null);
  const defUse = stresses.map((_, j) => { const a = perDim(j); return a.length ? Math.min(...a) : 0; });
  const defRef = stresses.map((_, j) => { const a = perDim(j); return a.length ? Math.max(...a) : 0; });

  const [use, setUse] = useState(defUse.map(String));
  const [ref, setRef] = useState(defRef.map(String));
  const [useRef_, setUseRef] = useState(true);
  const [mission, setMission] = useState("");
  const [confidence, setConfidence] = useState(0.95);
  const [method, setMethod] = useState("wald");
  const [active, setActive] = useState("sf");
  const [res, setRes] = useState(null);
  const [bounds, setBounds] = useState(null);
  const [boundsBusy, setBoundsBusy] = useState(false);
  const [boundsError, setBoundsError] = useState(null);
  const [needsPro, setNeedsPro] = useState(false);
  const [job, setJob] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const ticket = useRef(0);

  const missionTime = () => {
    if (!String(mission).trim()) return null;
    const t = Number(mission);
    if (!Number.isFinite(t) || t <= 0) throw new Error("The mission time must be a positive number.");
    return t;
  };

  // Bounds by the chosen method for the current result: Wald comes with the
  // evaluation; the others are a second request (a job for the bootstrap).
  const loadBounds = async (m, base, inputs) => {
    const mine = ++ticket.current;
    setJob(null); setBoundsError(null); setNeedsPro(false);
    if (m === "wald") { setBounds(base?.bounds || null); setBoundsBusy(false); return; }
    setBounds(null); setBoundsBusy(true);
    try {
      const out = await altBounds(modelId, { ...inputs, method: m, tMax: base?.t_max });
      if (mine !== ticket.current) return;
      if (out.job) { setJob(out.job); return; }
      setBounds(out); setBoundsBusy(false);
    } catch (e) {
      if (mine !== ticket.current) return;
      setBoundsBusy(false);
      if (e.status === 402 && e.code === "pro_required") setNeedsPro(true);
      else setBoundsError(e.message);
    }
  };

  const inputsRef = useRef(null);
  const run = async () => {
    setBusy(true); setError(null);
    try {
      const u = use.map(Number);
      const rf = useRef_ ? ref.map(Number) : undefined;
      if (u.some((v) => !Number.isFinite(v))) throw new Error("Enter a number for each use-level stress.");
      const mt = missionTime();
      const out = await evaluateAlt(modelId, u, rf, { missionTime: mt, confidence });
      setRes(out);
      inputsRef.current = { useStress: u, confidence, missionTime: mt };
      loadBounds(method, out, inputsRef.current);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };

  // A new method re-runs only the bounds, against the result on screen.
  const pickMethod = (m) => {
    setMethod(m);
    if (res && inputsRef.current) loadBounds(m, res, inputsRef.current);
  };

  // Poll a queued bootstrap job until it's done.
  const jobId = job?.job_id;
  useEffect(() => {
    if (!jobId) return undefined;
    let cancelled = false;
    let timer = null;
    let delay = POLL_FIRST_MS;
    let failures = 0;
    const poll = async () => {
      try {
        const view = await getRbdJob(jobId);
        if (cancelled) return;
        failures = 0;
        if (view.status === "done") {
          setJob(null); setBounds(view.result); setBoundsBusy(false);
          return;
        }
        if (view.status === "failed") {
          setJob(null); setBoundsBusy(false); setBoundsError(view.error || "The calculation failed.");
          return;
        }
        setJob((prev) => (prev && prev.job_id === jobId ? { ...prev, ...view } : prev));
      } catch (err) {
        if (cancelled) return;
        if (err.status === 404 || ++failures >= 6) {
          setJob(null); setBoundsBusy(false);
          setBoundsError(err.status === 404 ? "The calculation was lost — run it again." : err.message);
          return;
        }
      }
      delay = Math.min(delay * 1.3, POLL_MAX_MS);
      timer = setTimeout(poll, delay);
    };
    timer = setTimeout(poll, POLL_FIRST_MS);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [jobId]);

  const curves = res?.curves || {};
  const traceX = curves.x || [];
  const traceY = curves[active] || [];
  const band = bounds?.band;
  const showBand = band && (active === "sf" || active === "ff");
  const conf = bounds?.confidence ?? confidence;
  const levelText = `${Math.round(conf * 100)}%`;

  const traces = useMemo(() => {
    const out = [];
    if (showBand) {
      const flip = (arr) => arr.map((v) => (v == null ? null : 1 - v));
      // R(t) bounds carry over to F(t) = 1 − R(t), the sides swapped.
      const lo = active === "sf" ? band.lower : flip(band.upper);
      const hi = active === "sf" ? band.upper : flip(band.lower);
      out.push(...bandPair(band.x, lo, hi, { name: `${levelText} band` }));
    }
    out.push(fitLine({ x: traceX, y: traceY, name: "Estimate" }));
    return out;
  }, [showBand, band, active, traceX, traceY, levelText]);

  const layout = useMemo(() => ({
    height: 340,
    xaxis: { title: { text: unit ? `Time (${unit})` : "Time" } },
    yaxis: { title: { text: FUNCS.find((f) => f.id === active)?.y || "" } },
    showlegend: !!showBand,
  }), [active, unit, showBand]);

  const m = res?.metrics || {};
  const af = res?.acceleration_factor;
  const bl = bounds?.b_lives || {};
  const mb = bounds?.mission;
  const u = unit ? ` ${unitInText(unit)}` : "";
  const lower = (b) => (b && b.lower != null ? <small className="alt-lower">≥ {fmt(b.lower)}{u} at {levelText}</small> : null);

  return (
    <div className="alt-calc">
      <div className="alt-calc-inputs">
        <div className="alt-stress-grid">
          {stresses.map((s, j) => (
            <label key={s.key} className="login-field">
              <span>Use-level {stressName(s)}</span>
              <input type="number" value={use[j]} inputMode="decimal"
                     onChange={(e) => setUse((cur) => cur.map((v, k) => (k === j ? e.target.value : v)))} />
            </label>
          ))}
        </div>
        <label className="alt-ref-toggle">
          <input type="checkbox" checked={useRef_} onChange={(e) => setUseRef(e.target.checked)} />
          <span>Acceleration factor vs a reference stress</span>
        </label>
        {useRef_ && (
          <div className="alt-stress-grid">
            {stresses.map((s, j) => (
              <label key={s.key} className="login-field">
                <span>Reference {stressName(s)}</span>
                <input type="number" value={ref[j]} inputMode="decimal"
                       onChange={(e) => setRef((cur) => cur.map((v, k) => (k === j ? e.target.value : v)))} />
              </label>
            ))}
          </div>
        )}
        <label className="login-field">
          <span>Mission time{unit ? ` (${unit})` : ""} <span className="muted">optional</span></span>
          <input type="number" value={mission} inputMode="decimal" min="0" placeholder="e.g. 8760"
                 onChange={(e) => setMission(e.target.value)} />
        </label>
        <div className="alt-bounds-pick">
          <span className="alt-bounds-k">Confidence bounds</span>
          <div className="seg" role="radiogroup" aria-label="Confidence level">
            {LEVELS.map((c) => (
              <button key={c} type="button" role="radio" aria-checked={confidence === c}
                      className={"seg-btn" + (confidence === c ? " active" : "")}
                      onClick={() => setConfidence(c)}>{Math.round(c * 100)}%</button>
            ))}
          </div>
          <div className="seg alt-method-seg" role="radiogroup" aria-label="Bounds method">
            {METHODS.filter((x) => methods.includes(x.id)).map((x) => (
              <button key={x.id} type="button" role="radio" aria-checked={method === x.id} title={x.hint}
                      className={"seg-btn" + (method === x.id ? " active" : "")}
                      onClick={() => pickMethod(x.id)}>{x.label}</button>
            ))}
          </div>
          <span className="muted alt-method-hint">
            {METHODS.find((x) => x.id === method)?.hint}
            {!methods.includes("bootstrap") && interval && " · Bootstrap bounds aren't available for inspection (interval) data."}
          </span>
        </div>
        <button onClick={run} disabled={busy}>{busy ? "Computing…" : "Compute at use level"}</button>
        {error && <div className="error">{error}</div>}
      </div>

      {res && (
        <div className="alt-calc-out">
          <div className="alt-metrics">
            <div className="alt-metric"><span className="k">Characteristic life</span><span className="v">{fmt(m.characteristic_life)}{u}</span></div>
            <div className="alt-metric"><span className="k">Mean life</span><span className="v">{fmt(m.mean_life)}{u}</span></div>
            <div className="alt-metric"><span className="k">B10 life</span><span className="v">{fmt(m.b10)}{u}</span>{lower(bl.b10)}</div>
            <div className="alt-metric"><span className="k">B1 life</span><span className="v">{fmt(m.b1)}{u}</span>{lower(bl.b1)}</div>
            <div className="alt-metric"><span className="k">B50 (median)</span><span className="v">{fmt(m.b50)}{u}</span></div>
            {m.mission_time != null && (
              <div className="alt-metric">
                <span className="k">R({fmt(m.mission_time)}{u})</span>
                <span className="v">{pct(m.mission_reliability)}</span>
                {mb && mb.lower != null && <small className="alt-lower">≥ {pct(mb.lower)} at {levelText}</small>}
              </div>
            )}
            {af && (
              <div className="alt-metric accent">
                <span className="k">Acceleration factor</span>
                <span className="v">{fmt(af.value)}×</span>
              </div>
            )}
          </div>
          {res.no_finite_maximum && <div className="calc-warn">{res.no_finite_maximum.message || "This fit has no finite maximum: the extrapolation means nothing."}</div>}
          {boundsBusy && (
            <p className="hint" role="status" aria-live="polite" style={{ margin: 0 }}>
              {job ? jobText(job) : `Computing ${METHODS.find((x) => x.id === method)?.label.toLowerCase()} bounds…`}
            </p>
          )}
          {needsPro && (
            <div className="card note" role="status">
              <p style={{ margin: 0 }}>
                <b>Bootstrap bounds are part of Pro.</b> They refit the model 200 times on Reliafy's calculation
                service — subscribe to Pro or buy AI credits. Wald and likelihood-ratio bounds are free.
              </p>
              <div className="rbd-upgrade-actions"><Link className="cta cta-solid" to="/billing">Upgrade to Pro</Link></div>
            </div>
          )}
          {boundsError && <div className="calc-warn">{boundsError}</div>}
          {res.bounds_note && method === "wald" && !bounds && <div className="calc-warn">{res.bounds_note}</div>}
          <div className="seg" style={{ alignSelf: "flex-start", flexWrap: "wrap", maxWidth: "100%" }}>
            {FUNCS.map((f) => (
              <button key={f.id} className={"seg-btn" + (active === f.id ? " active" : "")}
                      onClick={() => setActive(f.id)}>{f.label}</button>
            ))}
          </div>
          <Plot data={traces} layout={layout} />
          {curves.warning && <div className="calc-warn">{curves.warning}</div>}
          {bounds && (
            <>
              {(bounds.warnings || []).map((w, i) => <div key={i} className="calc-warn">{w}</div>)}
              <p className="muted-line" style={{ margin: 0 }}>
                {bounds.method_name} bounds{bounds.n_boot ? ` (${bounds.n_boot} refits)` : ""}: the shaded band
                is two-sided {levelText} on {active === "ff" ? "F(t)" : "R(t)"}; the B-life and mission figures are
                one-sided {levelText} lower bounds.
              </p>
              {(bounds.coefficients || []).length > 0 && (
                <div className="table-scroll">
                  <table className="mini-table alt-ci-table">
                    <thead><tr><th>Parameter</th><th>Estimate</th><th>{levelText} interval</th></tr></thead>
                    <tbody>
                      {bounds.coefficients.map((c) => (
                        <tr key={c.name}>
                          <td>{c.name} <span className="muted">({c.kind === "shape" ? "shape" : "life-stress"})</span></td>
                          <td>{fmt(c.value)}</td>
                          <td>{c.ci ? `${fmt(c.ci[0])} – ${fmt(c.ci[1])}` : "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

function jobText(job) {
  if (!job) return "";
  if (job.status === "running") return "Bootstrapping: refitting the model…";
  const ahead = job.queue_position;
  return ahead ? `Queued for the calculation service (${ahead} ahead)…` : "Queued for the calculation service…";
}

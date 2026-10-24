import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import Plot from "./Plot.jsx";
import { bandPair, fitLine } from "../plotTheme.js";
import { altBounds, evaluateAlt, getRbdJob } from "../api.js";
import { stressName } from "./stressName.js";
import { unitInText } from "./unitText.js";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import { PlotCard } from "./model/ModelLayouts.jsx";
import { parseUse } from "../altFrame.js";

const fmt = (v) =>
  v == null || !Number.isFinite(v)
    ? "—"
    : Math.abs(v) >= 1e-4 || v === 0
      ? Number(v).toLocaleString(undefined, { maximumSignificantDigits: 4 })
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

// The calculator's inputs and its last answer, kept by the page so they
// survive a switch of tab. The use stress itself is the page's (the
// Life-stress tab shares it).
export function initAltCalc(results) {
  const r = results || {};
  const stresses = r.stresses || [];
  const perDim = (j) => (r.levels || []).map((l) => l.stress?.[j]).filter((v) => v != null);
  // Reference: the harshest tested level of each stress.
  const ref = stresses.map((_, j) => { const a = perDim(j); return a.length ? String(Math.max(...a)) : "0"; });
  return {
    ref, refOn: true, mission: "", confidence: 0.95, method: "wald", active: "sf",
    res: null, bounds: null, job: null, inputs: null,
  };
}

// Use-level calculator for an ALT model: enter the field/use stress (below the
// tested stresses) and read the extrapolated reliability curve with its
// confidence band, characteristic / mean / BX lives (with lower bounds), the
// reliability over a mission, and the acceleration factor against a reference
// (test) stress. Evaluation happens on the server (the fitted model lives there).
// The inputs sit in a rail on the right; the answer and the chart fill the rest.
export default function AltCalculator({ modelId, results, use, onUse, state, setState }) {
  const stresses = results.stresses || [];
  const unit = results.unit || "";
  const methods = results.bounds_methods || ["wald", "lr", "bootstrap"];
  const interval = !!results.interval_censored;
  const st = state;
  const set = (patch) => setState((cur) => ({ ...cur, ...(typeof patch === "function" ? patch(cur) : patch) }));

  const [boundsBusy, setBoundsBusy] = useState(!!st.job);
  const [boundsError, setBoundsError] = useState(null);
  const [needsPro, setNeedsPro] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const ticket = useRef(0);

  const missionTime = () => {
    if (!String(st.mission).trim()) return null;
    const t = Number(st.mission);
    if (!Number.isFinite(t) || t <= 0) throw new Error("The mission time must be a positive number.");
    return t;
  };

  // Bounds by the chosen method for the current result: Wald comes with the
  // evaluation; the others are a second request (a job for the bootstrap).
  const loadBounds = async (m, base, inputs) => {
    const mine = ++ticket.current;
    set({ job: null }); setBoundsError(null); setNeedsPro(false);
    if (m === "wald") { set({ bounds: base?.bounds || null }); setBoundsBusy(false); return; }
    set({ bounds: null }); setBoundsBusy(true);
    try {
      const out = await altBounds(modelId, { ...inputs, method: m, tMax: base?.t_max });
      if (mine !== ticket.current) return;
      if (out.job) { set({ job: out.job }); return; }
      set({ bounds: out }); setBoundsBusy(false);
    } catch (e) {
      if (mine !== ticket.current) return;
      setBoundsBusy(false);
      if (e.status === 402 && e.code === "pro_required") setNeedsPro(true);
      else setBoundsError(e.message);
    }
  };

  const run = async () => {
    setBusy(true); setError(null);
    try {
      const u = parseUse(use);
      if (!u) throw new Error("Enter a number for each use-level stress.");
      const rf = st.refOn ? st.ref.map(Number) : undefined;
      if (rf && rf.some((v) => !Number.isFinite(v))) throw new Error("Enter a number for each reference stress.");
      const mt = missionTime();
      const out = await evaluateAlt(modelId, u, rf, { missionTime: mt, confidence: st.confidence });
      const inputs = { useStress: u, confidence: st.confidence, missionTime: mt };
      set({ res: out, inputs });
      loadBounds(st.method, out, inputs);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };

  // A new method re-runs only the bounds, against the result on screen.
  const pickMethod = (m) => {
    set({ method: m });
    if (st.res && st.inputs) loadBounds(m, st.res, st.inputs);
  };

  // Poll a queued bootstrap job until it's done.
  const jobId = st.job?.job_id;
  useEffect(() => {
    if (!jobId) return undefined;
    let cancelled = false;
    let timer = null;
    let delay = POLL_FIRST_MS;
    let failures = 0;
    setBoundsBusy(true);
    const poll = async () => {
      try {
        const view = await getRbdJob(jobId);
        if (cancelled) return;
        failures = 0;
        if (view.status === "done") {
          set({ job: null, bounds: view.result }); setBoundsBusy(false);
          return;
        }
        if (view.status === "failed") {
          set({ job: null }); setBoundsBusy(false); setBoundsError(view.error || "The calculation failed.");
          return;
        }
        set((cur) => ({ job: cur.job && cur.job.job_id === jobId ? { ...cur.job, ...view } : cur.job }));
      } catch (err) {
        if (cancelled) return;
        if (err.status === 404 || ++failures >= 6) {
          set({ job: null }); setBoundsBusy(false);
          setBoundsError(err.status === 404 ? "The calculation was lost — run it again." : err.message);
          return;
        }
      }
      delay = Math.min(delay * 1.3, POLL_MAX_MS);
      timer = setTimeout(poll, delay);
    };
    timer = setTimeout(poll, POLL_FIRST_MS);
    return () => { cancelled = true; clearTimeout(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  const res = st.res;
  const bounds = st.bounds;
  const active = st.active;
  const curves = res?.curves || {};
  const traceX = curves.x || [];
  const traceY = curves[active] || [];
  const band = bounds?.band;
  const showBand = band && (active === "sf" || active === "ff");
  const conf = bounds?.confidence ?? st.confidence;
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
    margin: { t: 8, r: 12, b: 44, l: 58 },
    xaxis: { title: { text: unit ? `Time (${unit})` : "Time" } },
    yaxis: { title: { text: FUNCS.find((f) => f.id === active)?.y || "" } },
    showlegend: !!showBand,
    legend: { x: 1, xanchor: "right", y: 1, yanchor: "top", bgcolor: "rgba(255,255,255,0.85)" },
  }), [active, unit, showBand]);

  const m = res?.metrics || {};
  const af = res?.acceleration_factor;
  const bl = bounds?.b_lives || {};
  const mb = bounds?.mission;
  const u = unit ? ` ${unitInText(unit)}` : "";
  const lower = (b) => (b && b.lower != null ? <small className="alt-lower">≥ {fmt(b.lower)} at {levelText}</small> : null);
  // The answer on screen is for another use stress than the one entered now.
  const stale = res && JSON.stringify(parseUse(use)) !== JSON.stringify(res.use_stress);

  return (
    <div className="alt-calc mf-alt-calc">
      <div className="alt-calc-out">
        {res ? (
          <>
            <div className="alt-metrics" role="status" aria-live="polite">
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
            {stale && <p className="hint alt-calc-note">You changed the use stress: press Compute to update.</p>}
            {res.no_finite_maximum && <div className="calc-warn">{res.no_finite_maximum.message || "This fit has no finite maximum: the extrapolation means nothing."}</div>}
            {boundsBusy && (
              <p className="hint alt-calc-note" role="status" aria-live="polite">
                {st.job ? jobText(st.job) : `Computing ${METHODS.find((x) => x.id === st.method)?.label.toLowerCase()} bounds…`}
              </p>
            )}
            {needsPro && (
              <div className="card note alt-calc-note" role="status">
                <p style={{ margin: 0 }}>
                  <b>Bootstrap bounds are part of Pro.</b> They refit the model 200 times on Reliafy's calculation
                  service. Wald and likelihood-ratio bounds are free.
                </p>
                <div className="rbd-upgrade-actions"><Link className="cta cta-solid" to="/billing">Upgrade to Pro</Link></div>
              </div>
            )}
            {boundsError && <div className="calc-warn">{boundsError}</div>}
            {res.bounds_note && st.method === "wald" && !bounds && <div className="calc-warn">{res.bounds_note}</div>}
            {curves.warning && <div className="calc-warn">{curves.warning}</div>}
            {(bounds?.warnings || []).map((w, i) => <div key={i} className="calc-warn">{w}</div>)}
            <PlotCard controls={(
              <>
                <SegmentedControl
                  label="Function"
                  size="sm"
                  value={active}
                  onChange={(v) => set({ active: v })}
                  options={FUNCS.map((f) => ({ value: f.id, label: f.label }))}
                />
                {bounds && (
                  <span className="muted alt-band-note">
                    {bounds.method_name} bounds{bounds.n_boot ? ` (${bounds.n_boot} refits)` : ""}: band two-sided {levelText}
                    {" "}on {active === "ff" ? "F(t)" : "R(t)"}; B-life and mission figures one-sided {levelText} lower bounds.
                  </span>
                )}
              </>
            )}>
              <Plot fill data={traces} layout={layout} download={`Use-level ${FUNCS.find((f) => f.id === active)?.label}`} />
            </PlotCard>
          </>
        ) : (
          <div className="alt-calc-empty">
            <p>Enter your use stress on the right and press <b>Compute at use level</b>: the life, the B-lives and
              the reliability there, with their bounds.</p>
          </div>
        )}
      </div>

      <div className="calc-rail-card calc-eval-card alt-calc-rail">
        <div className="gofh">Inputs</div>
        <div className="alt-calc-inputs">
          {stresses.map((s, j) => (
            <label key={s.key} className="alt-use-field">
              <span>Use {stressName(s)}</span>
              <input type="number" value={use[j] ?? ""} inputMode="decimal" step="any"
                     onChange={(e) => onUse(use.map((v, k) => (k === j ? e.target.value : v)))} />
            </label>
          ))}
          <label className="alt-ref-toggle">
            <input type="checkbox" checked={st.refOn} onChange={(e) => set({ refOn: e.target.checked })} />
            <span>Acceleration factor against a reference</span>
          </label>
          {st.refOn && stresses.map((s, j) => (
            <label key={s.key} className="alt-use-field">
              <span>Reference {stressName(s)}</span>
              <input type="number" value={st.ref[j] ?? ""} inputMode="decimal" step="any"
                     onChange={(e) => set((cur) => ({ ref: cur.ref.map((v, k) => (k === j ? e.target.value : v)) }))} />
            </label>
          ))}
          <label className="alt-use-field">
            <span>Mission time{unit ? ` (${unit})` : ""} <span className="muted">optional</span></span>
            <input type="number" value={st.mission} inputMode="decimal" min="0" step="any" placeholder="e.g. 8760"
                   onChange={(e) => set({ mission: e.target.value })} />
          </label>
          <div className="alt-bounds-pick">
            <span className="alt-bounds-k">Confidence bounds</span>
            <SegmentedControl
              label="Confidence level"
              size="sm"
              value={st.confidence}
              onChange={(v) => set({ confidence: v })}
              options={LEVELS.map((c) => ({ value: c, label: `${Math.round(c * 100)}%` }))}
            />
            <SegmentedControl
              label="Bounds method"
              size="sm"
              className="alt-method-seg"
              value={st.method}
              onChange={pickMethod}
              options={METHODS.filter((x) => methods.includes(x.id)).map((x) => ({ value: x.id, label: x.label, title: x.hint }))}
            />
            <span className="muted alt-method-hint">
              {METHODS.find((x) => x.id === st.method)?.hint}
              {!methods.includes("bootstrap") && interval && " · Bootstrap bounds aren't available for inspection (interval) data."}
            </span>
          </div>
          <button onClick={run} disabled={busy}>{busy ? "Computing…" : "Compute at use level"}</button>
          {error && <div className="error" role="alert">{error}</div>}
          {(bounds?.coefficients || []).length > 0 && (
            <div className="alt-calc-cis">
              <div className="alt-bounds-k">Parameter intervals ({levelText}, {bounds.method_name})</div>
              <table className="mini-table alt-ci-table">
                <thead><tr><th>Parameter</th><th>Estimate</th><th>Interval</th></tr></thead>
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
        </div>
      </div>
    </div>
  );
}

function jobText(job) {
  if (!job) return "";
  if (job.status === "running") return "Bootstrapping: refitting the model…";
  const ahead = job.queue_position;
  return ahead ? `Queued for the calculation service (${ahead} ahead)…` : "Queued for the calculation service…";
}

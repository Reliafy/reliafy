import { useEffect, useState } from "react";
import Plot from "./Plot.jsx";
import { fitLine, pointMarker, referenceShape } from "../plotTheme.js";
import Select from "./Select.jsx";
import { formatNumber } from "../format.js";
import { unitInText } from "./unitText.js";
import { calculateRecurrent, recurrentFromNow } from "../api.js";
import { LEVEL_TEXT } from "../levels.js";

// Recurrent-event calculator: read off the repairable-system functions at a
// chosen time — expected cumulative failures N(t), the rate of occurrence of
// failures ROCOF(t), and the instantaneous MTBF(t) — and, over a window, the
// failures to expect with the average rate and MTBF. The power law
// (Crow-AMSAA) is evaluated in closed form from α, β; otherwise the fitted MCF
// curve is interpolated. Mirrors the life-data Calculator: one answer line —
// function, time, value — then the chart filling the tab, the window in the rail.
const FUNCS = [
  { id: "N", label: "Expected failures N(t)", y: "Expected failures per system" },
  { id: "rocof", label: "Failure rate (ROCOF)", y: "Failure rate" },
  { id: "mtbf", label: "Mean time between failures", y: "MTBF" },
];

const fmt = (v) => (v == null || !Number.isFinite(v) ? "—" : formatNumber(v, { sig: 4 }));
const rangeText = (ci) => (ci && Number.isFinite(ci[0]) && Number.isFinite(ci[1])
  ? `${formatNumber(ci[0], { sig: 3 })}–${formatNumber(ci[1], { sig: 3 })}` : null);

// The server's figure for a function: { value, ci, lower }.
const serverPart = (res, id) => (!res ? null : id === "N" ? res.expected : id === "rocof" ? res.rocof : res.mtbf);

function interp(x, y, xq) {
  if (!x || !y || xq < x[0] || xq > x[x.length - 1]) return null;
  for (let i = 1; i < x.length; i++) {
    if (xq <= x[i]) {
      const y0 = y[i - 1], y1 = y[i];
      if (y0 == null || y1 == null) return null;
      const x0 = x[i - 1], x1 = x[i];
      return y0 + (x1 === x0 ? 0 : (xq - x0) / (x1 - x0)) * (y1 - y0);
    }
  }
  return null;
}

export default function RecurrentCalculator({ r, name = null, modelId = null }) {
  const unit = String(r.unit || "").toLowerCase();
  const tLabel = unit ? `t (${unit})` : "t";
  const fitted = r.mcf?.fitted || {};
  const byName = Object.fromEntries((r.params || []).map((p) => [p.name, p.value]));
  const alpha = byName.alpha;
  const beta = byName.beta ?? r.beta;
  // Crow-AMSAA's power law, N(t) = (t/α)^β, in closed form; every other
  // model (Duane's own parameters, covariates, imperfect repair) off its
  // fitted MCF curve.
  const analytic = (r.model?.id || "crow_amsaa") === "crow_amsaa" && (r.family || "nhpp") === "nhpp" &&
    alpha > 0 && beta != null;

  const gridMax = (fitted.x?.length ? fitted.x[fitted.x.length - 1] : 0) || 1;
  const [t, setT] = useState(Number((gridMax / 2).toPrecision(4)) || 0);
  const [from, setFrom] = useState("");
  const [active, setActive] = useState("N");
  const renewal = r.family === "renewal";
  const regression = r.family === "regression";
  const funcs = renewal ? FUNCS.filter((f) => f.id === "N") : FUNCS;
  // A covariate model is read at chosen covariate values (each category's
  // level, each number), the rest at the fleet's average.
  const covs = regression ? (r.covariates || []) : [];
  const [profile, setProfile] = useState(() => Object.fromEntries(covs.map((c) => [c.column,
    c.kind === "category" ? (c.reference ?? c.levels?.[0] ?? "") : (r.average_profile?.[c.column] ?? "")])));
  // The server's values with their 90% bounds (a saved model), beyond the
  // data too: { expected, rocof, mtbf, window } or an error.
  const [server, setServer] = useState(null);
  const [serverError, setServerError] = useState(null);
  const fitted_ = !r.from_params;

  const nt = Number(t);
  const tMax = Math.max(gridMax, (Number.isFinite(nt) ? nt : 0) * 1.05) || 1;

  // Point evaluators.
  const mcfAt = (tv) => (analytic ? Math.pow(tv / alpha, beta) : interp(fitted.x, fitted.mcf, tv));
  const rocofAt = (tv) => {
    if (analytic) return tv > 0 ? (beta / alpha) * Math.pow(tv / alpha, beta - 1) : (beta === 1 ? 1 / alpha : null);
    // Numeric slope of the fitted MCF.
    const h = tMax / 400;
    const a = mcfAt(Math.max(0, tv - h)), b = mcfAt(tv + h);
    return a != null && b != null ? (b - a) / (2 * h) : null;
  };
  const mtbfAt = (tv) => { const rr = rocofAt(tv); return rr && Number.isFinite(rr) && rr > 0 ? 1 / rr : null; };
  // A covariate model's curve at the chosen values is the average-covariate
  // curve times a constant (proportional intensity): the server's N(t) over
  // the curve's gives it.
  const avgAtT = regression ? mcfAt(nt) : null;
  const scale = regression && server?.expected?.value > 0 && avgAtT > 0 ? server.expected.value / avgAtT : 1;
  const valAt = (id, tv) => {
    const v = id === "N" ? mcfAt(tv) : id === "rocof" ? rocofAt(tv) : mtbfAt(tv);
    if (v == null || scale === 1) return v;
    return id === "mtbf" ? v / scale : v * scale;
  };

  // Curves over [0, tMax] for the active function.
  const M = 200;
  const gx = Array.from({ length: M }, (_, k) => (tMax * k) / (M - 1));
  const gy = gx.map((tv) => { const v = valAt(active, tv); return v != null && Number.isFinite(v) ? v : null; });

  const nFrom = from !== "" && Number.isFinite(Number(from)) ? Number(from) : null;
  const profileKey = JSON.stringify(profile);
  useEffect(() => {
    if (!modelId || !(nt > 0)) { setServer(null); return undefined; }
    let live = true;
    const timer = setTimeout(() => {
      calculateRecurrent(modelId, {
        t: nt, start: nFrom != null && nFrom < nt ? nFrom : null, profile: regression ? profile : null,
      }).then((res) => { if (live) { setServer(res); setServerError(null); } })
        .catch((e) => { if (live) { setServer(null); setServerError(e?.message || String(e)); } });
    }, renewal ? 450 : 250);
    return () => { live = false; clearTimeout(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modelId, nt, nFrom, profileKey]);
  // Over a window [from, t]: the expected failures, and the average rate and
  // MTBF across it.
  const win = (() => {
    if (regression || nFrom == null || !(nt > nFrom)) return null;
    const a = mcfAt(nFrom), b = mcfAt(nt);
    if (a == null || b == null) return null;
    const n = b - a;
    return { n, rate: n / (nt - nFrom), mtbf: n > 0 ? (nt - nFrom) / n : null };
  })();

  // The server's figure wins where it has one: a covariate model at the chosen
  // values, an imperfect-repair model beyond the data.
  const sp = serverPart(server, active);
  const yv = sp?.value != null ? sp.value : regression ? null : valAt(active, nt);
  const yci = sp?.ci || null;
  const ylower = active === "mtbf" ? sp?.lower : null;
  const sWin = server?.window || null;
  const traces = [fitLine({ x: gx, y: gy, name: active, connectgaps: false })];
  if (yv != null && Number.isFinite(yv)) {
    traces.push({ ...pointMarker(), x: [nt], y: [yv] });
  }
  const yTitle = FUNCS.find((f) => f.id === active)?.y || active;
  const shapes = [referenceShape({ x: nt, line: { dash: "dot" } })];
  if (win) {
    // The window, shaded.
    shapes.push({ type: "rect", xref: "x", yref: "paper", x0: nFrom, x1: nt, y0: 0, y1: 1,
                  fillcolor: "rgba(47,109,246,0.08)", line: { width: 0 }, layer: "below" });
  }
  const layout = {
    showlegend: false,
    xaxis: { title: { text: tLabel }, rangemode: "tozero" },
    yaxis: {
      title: {
        text: yTitle + (unit && active === "mtbf" ? ` (${unitInText(unit)})`
          : unit && active === "rocof" ? ` (per ${unitInText(unit).replace(/s$/, "")})` : ""),
      },
      rangemode: "tozero",
    },
    shapes,
  };
  const ut = unit ? unitInText(unit) : "";

  return (
    <div className="calc">
      <div className="calc-body">
        <div className="calc-main">
          <div className="calc-answer">
            <Select
              value={active}
              onChange={setActive}
              title="Function"
              className="calc-fn"
              options={funcs.map((f) => ({ value: f.id, label: f.label }))}
            />
            <span>at</span>
            <input
              type="number" inputMode="decimal"
              className="calc-t-input"
              aria-label={`Evaluate at ${tLabel}`}
              min={0}
              step="any"
              value={t}
              onChange={(e) => setT(e.target.value)}
            />
            <span>{ut}:</span>
            <span className="calc-answer-value">
              <b>{fmt(yv)}{active === "mtbf" && yv != null && ut ? ` ${ut}` : ""}</b>
              {active === "rocof" && yv != null && ut && (
                <span className="calc-answer-ci"> per {ut.replace(/s$/, "")}</span>
              )}
              {yv != null && rangeText(yci) && (
                <span className="calc-answer-ci"> ({LEVEL_TEXT} range {rangeText(yci)})</span>
              )}
              {yv != null && ylower != null && (
                <span className="calc-answer-ci"> · at least {fmt(ylower)}{ut ? ` ${ut}` : ""} ({LEVEL_TEXT} one-sided)</span>
              )}
            </span>
          </div>
          {covs.length > 0 && (
            <div className="row calc-profile" style={{ gap: 12, flexWrap: "wrap", margin: "0 0 8px" }}>
              {covs.map((c) => (
                <label key={c.column} className="calc-t">
                  <span>{c.column}</span>
                  {c.kind === "category" ? (
                    <Select value={String(profile[c.column] ?? "")} title={c.column}
                            onChange={(v) => setProfile((p) => ({ ...p, [c.column]: v }))}
                            options={(c.levels || []).map((l) => ({ value: String(l), label: String(l) }))} />
                  ) : (
                    <input type="number" inputMode="decimal" step="any" value={profile[c.column] ?? ""}
                           onChange={(e) => setProfile((p) => ({ ...p, [c.column]: e.target.value }))} />
                  )}
                </label>
              ))}
            </div>
          )}
          {calcNote({ r, modelId, server, serverError, active, renewal, regression, fitted: fitted_ })}
          <Plot fill data={traces} layout={layout} download={`${name || "Repairable model"} — ${yTitle}`} />
        </div>

        <div className="calc-side-rail">
          <div className="calc-rail-card calc-eval-card">
            <div className="gofh">Over a window</div>
            <div className="calc-eval-body">
              <label className="calc-t">
                <span>From{unit ? ` (${unitInText(unit)})` : ""}, to the time chosen</span>
                <input type="number" inputMode="decimal" min={0} step="any" placeholder="e.g. 0" value={from}
                       onChange={(e) => setFrom(e.target.value)} />
              </label>
              {(sWin || win) ? (
                <dl className="rec-window" aria-live="polite">
                  <div><dt>Expected failures</dt><dd>{fmt(sWin?.expected ?? win?.n)} <span className="gof-sub">per system{rangeText(sWin?.ci) ? `, ${LEVEL_TEXT} range ${rangeText(sWin.ci)}` : ""}</span></dd></div>
                  {win && <div><dt>Average failure rate</dt><dd>{fmt(win.rate)}{ut ? <span className="gof-sub"> per {ut.replace(/s$/, "")}</span> : null}</dd></div>}
                  {win && <div><dt>Average MTBF</dt><dd>{win.mtbf != null ? `${fmt(win.mtbf)}${ut ? ` ${ut}` : ""}` : "—"}</dd></div>}
                </dl>
              ) : (
                <p className="rs-note">
                  {nFrom != null && !(nt > nFrom)
                    ? "The window ends at the time chosen above the chart: make that later than the start."
                    : "Enter a start time to see the failures to expect between then and the time chosen: for a budget or a spares order."}
                </p>
              )}
              {!analytic && !modelId && (
                <p className="rs-note">
                  Read off the fitted MCF{regression ? " at the fleet's average covariates (no real system)"
                    : r.mcf?.fitted?.simulated ? " (simulated)" : ""}: within the fitted range only. Save the model
                  for values beyond the data, with bounds.
                </p>
              )}
            </div>
          </div>
          {modelId && fitted_ && !regression && <FromNow modelId={modelId} unit={unit} renewal={renewal} />}
        </div>
      </div>
    </div>
  );
}

// Where the figures come from, and why one is missing.
function calcNote({ r, modelId, server, serverError, active, renewal, regression, fitted }) {
  let text = null;
  if (serverError) text = serverError;
  else if (server?.bounds_note) {
    text = `${server.bounds_note}${regression && server.profile ? ` At ${server.profile}.` : ""}`;
    if (renewal && server.rate_reason) text += ` ${server.rate_reason}`;
  } else if (!modelId) {
    text = fitted ? "Bounds come once the model is saved." : null;
  } else if (!fitted) {
    text = "No bounds: this model was built from parameters, so it has no fit uncertainty.";
  }
  if (!text || (active !== "N" && renewal && !server?.rate_reason)) return null;
  return <p className="rs-note calc-bounds-note">{text}</p>;
}

// "How many failures next year?": the fleet's failures over the next stretch
// from where each of the model's systems is now (the end of its record), with
// the systems that add most.
function FromNow({ modelId, unit, renewal }) {
  const [h, setH] = useState("");
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const ut = unit ? unitInText(unit) : "";
  const run = async () => {
    if (!(Number(h) > 0)) return;
    setBusy(true);
    setErr(null);
    try {
      setRes(await recurrentFromNow(modelId, Number(h)));
    } catch (e) {
      setErr(e?.message || String(e));
      setRes(null);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="calc-rail-card calc-eval-card">
      <div className="gofh">From now on</div>
      <div className="calc-eval-body">
        <label className="calc-t">
          <span>The next{ut ? ` (${ut})` : ""}, from where each system is now</span>
          <span className="row" style={{ gap: 8, margin: 0 }}>
            <input type="number" inputMode="decimal" min={0} step="any" placeholder="e.g. 8000" value={h}
                   onChange={(e) => setH(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") run(); }} />
            <button type="button" className="btn" onClick={run} disabled={busy || !(Number(h) > 0)}>
              {busy ? (renewal ? "Simulating…" : "Working…") : "Work out"}
            </button>
          </span>
        </label>
        {err && <p className="hint">{err}</p>}
        {res && (
          <>
            <dl className="rec-window" aria-live="polite">
              <div><dt>Fleet failures</dt><dd>≈ {fmt(res.expected)} <span className="gof-sub">{LEVEL_TEXT} range {rangeText(res.interval)}</span></dd></div>
              {(res.systems || []).slice(0, 3).map((s) => (
                <div key={s.system}><dt>{s.system}</dt><dd>{fmt(s.expected)}</dd></div>
              ))}
            </dl>
            <p className="rs-note">{res.note}</p>
          </>
        )}
        {!res && !err && (
          <p className="rs-note">For a budget: every system in the model from the end of its record, counting each repeat failure.</p>
        )}
      </div>
    </div>
  );
}

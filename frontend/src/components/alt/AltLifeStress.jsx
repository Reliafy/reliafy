// The Life-stress tab of an accelerated life model: life against stress, the
// tested levels marked, the fitted line run on to the use stress and the use
// point marked. One stress: the life drawn is the median (default) or the B10
// with its one-sided lower bound, or the characteristic life with its
// two-sided band (SurPyval's qf and quantile_cb along the line). Beside it
// the use stress, the life and mean life (MTTF) there, the shape, the
// activation energy and the acceleration factor against each tested level. A model with two stresses
// has two charts, one along each stress (a line for each tested level of the
// other): side by side where each is wide enough to read, else one at a time
// with a switch above (ChartPair).
import { useEffect, useState } from "react";
import Plot from "../Plot.jsx";
import ChartPair from "../model/ChartPair.jsx";
import { PlotCard, PlotPanel, ScrollCard } from "../model/ModelLayouts.jsx";
import { COLORWAY, DATA_INK, INK, SURFACE, WARNING, bandPair, fitLine, legendBg, token } from "../../plotTheme.js";
import { formatNumber } from "../../format.js";
import { evaluateAlt } from "../../api.js";
import { CHART_LIVES, accelerationRows, activationEnergy, enteredUnit, fromKelvin, inputStressName, lifeLineFor, meanAtUse, plotInEnteredUnits, kelvinWords, levelWords, shapeParam, useForModel, useRangeWarning } from "../../altFrame.js";
import ExtrapolationNote from "../ui/ExtrapolationNote.jsx";
import SegmentedControl from "../ui/SegmentedControl.jsx";
import { unitInText } from "../unitText.js";
import { ciPct } from "../../levels.js";

const SERIES = COLORWAY;
// The use point and line: the warning colour (the token, read as the chart draws).
const useMark = () => token("--warning", WARNING);

// One life-stress chart: ``plot`` is a life_stress_plot from the fit (along
// one stress); ``along`` the line through the use stress from the
// calculator's answer, and ``usePoint`` { x, y } the use point. ``lifeLabel``
// names the life drawn ("Median life"; the characteristic life by default)
// and ``points`` replaces the tested levels' marks (the median or B10 there).
export function LifeStressChart({ plot, unit, along = null, usePoint = null, otherUse = null, name, fill = true,
                                  lifeLabel = "Characteristic life", points = null }) {
  const p = plot || {};
  const two = p.secondary_label != null;
  const traces = [];
  const secLevels = two ? [...new Set((p.lines || []).map((l) => l.secondary))] : [null];
  (p.lines || []).forEach((ln, i) => {
    // One stress: the line through the use stress replaces the fitted line
    // (it is the same line, run on to the use stress).
    if (!two && along) return;
    traces.push(fitLine({
      x: ln.stress, y: ln.life,
      line: { color: SERIES[i % SERIES.length] },
      name: two ? `${p.secondary_label} = ${formatNumber(ln.secondary, { sig: 4 })}` : "Fitted line",
      legendgroup: `g${i}`,
    }));
  });
  // Two stresses: the line through the use stress, unless the other stress's
  // use value is a tested level (its line is already drawn).
  const onTested = two && otherUse != null && secLevels.some((v) => Math.abs(v - otherUse) <= 1e-9 * Math.max(1, Math.abs(v)));
  if (along?.stress?.length && !onTested) {
    // The band on the life along the line: how soft the extrapolated end is.
    const pct = Number.isFinite(along.level) ? `${Math.round(along.level * 100)}%` : null;
    if (along.bound === "lower" && Array.isArray(along.lower)) {
      // A life's bound is one-sided: the band runs from the lower bound up to the line.
      traces.push(...bandPair(along.stress, along.lower, along.life,
        { name: pct ? `${pct} lower bound (one-sided)` : "Lower bound (one-sided)" }));
    } else if (Array.isArray(along.lower) && Array.isArray(along.upper)) {
      traces.push(...bandPair(along.stress, along.lower, along.upper, { name: pct ? `${pct} band (two-sided)` : "Band" }));
    }
    traces.push(fitLine({
      x: along.stress, y: along.life,
      line: two ? { color: useMark(), dash: "dash" } : { color: SERIES[0] },
      name: two ? `${p.secondary_label} = ${formatNumber(otherUse, { sig: 4 })} (use)` : "Fitted line",
      hovertemplate: `${p.x_label}: %{x:.4~g}<br>Life: %{y:.4~g}<extra></extra>`,
    }));
  }
  (points || p.points || []).forEach((pt) => {
    const idx = two ? Math.max(0, secLevels.indexOf(pt.secondary)) : 0;
    traces.push({
      x: [pt.stress], y: [pt.life], mode: "markers", type: "scatter",
      marker: { color: two ? SERIES[idx % SERIES.length] : INK, size: 10, symbol: "diamond",
                line: { color: SURFACE, width: 1.5 } },
      name: "Tested level", legendgroup: `g${idx}`, showlegend: false,
      hovertemplate: `${p.x_label}: %{x}<br>Life: %{y:.4~g}<extra>tested level</extra>`,
    });
  });
  const obs = p.observations;
  if (obs) {
    const times = obs.ranges.time;
    const floor = p.log_y
      ? Math.min(...[...times, ...obs.failures.time].filter((t) => t > 0)) / 2
      : 0;
    if (obs.n_ranges) {
      traces.push({
        x: obs.ranges.stress, y: times.map((t) => (t === 0 ? floor : t)), mode: "lines", type: "scatter",
        line: { color: "rgba(20, 23, 28, 0.25)", width: 3 }, name: "Failed between inspections",
        hoverinfo: "skip",
      });
    }
    if (obs.n_failures) {
      traces.push({
        x: obs.failures.stress, y: obs.failures.time, mode: "markers", type: "scatter",
        marker: { color: DATA_INK, size: 6 }, name: "Failure",
        hovertemplate: `${p.x_label}: %{x}<br>Failed at: %{y:.4g}<extra></extra>`,
      });
    }
  }
  if (usePoint && Number.isFinite(usePoint.x) && Number.isFinite(usePoint.y)) {
    traces.push({
      x: [usePoint.x], y: [usePoint.y], mode: "markers", type: "scatter",
      marker: { color: useMark(), size: 13, symbol: "star", line: { color: SURFACE, width: 1 } },
      name: "Use stress",
      hovertemplate: `Use stress: %{x}<br>Life: %{y:.4~g}<extra></extra>`,
    });
  }
  const layout = {
    margin: { t: 8, r: 12, b: 44, l: 64 },
    xaxis: { title: { text: p.x_label || "Stress" } },
    yaxis: {
      title: { text: `${lifeLabel}${unit ? ` (${unit})` : ""}` },
      type: p.log_y ? "log" : "linear",
      ...(p.log_y ? { dtick: "D2", tickformat: ",~g" } : {}),
    },
    showlegend: true,
    // One stress: a small legend inside, top right; two: the theme's, above.
    ...(two ? {} : { legend: { orientation: "v", x: 1, xanchor: "right", y: 1, yanchor: "top", bgcolor: legendBg() } }),
  };
  return <Plot fill={fill} data={traces} layout={layout} download={`${name || "Model"} — life against ${p.x_label || "stress"}`} />;
}

// The life at the use stress from the server, asked again (after a pause)
// whenever the use stress changes. Null until there is one.
function useLifeAtUse(modelId, use) {
  const [state, setState] = useState(null);
  const key = use ? JSON.stringify(use) : null;
  useEffect(() => {
    if (!modelId || !key) { setState(null); return undefined; }
    let live = true;
    setState((s) => (s && s.key === key ? s : { key, busy: true, ev: s?.ev || null }));
    const timer = setTimeout(() => {
      evaluateAlt(modelId, JSON.parse(key), null, {})
        .then((ev) => live && setState({ key, ev }))
        .catch((e) => live && setState({ key, error: e.message }));
    }, 350);
    return () => { live = false; clearTimeout(timer); };
  }, [modelId, key]);
  return state;
}

// The range on the life at the use stress from the calculator's answer:
// { level, lower, upper }, or null where the answer has none (it says why).
function lifeRange(ev) {
  const ci = ev?.bounds?.characteristic_life?.ci;
  if (!Array.isArray(ci) || ci.length !== 2 || !ci.every((v) => Number.isFinite(v))) return null;
  const level = Number(ev.bounds.confidence);
  return { level: Number.isFinite(level) ? level : null, lower: ci[0], upper: ci[1] };
}

function UseInputs({ results, use, onUse }) {
  return (
    <div className="alt-use-inputs">
      {(results.stresses || []).map((s, j) => (
        <label key={s.key || j} className="alt-use-field">
          <span>{inputStressName(s)}</span>
          <input type="number" inputMode="decimal" step="any" value={use[j] ?? ""}
                 aria-label={`Use stress: ${inputStressName(s)}`}
                 onChange={(e) => onUse(use.map((v, k) => (k === j ? e.target.value : v)))} />
        </label>
      ))}
    </div>
  );
}

function Side({ results, modelId, use, onUse, edited, state }) {
  const r = results;
  const unit = r.unit ? unitInText(r.unit) : "";
  const shape = shapeParam(r);
  // While a new use stress is being asked about, the last answer isn't shown:
  // it is the life at the old stress.
  const ev = state?.busy ? null : state?.ev;
  const ea = activationEnergy(r, ev || state?.ev);
  const mean = meanAtUse(ev);
  const lifeUse = ev?.metrics?.characteristic_life;
  const range = Number.isFinite(lifeUse) ? lifeRange(ev) : null;
  const rows = accelerationRows(r.levels, modelId ? lifeUse : null);
  return (
    <>
      <section className="gof-card mf-flex-none" aria-labelledby="alt-use-h">
        <div className="gofh life-card-head">
          <h3 className="mf-card-title" id="alt-use-h">{modelId ? "At your use stress" : "The fit"}</h3>
        </div>
        {modelId && (
          <div className="alt-use-box">
            <UseInputs results={r} use={use} onUse={onUse} />
            {!edited && <p className="alt-use-hint">The mildest tested level: enter your own.</p>}
            {kelvinWords(r, use) && <p className="alt-use-hint">{kelvinWords(r, use)}, as the model reads it.</p>}
            {state?.error && <p className="alt-use-hint error-text" role="alert">{state.error}</p>}
          </div>
        )}
        {modelId && <ExtrapolationNote words={useRangeWarning(r, useForModel(r, use), ev?.acceleration_factor)} />}
        {modelId && (
          <div className="gofr">
            <span className="gk">Life at use stress</span>
            <span className="gv" aria-live="polite">
              {Number.isFinite(lifeUse) ? `${formatNumber(lifeUse)}${unit ? ` ${unit}` : ""}` : state?.busy ? "…" : "—"}
              {range && (
                <span className="gof-sub alt-ci">
                  {" "}{formatNumber(range.lower)}–{formatNumber(range.upper)}
                  {range.level == null ? " (two-sided)" : ` (${formatNumber(range.level * 100)}% two-sided)`}
                </span>
              )}
            </span>
          </div>
        )}
        {modelId && mean && (
          <div className="gofr">
            <span className="gk" title="The mean time to failure at the use stress, from the fitted model">Mean life (MTTF)</span>
            <span className="gv">
              {formatNumber(mean.value)}{unit ? ` ${unit}` : ""}
              {mean.ci && (
                <span className="gof-sub alt-ci">
                  {" "}{formatNumber(mean.ci[0])}–{formatNumber(mean.ci[1])} ({formatNumber(mean.level * 100)}% two-sided)
                </span>
              )}
            </span>
          </div>
        )}
        {shape && (
          <div className="gofr">
            <span className="gk">{shape.label}</span>
            <span className="gv">
              {formatNumber(shape.value)}
              {Array.isArray(shape.ci) && <span className="gof-sub alt-ci"> {formatNumber(shape.ci[0])}–{formatNumber(shape.ci[1])} ({ciPct(results, 0.9)} two-sided)</span>}
            </span>
          </div>
        )}
        {ea && (
          <div className="gofr">
            <span className="gk" title="The activation energy: the fitted temperature coefficient (in kelvin) × Boltzmann's constant">
              Activation energy Ea
            </span>
            <span className="gv">
              {formatNumber(ea.value, { sig: 3 })} eV
              {ea.ci && <span className="gof-sub alt-ci"> {formatNumber(ea.ci[0], { sig: 3 })}–{formatNumber(ea.ci[1], { sig: 3 })} ({ea.level ? `${formatNumber(ea.level * 100)}%` : ciPct(results, 0.9)} two-sided)</span>}
            </span>
          </div>
        )}
      </section>
      <ScrollCard title={modelId ? "Acceleration factor" : "Life at each tested level"}
                  sub={modelId ? "use ÷ each level" : null} id="alt-af-h">
        <table className="mini-table">
          <thead>
            <tr>
              <th>Tested at</th>
              <th className="mf-num">Life{unit ? ` (${unit})` : ""}</th>
              {modelId && <th className="mf-num">Factor</th>}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i}>
                <td>{levelWords(row.stress, r.stresses)}</td>
                <td className="mf-num">{formatNumber(row.life)}</td>
                {modelId && <td className="mf-num">{row.af == null ? "—" : `${formatNumber(row.af)}×`}</td>}
              </tr>
            ))}
          </tbody>
        </table>
        {modelId && (
          <p className="mf-note">How many times longer a unit lasts at the use stress than at each tested level.</p>
        )}
      </ScrollCard>
    </>
  );
}

export default function AltLifeStress({ results, modelId, name, use, onUse, edited }) {
  const r = results || {};
  // The life drawn: the median (default) or B10, each with its one-sided
  // lower bound, or the characteristic life with its two-sided band. One
  // stress, on a saved model (the use-stress answer carries the lines).
  const [which, setWhich] = useState("b50");
  // In the model's units (kelvin for a temperature given in °C): what the
  // model is asked at and where the chart (in kelvin) marks it.
  const numeric = useForModel(r, use);
  const state = useLifeAtUse(modelId, numeric);
  // Only an answer for the use stress now in the box (not one still on its way).
  const ev = state?.ev && !state.busy && state.key === JSON.stringify(numeric) ? state.ev : null;
  const lifeUse = ev?.metrics?.characteristic_life;
  const lines = ev?.life_lines || [];
  // The charts in the user's units (°C for a temperature typed in °C); the
  // model is asked in kelvin, so its answers are turned back for the chart.
  const plots = [r.life_stress_plot, r.life_stress_plot_2].filter(Boolean)
    .map((p, j) => plotInEnteredUnits(p, r.stresses, j));
  const shown = (v, j) => (v == null ? v : fromKelvin(v, enteredUnit(r.stresses?.[j])));
  const alongShown = (ln, j) => (ln && Array.isArray(ln.stress) ? { ...ln, stress: ln.stress.map((v) => shown(v, j)) } : ln);
  const side = <Side results={r} modelId={modelId} use={use} onUse={onUse} edited={edited} state={state} />;
  // The median or B10 line and the tested levels' marks for it (one stress).
  const canChoose = plots.length === 1 && !!lines[0]?.quantiles;
  const want = canChoose ? which : "eta";
  const tested = (ev?.tested_lives || []).map((t) => ({ ...t, stress: shown(t.stress?.[0], 0) }));
  const chosen = want === "eta" ? null : lifeLineFor(alongShown(lines[0], 0), want, tested);
  const life = chosen ? want : "eta";
  const useLife = life === "eta" ? lifeUse : ev?.metrics?.[life];
  const lifeLabel = { b50: "Median life", b10: "B10 life", eta: "Characteristic life" }[life];
  const chart = (j) => (
    <PlotCard key={j} title={plots.length > 1 ? `Life against ${plots[j].x_label}` : null}
              controls={canChoose && j === 0 && (
                <SegmentedControl size="sm" label="Life shown" value={which} onChange={setWhich} options={CHART_LIVES} />
              )}>
      <LifeStressChart
        plot={plots[j]}
        unit={r.unit}
        name={name}
        lifeLabel={lifeLabel}
        along={(chosen && j === 0 ? chosen.line : alongShown(lines[j], j)) || null}
        points={chosen && j === 0 ? chosen.points.map((t) => ({ stress: t.stress, life: t.life, secondary: null })) : null}
        otherUse={numeric && plots.length > 1 ? shown(numeric[1 - j], 1 - j) : null}
        usePoint={ev && numeric ? { x: shown(numeric[j], j), y: plots.length > 1 ? lifeUse : useLife } : null}
      />
    </PlotCard>
  );
  if (plots.length < 2) return <PlotPanel plot={chart(0)} side={side} />;
  // Alternatives: the same life, along one stress or the other.
  const items = plots.map((p, j) => ({ id: j, label: (r.stresses?.[j]?.label) || p.x_label, node: chart(j) }));
  return <PlotPanel plot={<ChartPair label="Life against" items={items} />} side={side} />;
}

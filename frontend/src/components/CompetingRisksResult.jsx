// A competing-risks fit (#177): life data by failure mode, in the model
// frame's tabs (components/model/). Failure modes (the incidence chart and
// each mode's share), Effects (with covariates: the regression by mode),
// Calculator (the stored curves read at a time, or the time to a chance),
// Diagnostics (how much data stands behind each curve, Gray's test, the
// regression's fit) and Data (the counts, the incidence table, every
// coefficient and how it was fitted).
import { useState } from "react";
import { Link } from "react-router-dom";
import CompetingRisksPlot, { causeColor } from "./CompetingRisksPlot.jsx";
import Plot from "./Plot.jsx";
import Select from "./Select.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import { ModelTabs } from "./model/ModelFrame.jsx";
import { CheckCard, ChecksGrid, PlotCard, PlotPanel, ScrollCard, TablePanel } from "./model/ModelLayouts.jsx";
import { ForestChart } from "./model/Effects.jsx";
import { unitInText } from "./unitText.js";
import { formatNumber } from "../format.js";
import { DATA_INK, referenceShape } from "../plotTheme.js";
import { modelTabs, resolveTab } from "../modelFrame.js";
import {
  ANY_MODE, anyAt, causesAt, effectsByMode, incidenceRows, leadSentence, modeSupport, pct, readingAt,
  timeToChance, widestBand,
} from "../competingRisks.js";
import "./NonParametric.css";
import "./CompetingRisks.css";

const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);
const pText = (p) => (p == null ? "—" : p < 0.001 ? "< 0.001" : formatNumber(p, { sig: 2 }));
const band = (lo, hi) => (lo != null && hi != null ? `${pct(lo)}–${pct(hi)}` : "—");
const unitOf = (result) => (result.unit ? unitInText(result.unit) : "");
const at = (v, unit) => `${formatNumber(v)}${unit ? ` ${unit}` : ""}`;

function ModeName({ name, i }) {
  return (
    <span className="cr-name">
      <span className="cr-dot" style={{ background: causeColor(i) }} aria-hidden="true" />
      {cap(name)}
    </span>
  );
}

// ---- Failure modes ----------------------------------------------------------

// The panel beside the chart: each mode's share of the failures by the
// horizon, its count and the chance of failing from it by then, the data,
// the group comparison (in Diagnostics) and the reading.
function ModesAside({ result, onGroups }) {
  const unit = unitOf(result);
  const when = at(result.horizon, unit);
  const causes = result.causes || [];
  const gray = result.gray;
  const running = result.running || 0;
  const lead = leadSentence(result.leads, unit);
  const top = causes.reduce((a, b) => ((b.at?.cif || 0) > (a?.at?.cif || 0) ? b : a), null);
  return (
    <>
      <section className="gof-card" aria-labelledby="cr-modes-title">
        <div className="gofh mf-card-head">
          <span>
            <h3 className="mf-card-title" id="cr-modes-title">Failure modes</h3>
            <span className="gof-sub">by {when}</span>
          </span>
        </div>
        <div className="gofr cr-mode-head" aria-hidden="true">
          <span className="gk">Mode</span><span className="gk">Share of failures</span>
        </div>
        {causes.map((k, i) => (
          <div className="gofr cr-mode-row" key={k.name}>
            <span className="gk">
              <ModeName name={k.name} i={i} />
              <span className="cr-mode-sub">
                {pct(k.at?.cif)} of units{k.at?.lower != null && k.at?.upper != null ? ` (${band(k.at.lower, k.at.upper)})` : ""}
              </span>
              <span className="cr-mode-sub">{formatNumber(k.failures)} failure{k.failures === 1 ? "" : "s"}</span>
            </span>
            <span className="gv"><span className="sr-only">Share of failures: </span>{pct(k.share)}</span>
          </div>
        ))}
        <div className="gofr">
          <span className="gk">Data</span>
          <span className="gv">
            {formatNumber(result.failed)} failed{running ? `, ${formatNumber(running)} running` : ""}
          </span>
        </div>
        {gray && (gray.available ? (
          <button type="button" className="gofr gofr-link" onClick={onGroups}>
            <span className="gk">By {gray.group_column}</span>
            <span className="gv">{gray.results.some((r) => r.significant) ? "Differs" : "No clear difference"} ›</span>
          </button>
        ) : (
          <div className="gofr"><span className="gk cr-note">{gray.reason}</span></div>
        ))}
      </section>
      <div className="life-reading">
        <div className="life-reading-title">{causes.length > 1 && top ? `${cap(top.name)} leads` : "Reading"}</div>
        <div>{readingAt(result, result.horizon, unit)}{lead ? ` ${lead}` : ""}</div>
      </div>
    </>
  );
}

function ModesTab({ result, name, onGroups }) {
  const [stacked, setStacked] = useState(true);
  return (
    <PlotPanel
      plot={(
        <PlotCard
          controls={(
            <div className="plot-option-row">
            <SegmentedControl
              size="sm"
              label="Show"
              showLabel
              options={[
                { value: true, label: "Stacked", title: "The modes stacked: the top is the chance of failing from any mode" },
                { value: false, label: "Each mode",
                  title: result.mode_bounds === false ? "Each mode on its own" : "Each mode on its own, with its 95% band" },
              ]}
              value={stacked}
              onChange={setStacked}
            />
            </div>
          )}
        >
          <CompetingRisksPlot fill result={result} unit={result.unit} stacked={stacked}
                              download={`${name || "Failure modes"} — chance of failing by mode`} />
        </PlotCard>
      )}
      side={<ModesAside result={result} onGroups={onGroups} />}
      sideClassName="cr-side"
    />
  );
}

// ---- Effects ----------------------------------------------------------------

function EffectsTab({ result, name }) {
  const reg = result.regression;
  const label = reg.ratio_label === "hazard ratio" ? "hazard ratio" : "subdistribution hazard ratio";
  const rows = reg.coefficients.map((c) => ({
    name: reg.covariates.length > 1 ? `${cap(c.cause)}: ${c.covariate}` : cap(c.cause),
    ratio: c.ratio, lo: c.ratio_ci?.[0] ?? null, hi: c.ratio_ci?.[1] ?? null, p: c.p_value,
  }));
  const words = effectsByMode(reg);
  const failed = reg.maximum && reg.maximum !== "verified";
  return (
    <PlotPanel
      plot={(
        <PlotCard title={reg.covariates.length > 1 ? "Each covariate's effect on each mode"
          : `The effect of ${reg.covariates[0]} on each mode`}>
          <ForestChart rows={rows} ratioLabel={label} name={name} download={`${name || "Failure modes"} — effects by mode`} />
        </PlotCard>
      )}
      side={(
        <>
          <ScrollCard title="In words" sub={reg.model === "Cox" ? "cause-specific Cox" : "Fine-Gray"}>
            <ul className="mf-effects-words">
              {words.flatMap((m) => m.lines.map((l) => (
                <li key={`${m.mode}|${l.covariate}`}>
                  {l.text}
                  {l.p != null && <span className="mf-effect-p"> p {l.p < 0.001 ? "" : "= "}{pText(l.p)}.</span>}
                </li>
              )))}
            </ul>
          </ScrollCard>
          <section className="gof-card mf-flex-none">
            <p className="mf-note">
              {reg.model === "Cox"
                ? "A ratio multiplies the failure rate from that mode, among units still running."
                : "A ratio multiplies the chance of failing from that mode, with the other modes acting."}{" "}
              Above 1 the mode comes sooner; below 1, later.
            </p>
            {failed && <p className="mf-note cr-warn">The fit has no finite maximum: these ratios aren&apos;t estimates.</p>}
          </section>
        </>
      )}
      sideClassName="cr-side cr-side-wide"
    />
  );
}

// ---- Calculator -------------------------------------------------------------

export const initCrCalc = (result) => ({
  mode: "value",
  t: String(result?.horizon ?? ""),
  p: "10",
  which: ANY_MODE,
});

function CrCalculator({ result, name, state, setState }) {
  const unit = unitOf(result);
  const set = (patch) => setState((s) => ({ ...s, ...patch }));
  const last = result.curves?.x?.length ? result.curves.x[result.curves.x.length - 1] : null;
  const tNum = Number(state.t);
  const tOk = state.t !== "" && Number.isFinite(tNum) && tNum >= 0;
  const pNum = Number(state.p);
  const pOk = state.p !== "" && Number.isFinite(pNum) && pNum > 0 && pNum < 100;
  const timeMode = state.mode === "time";
  const causes = result.causes || [];
  const whichLabel = state.which === ANY_MODE ? "any mode" : state.which;

  let answer;
  let shapes = [];
  let table = null;
  if (!timeMode) {
    const rows = tOk ? causesAt(result, tNum) : [];
    const any = tOk ? anyAt(result, tNum) : null;
    shapes = tOk ? [referenceShape({ x: tNum, line: { dash: "dot" } })] : [];
    const top = rows.reduce((a, b) => ((b.cif || 0) > (a?.cif || 0) ? b : a), null);
    answer = (
      <div className="calc-answer">
        <span>
          Chance of failing by <b>{tOk ? at(tNum, unit) : "—"}</b>
          {top?.cif ? <>: <b>{top.name}</b> leads with <b>{pct(top.cif)}</b> of units</> : null}
          {causes.length > 1 && any?.cif != null ? <>; any mode <b>{pct(any.cif)}</b></> : null}
        </span>
      </div>
    );
    table = tOk && (
      <div className="cr-calc-table">
        <table className="calc-table">
          <thead>
            <tr><th>Failure mode</th><th>Chance by then</th><th>95% band</th><th>Share of failures</th></tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={r.name}>
                <td className="cr-left"><ModeName name={r.name} i={i} /></td>
                <td><b>{pct(r.cif)}</b></td>
                <td>{band(r.lower, r.upper)}</td>
                <td>{pct(r.share)}</td>
              </tr>
            ))}
            {causes.length > 1 && (
              <tr className="cr-any-row">
                <td className="cr-left">Any mode</td>
                <td><b>{pct(any?.cif)}</b></td>
                <td>{band(any?.lower, any?.upper)}</td>
                <td>100%</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    );
  } else {
    const r = pOk ? timeToChance(result, state.which, pNum / 100) : null;
    if (r?.time != null) {
      shapes = [referenceShape({ y: pNum / 100, line: { dash: "dot" } }), referenceShape({ x: r.time, line: { dash: "dot" } })];
    } else if (pOk) {
      shapes = [referenceShape({ y: pNum / 100, line: { dash: "dot" } })];
    }
    let range = null;
    if (r?.time != null) {
      if (r.lower != null && r.upper != null) range = `we're 95% sure it's between ${at(r.lower, unit)} and ${at(r.upper, unit)}`;
      else if (r.lower != null) range = `we're 95% sure it's after ${at(r.lower, unit)}; the data can't bound it from above`;
    }
    answer = (
      <div className="calc-answer">
        <span>
          Time until <b>{pOk ? `${formatNumber(pNum)}%` : "—"}</b> of units have failed from <b>{whichLabel}</b>:
        </span>
        <span className="calc-answer-value">
          {r?.time != null ? <b>{at(r.time, unit)}</b> : <b>—</b>}
          {range && <span className="calc-answer-ci"> — {range}</span>}
        </span>
      </div>
    );
    if (pOk && r?.time == null) {
      table = (
        <p className="calc-warn">
          Not reached within the data: {whichLabel} reaches only {pct(r?.top ?? 0)} by{" "}
          {at(r?.last, unit)}, the last time in the data.
        </p>
      );
    }
  }
  const beyond = !timeMode && tOk && last != null && tNum > last;

  return (
    <div className="calc cr-calc">
      <div className="calc-body">
        <div className="calc-main">
          {answer}
          {beyond && (
            <p className="calc-warn">
              {at(tNum, unit)} is past the last time in the data ({at(last, unit)}): the curves stop there, so
              these are the values at {at(last, unit)}.
            </p>
          )}
          {table}
          <CompetingRisksPlot
            fill
            result={result}
            unit={result.unit}
            stacked={false}
            showAll={!timeMode || state.which === ANY_MODE}
            only={timeMode ? (state.which === ANY_MODE ? [] : [state.which]) : null}
            shapes={shapes}
            download={`${name || "Failure modes"} — calculator`}
          />
        </div>
        <div className="calc-side-rail">
          <div className="calc-rail-card calc-eval-card">
            <div className="gofh">Inputs</div>
            <div className="calc-eval-body">
              <SegmentedControl
                label="What to calculate"
                size="sm"
                className="calc-mode"
                value={state.mode}
                onChange={(v) => set({ mode: v })}
                options={[
                  { value: "value", label: "Chance by a time" },
                  { value: "time", label: "Time to a chance",
                    title: "The time by which a share of units have failed from a mode, or from any mode" },
                ]}
              />
              {timeMode ? (
                <>
                  <label className="calc-t">
                    <span>Failed from</span>
                    <Select
                      value={state.which}
                      onChange={(v) => set({ which: v })}
                      ariaLabel="Failed from"
                      options={[
                        { value: ANY_MODE, label: "Any mode" },
                        ...causes.map((k) => ({ value: k.name, label: cap(k.name) })),
                      ]}
                    />
                  </label>
                  <label className="calc-t">
                    <span>Share of units failed %</span>
                    <input type="number" inputMode="decimal" min={0.01} max={99.99} step="any"
                           value={state.p} onChange={(e) => set({ p: e.target.value })} />
                  </label>
                  {!pOk && state.p !== "" && <p className="calc-note">Give a share between 0 and 100%.</p>}
                </>
              ) : (
                <label className="calc-t">
                  <span>By{unit ? ` (${unit})` : ""}</span>
                  <input type="number" inputMode="decimal" min={0} step="any"
                         value={state.t} onChange={(e) => set({ t: e.target.value })} />
                </label>
              )}
              <p className="calc-note">
                Read off the curves on the Failure modes tab
                {result.mode_bounds === false ? ", whose modes have no band of their own" : ", with their 95% bands"}.
                {last != null && ` The data ends at ${at(last, unit)}.`}
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---- Diagnostics ------------------------------------------------------------

// Each mode's chance by the horizon with its 95% band, as a dot and a bar.
function BandsChart({ result, name }) {
  const unit = unitOf(result);
  const rows = (result.causes || []).map((k) => ({ name: cap(k.name), ...k.at }));
  const any = anyAt(result, result.horizon);
  if ((result.causes || []).length > 1) rows.push({ name: "Any mode", ...any });
  const has = (r) => r.lower != null && r.upper != null;
  const trace = {
    type: "scatter", mode: "markers",
    x: rows.map((r) => r.cif), y: rows.map((r) => r.name),
    marker: { color: rows.map((r, i) => (r.name === "Any mode" ? DATA_INK : causeColor(i))), size: 10, symbol: "square" },
    error_x: {
      type: "data", symmetric: false, color: DATA_INK, thickness: 1.5, width: 6,
      array: rows.map((r) => (has(r) ? r.upper - r.cif : 0)),
      arrayminus: rows.map((r) => (has(r) ? r.cif - r.lower : 0)),
    },
    customdata: rows.map((r) => (has(r) ? `${pct(r.lower)} to ${pct(r.upper)}` : "no band")),
    hovertemplate: "%{y}: %{x:.1%} (95% %{customdata})<extra></extra>",
  };
  return (
    <Plot fill data={[trace]} download={`${name || "Failure modes"} — bands`}
          layout={{
            showlegend: false, margin: { t: 8, r: 16, b: 46, l: 12 },
            xaxis: { title: { text: `Chance of failing by ${at(result.horizon, unit)}` }, tickformat: ".0%",
                     range: [0, Math.min(1, Math.max(0.05, ...rows.map((r) => r.upper ?? r.cif ?? 0)) * 1.1)], nticks: 6 },
            yaxis: { type: "category", autorange: "reversed", automargin: true, showgrid: false, ticks: "" },
          }} />
  );
}

function GrayCheck({ gray, unit }) {
  if (!gray.available) {
    return <CheckCard question={`Do the modes differ by ${gray.group_column}?`} term="Gray's test" verdict={gray.reason} />;
  }
  const hit = gray.results.some((r) => r.significant);
  return (
    <CheckCard question={`Do the modes differ by ${gray.group_column}?`} term="Gray's test"
               tone={hit ? undefined : "good"} verdict={gray.sentence}
               footer={`The share of each group's units failing from each mode by ${at(gray.horizon, unit)}; `
                 + "under 0.05, a mode clearly differs."}>
      <table className="mini-table cr-table">
        <thead>
          <tr>
            <th>Failure mode</th>
            {gray.groups.map((g) => <th key={g}>{gray.group_column} {g}</th>)}
            <th>p-value</th>
          </tr>
        </thead>
        <tbody>
          {gray.results.map((r) => (
            <tr key={r.cause} className={r.significant ? "cr-sig" : undefined}>
              <td>{cap(r.cause)}{r.significant && <span className="sr-only"> (differs)</span>}</td>
              {r.by_group.map((b) => <td key={b.group}>{pct(b.cif)}</td>)}
              <td title={r.error || undefined}>{r.error ? "—" : pText(r.p_value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </CheckCard>
  );
}

function RegressionCheck({ reg }) {
  const ok = !reg.maximum || reg.maximum === "verified";
  const notes = reg.warnings || [];
  return (
    <CheckCard question="Did the regression fit?" term={reg.model === "Cox" ? "cause-specific Cox" : "Fine-Gray"}
               tone={ok ? (notes.length ? "caveat" : "good") : "bad"}
               verdict={ok
                 ? `The fit found its maximum${notes.length ? ", with a note from the fit" : ""}.`
                 : "The fit has no finite maximum: the ratios on Effects aren't estimates."}>
      {reg.aic != null && <p className="muted-line">AIC {formatNumber(reg.aic, { sig: 5 })}</p>}
      {notes.map((w) => <p className="muted-line" key={w}>{w}</p>)}
    </CheckCard>
  );
}

function CrDiagnostics({ result, name }) {
  const unit = unitOf(result);
  const support = modeSupport(result);
  const total = support.rows.reduce((s, r) => s + (Number(r.failures) || 0), 0);
  const running = result.running || 0;
  const n = result.n || (result.failed || 0) + running;
  return (
    <ChecksGrid
      className="cr-checks"
      side={(
        <>
          <section className="gof-card mf-flex-none" aria-labelledby="cr-diag-data">
            <div className="gofh"><h3 className="mf-card-title" id="cr-diag-data">The data</h3></div>
            <div className="gofr"><span className="gk">Units</span><span className="gv">{formatNumber(n, { sig: 6 })}</span></div>
            <div className="gofr"><span className="gk">Failed</span><span className="gv">{formatNumber(result.failed, { sig: 6 })}</span></div>
            <div className="gofr">
              <span className="gk">Still running</span>
              <span className="gv">{formatNumber(running, { sig: 6 })}{n ? ` (${pct(running / n)})` : ""}</span>
            </div>
            <div className="gofr"><span className="gk">Failure modes</span><span className="gv">{support.rows.length}</span></div>
            {result.last_failure != null && (
              <div className="gofr"><span className="gk">Last failure</span><span className="gv">{at(result.last_failure, unit)}</span></div>
            )}
          </section>
          <section className="gof-card mf-flex-none">
            <p className="mf-note">
              No distribution is assumed, so there is no fit to test: each curve is the data&apos;s own. These checks
              say how much data stands behind each curve
              {result.gray ? " and whether the groups differ" : ""}.
            </p>
          </section>
        </>
      )}
    >
      <CheckCard question="Is there enough data for each mode?" term="failures per mode" tone={support.tone}
                 verdict={support.words}>
        <table className="mini-table cr-table">
          <thead><tr><th>Failure mode</th><th>Failures</th><th>Of all failures</th></tr></thead>
          <tbody>
            {support.rows.map((r, i) => (
              <tr key={r.name}>
                <td><ModeName name={r.name} i={i} />{r.few && <span className="cr-few"> · few</span>}</td>
                <td>{formatNumber(r.failures, { sig: 6 })}</td>
                <td>{total ? pct(r.failures / total) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CheckCard>
      <CheckCard chart question="How sure is each mode's chance?" term={result.mode_bounds === false ? "Kaplan-Meier bounds" : "Aalen's 95% bounds"}
                 verdict={result.mode_bounds === false
                   ? "Each mode's curve comes without a band here; only any mode has one."
                   : widestBand(result, unit)}>
        <BandsChart result={result} name={name} />
      </CheckCard>
      {result.gray && <GrayCheck gray={result.gray} unit={unit} />}
      {result.regression && <RegressionCheck reg={result.regression} />}
    </ChecksGrid>
  );
}

// ---- Data -------------------------------------------------------------------

function howNotes(result) {
  const out = [];
  out.push(result.mode_bounds === false
    ? "Non-parametric cumulative incidence (Aalen-Johansen): no distribution is assumed. The chance of failing from "
      + "any mode has Kaplan-Meier 95% pointwise bounds; each mode's own curve comes without a band."
    : "Non-parametric cumulative incidence (Aalen-Johansen), with Aalen's 95% pointwise bounds: no distribution is "
      + "assumed.");
  out.push("A mode's curve is the chance of failing from it by each time while the other modes still act, so the "
    + "curves add up to the chance of failing from any mode.");
  if (result.cause_column) out.push(`Failure modes from “${result.cause_column}”; a blank mode is a unit still running.`);
  if (result.gray) out.push(`Groups from “${result.gray.group_column}”, compared with Gray's test.`);
  const reg = result.regression;
  if (reg) {
    out.push(`${reg.model === "Cox" ? "Cause-specific Cox" : "Fine-Gray"} regression on ${reg.covariates.join(", ")}`
      + (reg.aic != null ? ` (AIC ${formatNumber(reg.aic, { sig: 5 })}).` : "."));
  }
  return out;
}

function CrDataTab({ result, datasetId }) {
  const unit = unitOf(result);
  const names = (result.causes || []).map((k) => k.name);
  const rows = incidenceRows(result);
  const reg = result.regression;
  const running = result.running || 0;
  return (
    <TablePanel
      className="mf-l5-wide"
      main={(
        <>
          <section className="gof-card mf-flex-none" aria-labelledby="cr-data-counts">
            <div className="gofh mf-card-head">
              <h3 className="mf-card-title" id="cr-data-counts">What it was fitted to</h3>
              {datasetId && <Link className="link" to={`/data/${datasetId}`}>Open the dataset ›</Link>}
            </div>
            {result.n != null && <div className="gofr"><span className="gk">Units</span><span className="gv">{formatNumber(result.n, { sig: 6 })}</span></div>}
            <div className="gofr"><span className="gk">Failed</span><span className="gv">{formatNumber(result.failed, { sig: 6 })}</span></div>
            {running > 0 && <div className="gofr"><span className="gk">Still running</span><span className="gv">{formatNumber(running, { sig: 6 })}</span></div>}
            <div className="gofr"><span className="gk">Failure modes</span><span className="gv">{names.length}</span></div>
            {result.unit && <div className="gofr"><span className="gk">Time unit</span><span className="gv">{unit}</span></div>}
          </section>
          <ScrollCard title="Chance of failing by each time" sub="at each failure time, from the data">
            <table className="mini-table">
              <thead>
                <tr>
                  <th>Time{unit ? ` (${unit})` : ""}</th>
                  {names.map((n) => <th className="mf-num" key={n}>{cap(n)}</th>)}
                  {names.length > 1 && <th className="mf-num">Any mode</th>}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.x}>
                    <td>{formatNumber(r.x, { sig: 4 })}</td>
                    {r.modes.map((v, i) => <td className="mf-num" key={names[i]}>{pct(v)}</td>)}
                    {names.length > 1 && <td className="mf-num">{pct(r.any)}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollCard>
        </>
      )}
      side={(
        <>
          <section className="gof-card mf-flex-none" aria-labelledby="cr-data-modes">
            <div className="gofh mf-card-head">
              <span>
                <h3 className="mf-card-title" id="cr-data-modes">Failures by mode</h3>
                <span className="gof-sub">by {at(result.horizon, unit)}</span>
              </span>
            </div>
            <div className="cr-table-wrap">
              <table className="mini-table cr-table">
                <thead><tr><th>Mode</th><th>Failures</th><th>Share</th><th>Chance</th><th>95% band</th></tr></thead>
                <tbody>
                  {(result.causes || []).map((k, i) => (
                    <tr key={k.name}>
                      <td><ModeName name={k.name} i={i} /></td>
                      <td>{formatNumber(k.failures, { sig: 6 })}</td>
                      <td>{pct(k.share)}</td>
                      <td>{pct(k.at?.cif)}</td>
                      <td>{band(k.at?.lower, k.at?.upper)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
          {reg ? (
            <ScrollCard title="Every coefficient" sub="per mode, with 95% intervals">
              <table className="mini-table cr-table cr-coef-table">
                <thead>
                  <tr><th>Mode</th><th>Covariate</th><th>β</th>
                    <th>{reg.ratio_label === "hazard ratio" ? "Hazard ratio" : "Subdist. HR"}</th>
                    <th>95% interval</th><th>p</th></tr>
                </thead>
                <tbody>
                  {reg.coefficients.map((c) => (
                    <tr key={`${c.cause}|${c.covariate}`}>
                      <td>{cap(c.cause)}</td>
                      <td>{c.covariate}</td>
                      <td>{formatNumber(c.coef, { sig: 4 })}</td>
                      <td>{formatNumber(c.ratio, { sig: 3 })}</td>
                      <td>{c.ratio_ci?.[0] != null ? `${formatNumber(c.ratio_ci[0])}–${formatNumber(c.ratio_ci[1])}` : "—"}</td>
                      <td>{pText(c.p_value)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </ScrollCard>
          ) : (
            <section className="gof-card mf-flex-none">
              <div className="gofh">Parameters</div>
              <p className="mf-note">None: the curves assume no distribution, so there are no fitted parameters.</p>
            </section>
          )}
          <section className="gof-card mf-flex-none" aria-labelledby="cr-data-how">
            <div className="gofh"><h3 className="mf-card-title" id="cr-data-how">How it was fitted</h3></div>
            {howNotes(result).map((t) => <p className="mf-note" key={t}>{t}</p>)}
          </section>
        </>
      )}
    />
  );
}

// ---- The tabs ---------------------------------------------------------------

// ``tab`` / ``onTab``: the open tab (a page keeps it in its address);
// without them the view keeps its own. ``datasetId``: the data it was
// fitted to, for the Data tab.
export default function CompetingRisksResult({ result, name = null, datasetId = null, tab: wanted = undefined, onTab = null }) {
  const tabs = modelTabs(result) || [];
  const [own, setOwn] = useState(() => resolveTab(tabs, wanted));
  const tab = resolveTab(tabs, wanted !== undefined && onTab ? wanted : own);
  const setTab = (id) => {
    setOwn(id);
    onTab?.(id);
  };
  // The calculator's inputs survive a tab switch; a new result resets them.
  const [calc, setCalc] = useState(() => initCrCalc(result));
  const [prev, setPrev] = useState(result);
  if (result !== prev) {
    setPrev(result);
    setCalc(initCrCalc(result));
    setOwn(resolveTab(modelTabs(result) || [], null));
  }

  let body = null;
  switch (tab) {
    case "modes":
      body = <ModesTab result={result} name={name} onGroups={() => setTab("diag")} />;
      break;
    case "effects":
      body = <EffectsTab result={result} name={name} />;
      break;
    case "calc":
      body = <CrCalculator result={result} name={name} state={calc} setState={setCalc} />;
      break;
    case "diag":
      body = <CrDiagnostics result={result} name={name} />;
      break;
    case "data":
      body = <CrDataTab result={result} datasetId={datasetId} />;
      break;
    default:
  }
  return <ModelTabs tabs={tabs} value={tab} onChange={setTab}>{body}</ModelTabs>;
}

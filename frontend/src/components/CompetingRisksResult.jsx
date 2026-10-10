import { useState } from "react";
import CompetingRisksPlot, { causeColor } from "./CompetingRisksPlot.jsx";
import Modal from "./Modal.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import { ResultDetails } from "./ui/ResultSummary.jsx";
import { unitInText } from "./unitText.js";
import { formatNumber } from "../format.js";
import { causesAt, effectSentence, leadSentence, pct, readingAt } from "../competingRisks.js";
import "./NonParametric.css";
import "./CompetingRisks.css";

const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);
const pText = (p) => (p == null ? "—" : p < 0.001 ? "< 0.001" : formatNumber(p, { sig: 2 }));

// Gray's test per failure mode across the groups, in the statistics dialog:
// each mode's p-value and each group's incidence of it at the horizon.
function GrayTable({ gray, unit }) {
  const when = `${formatNumber(gray.horizon)}${unit ? ` ${unit}` : ""}`;
  return (
    <>
      <p className="cr-modal-lead">{gray.sentence}</p>
      <div className="rs-table-wrap">
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
                <td>{cap(r.cause)}</td>
                {r.by_group.map((b) => <td key={b.group}>{pct(b.cif)}</td>)}
                <td title={r.error || undefined}>{r.error ? "—" : pText(r.p_value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted-line">
        The share of each group's units that fail from each mode by {when}. Gray's test asks whether a
        mode's chance differs between the groups, with the other modes still acting; under 0.05, it
        clearly does.
      </p>
    </>
  );
}

// Coefficients per failure mode (the advanced choice): the ratio each
// covariate multiplies by, with its 95% interval and p-value.
function CoefficientsByMode({ regression }) {
  const label = regression.ratio_label === "hazard ratio" ? "Hazard ratio" : "Subdistribution hazard ratio";
  const sig = regression.coefficients.filter((c) => c.p_value != null && c.p_value < 0.05);
  return (
    <div className="cr-coef">
      <p className="cr-modal-lead">
        {sig.length
          ? `${sig.map((c) => effectSentence(c, regression.ratio_label)).join("; ")}.`
          : "No covariate changes any failure mode clearly (every p ≥ 0.05)."}
      </p>
      <div className="rs-table-wrap">
        <table className="mini-table cr-table">
          <thead>
            <tr><th>Failure mode</th><th>Covariate</th><th>{label}</th><th>95% interval</th><th>p-value</th></tr>
          </thead>
          <tbody>
            {regression.coefficients.map((c) => (
              <tr key={`${c.cause}|${c.covariate}`} className={c.p_value < 0.05 ? "cr-sig" : undefined}>
                <td>{cap(c.cause)}</td>
                <td>{c.covariate}</td>
                <td>{formatNumber(c.ratio, { sig: 3 })}</td>
                <td>{c.ratio_ci?.[0] != null ? `${formatNumber(c.ratio_ci[0])}–${formatNumber(c.ratio_ci[1])}` : "—"}</td>
                <td>{pText(c.p_value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted-line">
        {regression.model === "Cox"
          ? "Cause-specific Cox: a ratio multiplies the failure rate from that mode, among units still running."
          : "Fine-Gray: a ratio multiplies the subdistribution hazard, so it moves the chance of failing from "
            + "that mode with the other modes acting."}{" "}
        Above 1 the mode comes sooner; below 1, later.
        {regression.aic != null && ` AIC ${formatNumber(regression.aic, { sig: 5 })}.`}
      </p>
      {regression.maximum && regression.maximum !== "verified" && (
        <p className="life-reading caveat">The fit has no finite maximum: these ratios aren't estimates.</p>
      )}
      {(regression.warnings || []).map((w) => <p className="muted-line" key={w}>{w}</p>)}
    </div>
  );
}

// The answer panel beside the chart: each mode's chance by a time (typed in
// place, the round time near the last failure by default), the data, the
// group comparison in a dialog, and the reading.
function CompetingRisksAside({ result }) {
  const unit = result.unit ? unitInText(result.unit) : "";
  const [text, setText] = useState(String(result.horizon ?? ""));
  const typed = Number(text);
  const t = text !== "" && Number.isFinite(typed) && typed >= 0 ? typed : result.horizon;
  const rows = causesAt(result, t);
  const [grayOpen, setGrayOpen] = useState(false);
  const gray = result.gray;
  const running = result.running || 0;
  const lead = leadSentence(result.leads, unit);
  return (
    <div className="aside">
      <div className="gof-card">
        <div className="gofh">Failure modes</div>
        <div className="gofr">
          <span className="gk">Units failed by</span>
          <label className="cr-by">
            <input
              className="cr-t"
              type="number"
              min="0"
              step="any"
              value={text}
              aria-label={`Time to read the failure modes at${unit ? ` (${unit})` : ""}`}
              onChange={(e) => setText(e.target.value)}
            />
            {unit}
          </label>
        </div>
        {rows.map((r, i) => (
          <div
            className="gofr life-row"
            key={r.name}
            title={r.lower != null && r.upper != null
              ? `${pct(r.cif)} of units fail from ${r.name} by ${formatNumber(t)}${unit ? ` ${unit}` : ""}: `
                + `we're 95% sure it's between ${pct(r.lower)} and ${pct(r.upper)}.`
              : undefined}
          >
            <span className="gk cr-name"><span className="cr-dot" style={{ background: causeColor(i) }} />{cap(r.name)}</span>
            <span className="gv">{pct(r.cif)}</span>
            <span className="life-lo">{r.lower != null && r.upper != null ? `${pct(r.lower)}–${pct(r.upper)}` : ""}</span>
          </div>
        ))}
        <div className="gofr">
          <span className="gk">Data</span>
          <span className="gv">
            {formatNumber(result.failed)} failed{running ? `, ${formatNumber(running)} running` : ""}
          </span>
        </div>
        {gray && (gray.available ? (
          <button type="button" className="gofr gofr-link" onClick={() => setGrayOpen(true)}>
            <span className="gk">By {gray.group_column}</span>
            <span className="gv">
              {gray.results.some((r) => r.significant) ? "Differs" : "No clear difference"} ›
            </span>
          </button>
        ) : (
          <div className="gofr"><span className="gk cr-note">{gray.reason}</span></div>
        ))}
      </div>
      <div className="life-reading">
        <div className="life-reading-title">
          {rows.length > 1 && rows.some((r) => r.cif) ? `${cap(rows.reduce((a, b) => ((b.cif || 0) > (a.cif || 0) ? b : a)).name)} leads` : "Reading"}
        </div>
        <div>{readingAt(result, t, unit)}{lead ? ` ${lead}` : ""}</div>
      </div>
      {grayOpen && (
        <Modal title={`Failure modes by ${gray.group_column}`} onClose={() => setGrayOpen(false)}
               footer={<div className="row" style={{ margin: 0, marginLeft: "auto" }}>
                 <button onClick={() => setGrayOpen(false)}>Done</button></div>}>
          <GrayTable gray={gray} unit={unit} />
        </Modal>
      )}
    </div>
  );
}

// A competing-risks fit (#177): life data by failure mode. The tabs come
// first; the chart sits beside the answer panel; the regression by mode (the
// advanced choice) has its own tab.
export default function CompetingRisksResult({ result, name = null }) {
  const [tab, setTab] = useState("cif");
  const [stacked, setStacked] = useState(true);
  const tabs = [
    { id: "cif", label: "Cumulative incidence" },
    ...(result.regression ? [{ id: "coef", label: "Coefficients" }] : []),
  ];
  return (
    <>
      <div className="tabs">
        {tabs.map((t) => (
          <button key={t.id} className={"tab" + (tab === t.id ? " active" : "")} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>
      <div className="tab-panel">
        {tab === "cif" && (
          <div className="detail-panel life-panel">
            <div className="plotwrap">
              <CompetingRisksPlot result={result} unit={result.unit} stacked={stacked}
                                  download={`${name || "Failure modes"} — cumulative incidence`} />
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
            </div>
            <CompetingRisksAside result={result} />
          </div>
        )}
        {tab === "coef" && result.regression && <CoefficientsByMode regression={result.regression} />}
      </div>
      <ResultDetails>
        <p className="rs-note">
          {result.mode_bounds === false
            ? "Non-parametric cumulative incidence (Aalen-Johansen): no distribution is assumed. The chance "
              + "of failing from any mode has Kaplan-Meier 95% pointwise bounds; each mode's own curve is "
              + "shown without a band."
            : "Non-parametric cumulative incidence (Aalen-Johansen), with Aalen's 95% pointwise bounds: no "
              + "distribution is assumed."}{" "}
          A mode's curve is the chance of failing from it by each time while
          the other modes still act, so the curves add up to the chance of failing from any mode.
          {result.cause_column && ` Failure modes from “${result.cause_column}”; a blank mode is a unit still running.`}
        </p>
      </ResultDetails>
    </>
  );
}

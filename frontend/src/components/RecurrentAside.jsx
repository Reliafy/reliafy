import { useState } from "react";
import Modal from "./Modal.jsx";
import RecurrentStats from "./RecurrentStats.jsx";
import { openGuide } from "./HelpButton.jsx";
import { formatNumber } from "../format.js";
import { boundWords } from "../lifeResults.js";
import {
  ciText, dataText, familyOf, growthReading, orderedParams, paramLabel, pct, perUnit, ratioCiText, ratioText, repairTitle,
} from "../recurrentResults.js";

const sig = (v, n = 3) => formatNumber(v, { sig: n });

// The side panel beside a recurrent model's MCF plot (#65), as a life model's
// (#311): its parameters by their plain names with their intervals, the data
// and a row that opens the fit statistics; then the rates now (or, for
// imperfect repair, each system's next failure); then a quiet one-line
// reading of what the fit says.
export default function RecurrentAside({ r }) {
  const [statsOpen, setStatsOpen] = useState(false);
  const fam = familyOf(r);
  const unit = String(r.unit || "").trim().toLowerCase();
  const aic = (r.gof || []).find((g) => g.id === "aic") || (r.gof || [])[0];
  const hasStats = (r.gof || []).length > 0 || (r.trend_tests || []).length > 0 || (r.params || []).length > 0;
  const data = dataText(r);

  // Covariate models lead with the baseline's growth shape, then each
  // covariate's effect; the baseline scale is in the statistics.
  // (Duane's shape is its alpha; Cox-Lewis's trend is its slope beta.)
  const shapeName = r.baseline?.id === "duane" ? "alpha" : "beta";
  const params = orderedParams(r).filter((p) => fam !== "regression" || p.name === shapeName);
  const rest = r.restoration;

  let reading = null;
  if (fam === "renewal" && r.repair_test) {
    // The interval is beside the value above: the reading keeps to words.
    reading = { title: repairTitle(r.repair_test.verdict), text: <>{rest?.short || rest?.sentence} {r.repair_test.sentence}</> };
  } else if (fam === "renewal" && rest) {
    reading = { title: "Repair effectiveness", text: rest.sentence };
  } else {
    reading = growthReading(r);
  }

  return (
    <div className="aside rec-aside">
      <div className="gof-card">
        <div className="gofh life-card-head">
          <span>Parameters</span>
          <button type="button" className="link life-help" onClick={() => openGuide("recurrent-events")}>
            What do these mean?
          </button>
        </div>
        {rest && (
          <div className="gofr" title={`${rest.sentence} ${rest.scale || ""}`}>
            <span className="gk">{rest.ratio != null ? "Gap ratio" : "Repair effectiveness"}</span>
            <span className="gv-col">
              <span className="gv">{rest.ratio != null ? ratioText(rest.ratio) : pct(rest.effectiveness)}</span>
              {rest.ratio != null
                ? rest.ratio_ci && <span className="param-ci">95% {ciText(rest.ratio_ci, 3)}</span>
                : rest.effectiveness_ci &&
                  <span className="param-ci">95% {pct(rest.effectiveness_ci[0])}–{pct(rest.effectiveness_ci[1])}</span>}
            </span>
          </div>
        )}
        {params.filter((p) => !rest || p.name !== rest.parameter).map((p) => (
          <div className="gofr" key={p.name}>
            <span className="gk">{paramLabel(r, p.name)}</span>
            <span className="gv-col">
              <span className="gv">{sig(p.value)}</span>
              {p.ci && <span className="param-ci">95% {ciText(p.ci)}</span>}
            </span>
          </div>
        ))}
        {(r.coefficients || []).map((c) => (
          <div className="gofr" key={c.name} title={c.reading}>
            <span className="gk">{c.name.replace(": ", " ")}</span>
            <span className="gv-col">
              <span className="gv">{c.ratio != null ? `${ratioText(c.ratio)} rate` : "—"}</span>
              {c.ratio_ci && <span className="param-ci">95% {ratioCiText(c.ratio_ci)}</span>}
            </span>
          </div>
        ))}
        {data && (
          <div className="gofr">
            <span className="gk">Data</span>
            <span className="gv">{data}</span>
          </div>
        )}
        {hasStats && !r.from_params && (
          <button type="button" className="gofr gofr-link" onClick={() => setStatsOpen(true)}>
            <span className="gk">Fit statistics</span>
            <span className="gv">{aic ? `AIC ${formatNumber(aic.value, { sig: 5 })}` : "Tests"} ›</span>
          </button>
        )}
      </div>

      {fam !== "renewal" && r.mtbf != null && <NowCard r={r} unit={unit} />}
      {fam === "renewal" && r.next_failure?.units?.length > 0 && <NextCard nf={r.next_failure} unit={unit} />}

      {r.fit_warning && <div className="life-reading caveat">{r.fit_warning}</div>}
      {reading && (
        <div className="life-reading">
          <div className="life-reading-title">{reading.title}</div>
          <div>{reading.text}</div>
        </div>
      )}
      {r.windows && (
        <p className="life-method">
          Observed in {r.windows.windows} windows; {r.windows.systems_with_gaps} system
          {r.windows.systems_with_gaps === 1 ? " has" : "s have"} gaps ({formatNumber(r.windows.gap_time)}
          {unit ? ` ${unit}` : ""} unobserved).
        </p>
      )}
      {statsOpen && (
        <Modal title="Fit statistics" className="rec-stats-modal" onClose={() => setStatsOpen(false)}
               footer={<div className="row" style={{ margin: 0, marginLeft: "auto" }}>
                 <button onClick={() => setStatsOpen(false)}>Done</button></div>}>
          <RecurrentStats r={r} />
        </Modal>
      )}
    </div>
  );
}

// The failure rate and MTBF at the end of the data (for a covariate model,
// the fleet's average system), with the demonstrated MTBF's lower bound.
function NowCard({ r, unit }) {
  const at = r.end_of_observation ?? r.horizon;
  const dm = r.demonstrated_mtbf;
  const level = Math.round((dm?.confidence || 0.9) * 100);
  const fmtT = (v) => `${formatNumber(v)}${unit ? ` ${unit}` : ""}`;
  const mtbfTitle = [
    "MTBF now: 1 ÷ the failure rate at the end of the data",
    dm?.lower != null ? boundWords(level, "lower", dm.lower, null, fmtT) : null,
    r.mtbf_ci ? `95% interval ${ciText(r.mtbf_ci)}` : null,
  ].filter(Boolean).join(". ");
  return (
    <div className="gof-card life-card">
      <div className="gofh life-card-head">
        <span>{at != null ? `At ${formatNumber(at)}${unit ? ` ${unit}` : ""}` : "Now"}</span>
        {dm?.lower != null ? <span className="gof-sub">{level}% lower bound</span>
          : r.rates_at ? <span className="gof-sub">average system</span> : null}
      </div>
      <div className="gofr life-row" title={`${mtbfTitle}.`}>
        <span className="gk">MTBF{unit ? ` (${unit})` : ""}</span>
        <span className="gv">{sig(r.mtbf)}</span>
        <span className="life-lo">{dm?.lower != null ? `≥ ${sig(dm.lower)}` : ""}</span>
      </div>
      <div className="gofr life-row"
           title={r.rocof_ci ? `Failures per ${perUnit(unit) || "unit time"}. 95% interval ${ciText(r.rocof_ci)}.` : undefined}>
        <span className="gk">Failure rate</span>
        <span className="gv">{sig(r.rocof)}</span>
        <span className="life-lo">{unit ? `per ${perUnit(unit)}` : ""}</span>
      </div>
    </div>
  );
}

// Imperfect repair: the systems due soonest, by the median time to their
// next failure from where their history leaves them.
function NextCard({ nf, unit }) {
  const rows = nf.units.slice(0, 3);
  return (
    <div className="gof-card life-card">
      <div className="gofh life-card-head" title={unit ? `In ${unit} from now` : undefined}>
        <span>Next failure</span>
        <span className="gof-sub">median · 10% by</span>
      </div>
      {rows.map((u) => (
        <div className="gofr life-row" key={u.system}
             title={`${u.system}: ${u.failures} failures, ${formatNumber(u.since_failure)}${unit ? ` ${unit}` : ""} since the last. Half the chance of a failure within ${formatNumber(u.median)}; a 10% chance within ${formatNumber(u.b10)}.`}>
          <span className="gk">{u.system}</span>
          <span className="gv">{u.median != null ? sig(u.median) : "—"}</span>
          <span className="life-lo">{u.b10 != null ? sig(u.b10) : ""}</span>
        </div>
      ))}
    </div>
  );
}

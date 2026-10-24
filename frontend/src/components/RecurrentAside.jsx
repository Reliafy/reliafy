import { openGuide } from "./HelpButton.jsx";
import { formatNumber } from "../format.js";
import { boundWords } from "../lifeResults.js";
import { COLORWAY } from "../plotTheme.js";
import {
  ciText, dataText, familyOf, growthReading, paramLabel, pct, perUnit, ratioText, repairTitle,
} from "../recurrentResults.js";

const sig = (v, n = 3) => formatNumber(v, { sig: n });

// The panel beside a repairable model's mean cumulative function (the
// Failures over time tab), like a non-repairable model's: the failure rate and
// MTBF now (for imperfect repair, how much a repair restores and the systems
// due soonest), the model in words, and a card with the model, its data and
// links to its fit statistics (Diagnostics) and every parameter (Data).
export default function RecurrentAside({ r, onStats = null, onData = null, onNext = null }) {
  const fam = familyOf(r);
  const unit = String(r.unit || "").trim().toLowerCase();
  const aic = (r.gof || []).find((g) => g.id === "aic");
  const data = dataText(r);
  const rest = r.restoration;
  const b = r.growth_basis;
  const shape = b && (r.params || []).find((p) => p.name === b.parameter);

  let reading = null;
  if (fam === "renewal" && r.repair_test) {
    // "Partial repair" is the title, so the verdict's own lead-in goes.
    const verdict = r.repair_test.sentence.replace(/^Repairs are partial: b/, "B");
    reading = { title: repairTitle(r.repair_test.verdict), text: <>{rest?.short || rest?.sentence} {verdict}</> };
  } else if (fam === "renewal" && rest) {
    reading = { title: "Repair effectiveness", text: rest.sentence };
  } else {
    reading = growthReading(r);
  }

  return (
    <>
      {fam !== "renewal" && r.mtbf != null && <NowCard r={r} unit={unit} />}
      {fam === "renewal" && rest && <RepairCard rest={rest} />}
      {fam === "renewal" && r.next_failure?.units?.length > 0 && <NextCard nf={r.next_failure} unit={unit} onNext={onNext} />}

      {reading && (
        <div className="life-reading">
          <div className="life-reading-title">{reading.title}</div>
          <div>{reading.text}</div>
        </div>
      )}

      <div className="gof-card">
        <div className="gofh life-card-head">
          <span>Model</span>
          <button type="button" className="link life-help" onClick={() => openGuide("recurrent-events")}>
            What does this mean?
          </button>
        </div>
        <div className="gofr">
          <span className="gk">Model</span>
          <span className="gv">{fam === "regression" && r.baseline ? `${r.baseline.name} baseline` : r.model?.name || "—"}</span>
        </div>
        {shape && fam !== "renewal" && (
          <div className="gofr">
            <span className="gk">{paramLabel(r, shape.name)}</span>
            <span className="gv-col">
              <span className="gv">{sig(shape.value)}</span>
              {ciText(shape.ci) && <span className="param-ci">95% {ciText(shape.ci)}</span>}
            </span>
          </div>
        )}
        {data && (
          <div className="gofr"><span className="gk">Data</span><span className="gv">{data}</span></div>
        )}
        {onStats && (
          <button type="button" className="gofr gofr-link" onClick={onStats}>
            <span className="gk">Fit statistics</span>
            <span className="gv">{aic ? `AIC ${formatNumber(aic.value, { sig: 5 })}` : "Checks"} ›</span>
          </button>
        )}
        {onData && (
          <button type="button" className="gofr gofr-link" onClick={onData}>
            <span className="gk">Every parameter</span>
            <span className="gv">{(r.params || []).length + (r.coefficients || []).length} ›</span>
          </button>
        )}
      </div>
    </>
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
    ciText(r.mtbf_ci) ? `95% interval ${ciText(r.mtbf_ci)}` : null,
  ].filter(Boolean).join(". ");
  return (
    <div className="gof-card life-card">
      <div className="gofh life-card-head">
        <span>{r.from_params ? "At the horizon" : "Now"}</span>
        {at != null && <span className="gof-sub">at {formatNumber(at)}{unit ? ` ${unit}` : ""}{r.rates_at ? ", average system" : ""}</span>}
      </div>
      <div className="gofr life-row" title={`${mtbfTitle}.`}>
        <span className="gk">MTBF{unit ? ` (${unit})` : ""}</span>
        <span className="gv">{sig(r.mtbf)}</span>
        <span className="life-lo">
          {dm?.lower != null ? `≥ ${sig(dm.lower)} (${level}%)` : ciText(r.mtbf_ci) || ""}
        </span>
      </div>
      <div className="gofr life-row"
           title={ciText(r.rocof_ci) ? `Failures per ${perUnit(unit) || "unit time"}. 95% interval ${ciText(r.rocof_ci)}.` : undefined}>
        <span className="gk">Failure rate</span>
        <span className="gv">{sig(r.rocof)}</span>
        <span className="life-lo">{unit ? `per ${perUnit(unit)}` : ""}</span>
      </div>
    </div>
  );
}

// Imperfect repair: how much of the age a repair takes away (or, for G1, the
// gap ratio), with its interval.
function RepairCard({ rest }) {
  return (
    <div className="gof-card life-card">
      <div className="gofh life-card-head"><span>Each repair</span><span className="gof-sub">95% interval</span></div>
      <div className="gofr life-row" title={`${rest.sentence} ${rest.scale || ""}`}>
        <span className="gk">{rest.ratio != null ? "Gap ratio" : "Restores"}</span>
        <span className="gv">{rest.ratio != null ? ratioText(rest.ratio) : pct(rest.effectiveness)}</span>
        <span className="life-lo">
          {rest.ratio != null
            ? rest.ratio_ci && ciText(rest.ratio_ci, 3)
            : rest.effectiveness_ci && `${pct(rest.effectiveness_ci[0])}–${pct(rest.effectiveness_ci[1])}`}
        </span>
      </div>
    </div>
  );
}

// Imperfect repair: the two systems due soonest (every one under Plan ahead),
// by the median time to their next failure from where their history leaves them.
function NextCard({ nf, unit, onNext }) {
  const rows = nf.units.slice(0, 2);
  return (
    <div className="gof-card life-card">
      <div className="gofh life-card-head" title={unit ? `In ${unit} from now` : undefined}>
        <span>Next failure</span>
        <span className="gof-sub">{unit ? `${unit}: ` : ""}median · 10%</span>
      </div>
      {rows.map((u) => (
        <div className="gofr life-row" key={u.system}
             title={`${u.system}: ${u.failures} failures, ${formatNumber(u.since_failure)}${unit ? ` ${unit}` : ""} since the last. Half the chance of a failure within ${formatNumber(u.median)}; a 10% chance within ${formatNumber(u.b10)}.`}>
          <span className="gk">{u.system}</span>
          <span className="gv">{u.median != null ? sig(u.median) : "—"}</span>
          <span className="life-lo">{u.b10 != null ? sig(u.b10) : ""}</span>
        </div>
      ))}
      {onNext && nf.units.length > 2 && (
        <button type="button" className="gofr gofr-link" onClick={onNext}>
          <span className="gk">Every system</span><span className="gv">{nf.units.length} ›</span>
        </button>
      )}
    </div>
  );
}

// The By cause view's panel: each cause (choose one to see its 95% band), its
// failures and growth shape, and the chosen cause's reading.
export function CausesSide({ r, chosen, onChoose }) {
  const bc = r.by_cause || {};
  const causes = bc.causes || [];
  const current = causes.find((c) => c.label === chosen) || causes[0];
  const reading = current?.fit ? growthReading(current.fit) : null;
  return (
    <>
      <div className="gof-card">
        <div className="gofh life-card-head">
          <span>Causes</span>
          <span className="gof-sub">failures · shape β</span>
        </div>
        {causes.map((c, k) => (
          <button type="button" key={c.label}
                  className={"gofr rec-cause-row" + (c === current ? " on" : "")}
                  aria-pressed={c === current} onClick={() => onChoose(c.label)}>
            <span className="gk"><span className="rec-dot" style={{ background: COLORWAY[k % COLORWAY.length] }} />{c.label}</span>
            <span className="gv-col">
              <span className="gv">{c.failures} <span className="gof-sub">({pct(c.share)})</span></span>
              {c.fit && <span className="param-ci">β {formatNumber(c.fit.beta, { sig: 3 })}</span>}
            </span>
          </button>
        ))}
      </div>
      {current && reading && (
        <div className="life-reading">
          <div className="life-reading-title">{current.label}: {reading.title.toLowerCase()}</div>
          <div>{reading.text}</div>
        </div>
      )}
      <p className="life-method">
        {bc.model || "Crow-AMSAA per cause"}{bc.aic != null ? ` · AIC ${formatNumber(bc.aic, { sig: 5 })}` : ""}.
        {bc.note ? ` ${bc.note}` : ""} Choose a cause to see its 95% band.
      </p>
    </>
  );
}

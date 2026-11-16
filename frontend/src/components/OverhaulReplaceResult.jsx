import "./OverhaulReplace.css";
import Plot from "./Plot.jsx";
import ResultSummary, { ResultDetails } from "./ui/ResultSummary.jsx";
import { formatNumber, formatWithUnit } from "../format.js";
import { optimumMarker } from "../plotTheme.js";
import { unitInText } from "./unitText.js";
import { useCurrency } from "../WorkspaceProvider.jsx";
import { formatCostRate } from "../money.js";
import { savingWords } from "../overhaulReplace.js";

// An overhaul-and-replace answer (POST /api/strategy/overhaul-replace, or a saved analysis's
// stored results): the plan in a sentence, the cost rate against X for a few N, the comparisons,
// the best X for every N, then how it's worked out. Used by the live tool (Strategy page, the
// repairable model's Plan ahead tab, the Explorer's table pane) and the saved-analysis page.
export default function OverhaulReplaceResult({ result, name = null, actions = null, compact = false }) {
  const currency = useCurrency();
  const unit = result?.unit || "";
  const ut = unitInText(unit);
  const u = unit ? ` (${ut})` : "";
  const rate = (v) => (v == null ? "—" : formatCostRate(v, currency, unit, { sig: 4 }));
  const best = result?.best;

  if (!result?.pays || !best) {
    return (
      <>
        <ResultSummary tone="neutral" sentence={result?.sentence || "Repair it when it fails."}>
          {result?.reason}
        </ResultSummary>
        {actions && <div className="rs-actions">{actions}</div>}
      </>
    );
  }

  const cheaper = (result.comparisons || []).find((c) => c.id === result.cheaper) || null;
  const runner = (result.comparisons || []).find((c) => c.id === result.runner_up) || null;
  const traces = (result.curve?.series || []).map((s) => ({
    type: "scatter", mode: "lines", x: result.curve.t, y: s.cost_rate, connectgaps: false,
    name: s.overhauls === 0 ? "Replace only (N = 0)" : `N = ${s.overhauls}`,
    line: { width: s.overhauls === best.overhauls ? 3 : 1.5 },
  }));
  traces.push(optimumMarker({ x: [best.interval], y: [best.cost_rate], name: "Best plan",
                              text: [`X ${formatNumber(best.interval)}, N ${best.overhauls}`] }));
  const layout = {
    height: compact ? 300 : 380, showlegend: true,
    xaxis: { title: { text: `Overhaul interval X${u}` } },
    yaxis: { title: { text: `Long-run cost (${currency}) per ${ut ? ut.replace(/s$/, "") : "unit of time"}` },
             rangemode: "tozero", range: [0, best.cost_rate * 2.2] },
  };

  return (
    <>
      <ResultSummary
        tone={cheaper ? "caveat" : "good"}
        sentence={<><PlanWords best={best} ut={ut} />{runner && !cheaper && runner.saving_pct > 0.05
          ? <>. That costs <b>{formatNumber(runner.saving_pct, { sig: 2 })}%</b> less than the next best plan ({runner.label.toLowerCase()})</> : null}.</>}
        stats={[
          { label: "Overhaul every", value: best.overhauls ? formatWithUnit(best.interval, ut) : "—",
            hint: best.overhauls ? undefined : "Overhauls don't pay" },
          { label: "Replace after", value: best.overhauls ? `${best.overhauls} overhaul${best.overhauls === 1 ? "" : "s"}` : formatWithUnit(best.interval, ut),
            hint: `every ${formatWithUnit(best.replace_every, ut)}` },
          { label: "Cost rate", value: rate(best.cost_rate) },
          { label: "Repairs per replacement cycle", value: `≈ ${formatNumber(best.repairs_per_cycle)}` },
        ]}
      >
        {cheaper ? <>{cheaper.label} costs {formatNumber(-cheaper.saving_pct, { sig: 2 })}% less again: consider it, or search more overhauls.</> : null}
      </ResultSummary>
      {(result.warnings || []).filter((w) => !cheaper || !w.includes(cheaper.label)).map((w) => (
        <p key={w} className="hint" role="note">! {w}</p>
      ))}
      {actions && <div className="rs-actions">{actions}</div>}

      <Plot data={traces} layout={layout} download={`${name || "Overhaul and replace"} — cost rate`} />

      <h3 className="heading-xs or-h">Against the other plans</h3>
      <div className="maint-scroll or-scroll">
        <table className="or-table">
          <thead><tr><th scope="col">Plan</th><th scope="col">Interval{u}</th><th scope="col" className="num">Cost rate</th><th scope="col" className="num">Best plan saves</th></tr></thead>
          <tbody>
            <tr className="or-best"><th scope="row">This plan: {best.overhauls ? `overhaul every X, replace after ${best.overhauls}` : "replace every X"}</th>
              <td>{formatNumber(best.interval)}</td><td className="num">{rate(best.cost_rate)}</td><td className="num">—</td></tr>
            {(result.comparisons || []).map((c) => (
              <tr key={c.id}>
                <th scope="row">{c.label}{c.failure_count ? ` (at the ${ordinal(c.failure_count)} failure)` : ""}</th>
                <td>{c.interval != null ? formatNumber(c.interval) : "—"}</td>
                <td className="num">{c.cost_rate != null ? rate(c.cost_rate) : c.reason || "—"}</td>
                <td className="num">{savingWords(c.saving_pct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ResultDetails summary="The best X for each number of overhauls">
        <div className="maint-scroll or-scroll">
          <table className="or-table">
            <thead><tr><th scope="col">Overhauls before replacing (N)</th><th scope="col" className="num">Best X{u}</th><th scope="col" className="num">Replace every{u}</th><th scope="col" className="num">Cost rate</th></tr></thead>
            <tbody>
              {(result.by_overhauls || []).map((r) => (
                <tr key={r.overhauls} className={r.best ? "or-best" : undefined}>
                  <td>{r.overhauls}{r.best ? " · best" : ""}</td>
                  <td className="num">{r.interval != null ? formatNumber(r.interval) : "no limit"}</td>
                  <td className="num">{r.replace_every != null ? formatNumber(r.replace_every) : "—"}</td>
                  <td className="num">{rate(r.cost_rate)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </ResultDetails>
      <ResultDetails summary="How it's worked out">
        <p className="rs-note">
          For each number of overhauls N, the interval X with the lowest long-run cost per {ut ? ut.replace(/s$/, "") : "unit of time"} is
          found; the cheapest pair is the plan. A replacement cycle is N + 1 periods of X: the repairs expected over
          it (the unit ages through each period, and each overhaul takes off part of its age), N overhauls and one
          replacement, divided by its length. Exact, from the model's failure intensity (RePyability).
        </p>
        <ul className="rs-note">{(result.assumptions || []).map((a) => <li key={a}>{a}</li>)}</ul>
      </ResultDetails>
    </>
  );
}

// The plan in words, numbers in bold.
function PlanWords({ best, ut }) {
  if (!best.overhauls) return <>Replace every <b>{formatWithUnit(best.interval, ut)}</b>; overhauls don't pay</>;
  return (
    <>
      Overhaul every <b>{formatWithUnit(best.interval, ut)}</b> and replace the unit after{" "}
      <b>{best.overhauls} overhaul{best.overhauls === 1 ? "" : "s"}</b> (every {formatWithUnit(best.replace_every, ut)})
    </>
  );
}

const ordinal = (n) => {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return `${n}${s[(v - 20) % 10] || s[v] || s[0]}`;
};

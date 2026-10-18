import { useState } from "react";
import Plot from "./Plot.jsx";
import ResultSummary, { ResultDetails } from "./ui/ResultSummary.jsx";
import ScrollCue from "./ui/ScrollCue.jsx";
import { formatNumber, formatPercent } from "../format.js";
import { ACCENT, REFERENCE } from "../plotTheme.js";
import { unitInText } from "./unitText.js";
import { dearer, formatDate, visibleSchedule } from "../calendarReplacement.js";
import "./CalendarReplacement.css";

// The answer of replacement over a shutdown calendar: the rule in plain words
// and its cost a year first, then what simpler rules cost (a chart and a
// table), where the cost goes, and the next months' shuts by date.
export default function CalendarReplacementResult({ result, wt }) {
  const [showAll, setShowAll] = useState(false);
  const unit = unitInText(result.unit);
  const year = (v) => formatNumber(v, { sig: 3 });
  const se = result.cost_per_year_se;
  const rtf = result.savings_vs_run_to_failure;
  const age = result.savings_vs_age_rule;
  const used = (result.rule || []).filter((r) => r.used);
  const tone = used.length ? "good" : "caveat";

  const rules = [
    { label: "Best rule over the calendar", cost: result.cost_per_year, best: true },
    ...(result.comparisons || []).map((c) => ({ label: c.label, cost: c.cost_per_year, vs: c.vs_optimal })),
  ].filter((r) => r.cost != null);
  const chart = {
    data: [{
      type: "bar", orientation: "h",
      y: rules.map((r) => r.label), x: rules.map((r) => r.cost),
      marker: { color: rules.map((r) => (r.best ? ACCENT : REFERENCE)) },
      hovertemplate: "%{y}: %{x:,.4g} a year<extra></extra>",
    }],
    layout: {
      height: 90 + 34 * rules.length,
      margin: { l: 10, r: 20, t: 10, b: 40 },
      xaxis: { title: { text: "Long-run cost a year" }, rangemode: "tozero" },
      yaxis: { automargin: true, autorange: "reversed" },
      showlegend: false,
    },
  };
  const schedule = visibleSchedule(result.schedule, showAll, used.map((r) => r.kind));
  const hidden = (result.schedule || []).length - schedule.length;

  return (
    <>
      <ResultSummary
        tone={tone}
        wt={wt}
        sentence={result.recommendation}
        stats={[
          { label: "Cost a year", value: se ? `${year(result.cost_per_year)} ± ${year(se)}` : year(result.cost_per_year),
            hint: "long-run average" },
          rtf != null && rtf > 0 && { label: "vs run to failure", value: `−${formatPercent(rtf)}` },
          age != null && { label: "vs age replacement", value: age > 0 ? `−${formatPercent(age)}` : "no saving",
                           hint: result.age_rule ? `at ${formatNumber(result.age_rule.age)} ${unit}` : undefined },
        ]}
      >
        Today ({formatDate(result.today)}) is time 0. {result.method_label}.
      </ResultSummary>

      <section className="cal-block" data-testid="calendar-rule">
        <h3>The rule</h3>
        <ul className="cal-rule">
          {(result.rule || []).map((r) => (
            <li key={r.kind} className={r.used ? "" : "cal-unused"}>{r.text}</li>
          ))}
        </ul>
      </section>

      <section className="cal-block">
        <h3>Against simpler rules</h3>
        <Plot data={chart.data} layout={chart.layout} download="Calendar replacement — cost a year by rule" />
        <ScrollCue className="table-scroll">
          <table className="mini-table">
            <thead><tr><th>Rule</th><th>Cost a year</th><th>Against the best</th></tr></thead>
            <tbody>
              {rules.map((r) => (
                <tr key={r.label}>
                  <td>{r.best ? <b>{r.label}</b> : r.label}</td>
                  <td>{year(r.cost)}</td>
                  <td>{r.best ? "—" : dearer(r.vs)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollCue>
      </section>

      <section className="cal-block">
        <h3>Where the cost goes</h3>
        <ScrollCue className="table-scroll">
          <table className="mini-table">
            <thead><tr><th>Replaced</th><th>Price</th><th>Replacements a year</th><th>Cost a year</th><th>Share</th></tr></thead>
            <tbody>
              {(result.by_kind || []).map((k) => (
                <tr key={k.kind}>
                  <td>{k.kind === "failure" || k.kind === "anytime" ? k.label : `At the ${k.label}`}</td>
                  <td>{formatNumber(k.price)}</td>
                  <td>{formatNumber(k.replacements_per_year, { sig: 3 })}</td>
                  <td>{year(k.cost_per_year)}</td>
                  <td>{k.share == null ? "—" : formatPercent(k.share)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollCue>
      </section>

      {(result.schedule || []).length > 0 && (
        <section className="cal-block" data-testid="calendar-schedule">
          <h3>The next {result.horizon_months} months</h3>
          <p className="muted-line">
            At each shut, replace the part if it's older than the age shown. The chance is how often that happens
            in the long run.
          </p>
          <ScrollCue className="table-scroll">
            <table className="mini-table">
              <thead><tr><th>Date</th><th>Shut</th><th>Price</th><th>Replace if older than</th><th>Chance</th></tr></thead>
              <tbody>
                {schedule.map((r) => (
                  <tr key={`${r.date}-${r.kind}`}>
                    <td>{formatDate(r.date)}</td>
                    <td>{r.kind}</td>
                    <td>{formatNumber(r.price)}</td>
                    <td>{r.threshold == null ? "never" : `${formatNumber(r.threshold)} ${unit}`}</td>
                    <td>{r.chance == null ? "—" : formatPercent(r.chance)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollCue>
          {(hidden > 0 || showAll) && (
            <button type="button" className="link sm" onClick={() => setShowAll((v) => !v)}>
              {showAll ? "Show only the likely replacements" : `Show every shut (${hidden} more)`}
            </button>
          )}
        </section>
      )}

      {(result.notes || []).map((n, i) => <div key={i} className="calc-warn">{n}</div>)}

      <ResultDetails
        summary="How the dates became model time"
        rows={[
          { label: "Today (time 0)", value: formatDate(result.today) },
          { label: "Model time unit", value: result.unit },
          { label: "Long-run cost per unit time", value: formatNumber(result.cost_rate, { sig: 4 }) },
          result.step != null && { label: `Grid step (${unit})`, value: formatNumber(result.step, { sig: 4 }) },
          result.period != null && { label: `Pattern repeats every (${unit})`, value: formatNumber(result.period, { sig: 6 }) },
          result.determined_until_date && { label: "Shown dates hold until", value: formatDate(result.determined_until_date) },
          result.mc_samples && { label: "Samples", value: result.mc_samples },
        ]}
      >
        <p className="rs-note">{result.convention}</p>
        <ul className="cal-rule">
          {(result.opportunities || []).map((o) => (
            <li key={o.name}>
              <b>{o.name}</b>{" "}
              {o.kind === "dates"
                ? `on ${o.dates.map(formatDate).join(", ")}: model times ${o.times.map((t) => formatNumber(t, { sig: 5 })).join(", ")} ${unit}`
                : `every ${formatNumber(o.every)} ${o.every_unit} from ${formatDate(o.start)}: every ${formatNumber(o.period, { sig: 6 })} ${unit}, one at ${formatNumber(o.offset, { sig: 6 })} ${unit}`}
            </li>
          ))}
        </ul>
      </ResultDetails>
    </>
  );
}

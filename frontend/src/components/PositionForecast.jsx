import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getPositionForecast } from "../api.js";
import { plannedTitle, promptGroups } from "../failureCosts.js";
import { formatChance } from "../format.js";
import {
  besidesRoutine, costRangeText, datesText, dayText, everyText, failuresText, hoursText, moneyText, periodLabel, restsOn, sig,
} from "../positionForecast.js";
import { ShowMe } from "./SectionPage.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import { tabPlace } from "../explorerTabs.js";
import ResultSummary, { ResultDetails } from "./ui/ResultSummary.jsx";
import "./PositionForecast.css";

// The Maintenance tab's Forecast view (?mview=forecast): the position and everything inside it,
// inside the asset opened (?root=). The answer first ("To 30 Nov 2027: 58 tasks …; 0.62 failures
// expected (0 to 1, 90% range), about $2,990"), then where the hours come from, anything missing
// said plainly with what to do, and a period-by-period table (scrolls inside its card at phone
// width). Each column's heading and cells say what they rest on; the folds below list the tasks on
// dates, the life models used and what was left out. Worked out on read by the server
// (backend/maintenance/position_forecast.py, on RePyability's schedule module); nothing is saved.
//
//   positionId, name: the row opened      root: the asset opened (nothing above it is used)
//   bar: the Tasks / Forecast switch, shown in the view's own bar
//
// Built from the design system's shared parts: the answer is a ResultSummary (amber with "!" when
// something is missing), the folds are ResultDetails; spacing and colour are tokens.

const PERIODS = [
  { value: "month", label: "Months", periods: 12 },
  { value: "quarter", label: "Quarters", periods: 4 },
  { value: "year", label: "Years", periods: 5 },
];

// The answer's numbers in bold, after its date ("To 30 Nov 2027: **58** tasks, about **46** labour
// hours …"), as the design system's result sentences have them.
function boldNumbers(text) {
  const s = String(text);
  const at = s.indexOf(": ");
  const head = at < 0 ? "" : s.slice(0, at + 2);
  const parts = s.slice(head.length).split(/(\$?\d[\d,]*(?:\.\d+)?%?)/);
  return [head, ...parts.map((part, i) => (i % 2 ? <b key={i}>{part}</b> : part))];
}

// Planned plus unplanned; with a failure forecast at no cost, the planned alone and "+ ?" (it isn't the whole cost).
function totalText(r, totals) {
  if (r.total_cost == null) return "—";
  return totals.total_complete === false && totals.failures ? `${moneyText(r.total_cost)} + ?` : moneyText(r.total_cost);
}

// The "Cost by kind" fold's rows: [label, amount, what it rests on].
function costRows(fc) {
  const t = fc.totals;
  const rows = [
    ["Labour", moneyText(t.labour_cost), "Each task's LSA labour at the trade rates, × the times it's due"],
    ["Parts and consumables", moneyText(t.materials_cost), "Each task's LSA spares and consumables, × the times it's due"],
  ];
  if (t.other_planned_cost) rows.push(["Other planned", moneyText(t.other_planned_cost), "A task's typed cost beyond what its LSA prices"]);
  rows.push(["Planned in all", moneyText(t.planned_cost), fc.cost_basis?.planned || ""]);
  rows.push(["Unplanned (failures)", t.failure_cost == null ? "—" : moneyText(t.failure_cost), fc.cost_basis?.unplanned || ""]);
  if (t.downtime_hours != null) {
    rows.push(["Of which downtime", t.downtime_cost == null ? "—" : moneyText(t.downtime_cost),
      `${hoursText(t.downtime_hours)} out of use expected, at each failure's cost of an hour down`]);
  }
  rows.push(["Total", totalText(t, t), t.total_complete === false ? "Some failures forecast have no failure cost: see What to enter." : "Planned plus unplanned"]);
  return rows;
}

export default function PositionForecast({ positionId, name, root = null, bar = null }) {
  const [period, setPeriod] = useState("month");
  const [state, setState] = useState({ key: null, data: null, error: null });
  const key = `${positionId}:${root || ""}:${period}`;
  useEffect(() => {
    let live = true;
    const { periods } = PERIODS.find((p) => p.value === period);
    getPositionForecast(positionId, { root, period, periods })
      .then((data) => live && setState({ key, data, error: null }))
      .catch((e) => live && setState({ key, data: null, error: e.message }));
    return () => { live = false; };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  const fc = state.key === key ? state.data : null;
  const error = state.key === key ? state.error : null;
  const word = PERIODS.find((p) => p.value === period).label.replace(/s$/, "");
  const downtime = fc?.totals?.downtime_hours != null;
  const groups = fc ? promptGroups(fc.prompts) : [];

  return (
    <section className="fc-view" aria-label="Forecast">
      <div className="pk-bar fc-bar">
        <SegmentedControl size="sm" label="By" value={period} onChange={setPeriod}
                          options={PERIODS.map((p) => ({ value: p.value, label: p.label }))} />
        <ShowMe help={{ guide: "forecast-the-maintenance-plan" }} asHelp />
        {bar}
      </div>
      {error && <div className="card error">Couldn&apos;t work out the forecast: {error}</div>}
      {!fc && !error && <div className="card empty">Working out the forecast…</div>}
      {fc && (
        <>
          <ResultSummary className="fc-summary" tone={fc.states.length > 0 ? "caveat" : "neutral"} sentence={boldNumbers(fc.answer)}>
            For {fc.covers || name}, from today ({dayText(fc.start)}) to {dayText(fc.end)}. {fc.hours_basis ? `${fc.hours_basis}.` : ""}{" "}
            Ranges are 90% of outcomes (the 5th to 95th percentile).
          </ResultSummary>
          {fc.states.length > 0 && (
            <ul className="fc-states" aria-label="What's missing">
              {fc.states.map((s, i) => (
                <li key={i} className={`fc-state fc-${s.kind}`}><span className="fc-state-icon" aria-hidden="true">!</span>{s.text}</li>
              ))}
            </ul>
          )}
          {groups.length > 0 && (
            <ResultDetails summary={`What to enter (${groups.reduce((t, g) => t + g.items.length, 0)})`} open>
              {groups.map((g) => (
                <section key={g.id} className="fc-enter-group" aria-label={g.title}>
                  <h3 className="fc-enter-title">{g.title}</h3>
                  <p className="lib-date">{g.lead}</p>
                  <ul className="td-rows fc-list">
                    {g.items.map((x) => (
                      <li key={x.key}>
                        <strong>{x.name}</strong> <span className="lib-date">· {x.where}</span>
                        {x.link && <> · <Link to={x.link}>{x.action}</Link></>}
                        <div className="lib-date">{x.why}</div>
                      </li>
                    ))}
                  </ul>
                </section>
              ))}
            </ResultDetails>
          )}
          <div className="maint-scroll fc-scroll">
            <table className="lib-table fc-table">
              <caption className="sr-only">The forecast by {word.toLowerCase()}</caption>
              <thead>
                <tr>
                  <th scope="col">{word}</th>
                  <th scope="col" className="num" title={restsOn(fc, "hours")}>Operating hours</th>
                  <th scope="col" className="num" title={restsOn(fc, "work")}>Tasks</th>
                  <th scope="col" className="num" title={restsOn(fc, "work")}>Labour hours</th>
                  <th scope="col" className="num" title={fc.cost_basis?.planned || restsOn(fc, "work")}>Planned cost</th>
                  <th scope="col" className="num" title={restsOn(fc, "failures")}>Expected failures</th>
                  <th scope="col" className="num" title={fc.cost_basis?.unplanned || restsOn(fc, "failures")}>Unplanned cost</th>
                  {downtime && <th scope="col" className="num" title="Expected failures × the hours each keeps it out of use">Downtime</th>}
                  <th scope="col" className="num" title="Planned plus unplanned">Total cost</th>
                  <th scope="col">Besides the routine</th>
                </tr>
              </thead>
              <tbody>
                {fc.rows.map((r, i) => {
                  const besides = besidesRoutine(r, fc.tasks);
                  return (
                    <tr key={r.start}>
                      <th scope="row">{periodLabel(r, fc.period, i === 0)}</th>
                      <td className="num" title={restsOn(fc, "hours")}>{hoursText(r.hours)}</td>
                      <td className="num">{r.tasks}</td>
                      <td className="num">{r.labour_hours ? hoursText(r.labour_hours) : "—"}</td>
                      <td className="num" title={plannedTitle(r) || undefined}>{r.planned_cost ? moneyText(r.planned_cost) : "—"}</td>
                      <td className="num" title={restsOn(fc, "failures")}>{failuresText(r.failures, r.failures_range)}</td>
                      <td className="num" title={restsOn(fc, "failures")}>{costRangeText(r.failure_cost, r.cost_range)}</td>
                      {downtime && <td className="num">{hoursText(r.downtime_hours)}</td>}
                      <td className="num">{totalText(r, fc.totals)}</td>
                      <td className="fc-besides">{besides.length ? besides.join(", ") : <span className="lib-date">—</span>}</td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot>
                <tr>
                  <th scope="row">In all</th>
                  <td className="num">{fc.rows.some((r) => r.hours != null) ? hoursText(fc.rows.reduce((t, r) => t + (r.hours || 0), 0)) : "—"}</td>
                  <td className="num">{fc.totals.tasks}</td>
                  <td className="num">{fc.totals.labour_hours ? hoursText(fc.totals.labour_hours) : "—"}</td>
                  <td className="num" title={plannedTitle(fc.totals) || undefined}>{fc.totals.planned_cost ? moneyText(fc.totals.planned_cost) : "—"}</td>
                  <td className="num">{failuresText(fc.totals.failures, fc.totals.failures_range)}</td>
                  <td className="num">{costRangeText(fc.totals.failure_cost, fc.totals.cost_range)}</td>
                  {downtime && <td className="num">{hoursText(fc.totals.downtime_hours)}</td>}
                  <td className="num">{totalText(fc.totals, fc.totals)}</td>
                  <td>{fc.totals.probability != null ? `${formatChance(fc.totals.probability)} chance of at least one failure` : ""}</td>
                </tr>
              </tfoot>
            </table>
          </div>
          <ResultDetails summary={`Tasks on dates (${fc.tasks.length})`} open={fc.tasks.length > 0 && fc.tasks.length <= 6}>
            {fc.tasks.length === 0 ? <p className="lib-date">No tasks with dates here or inside it.</p> : (
              <ul className="td-rows fc-list">
                {fc.tasks.map((t) => (
                  <li key={t.id}>
                    <strong>{t.name}</strong>
                    {fc.by_position.length > 1 && <span className="lib-date"> · {t.position.name}</span>}
                    <span className="lib-date"> · {everyText(t.how_often)}</span>
                    <div>{t.overdue ? "Overdue: done first, then " : ""}{datesText(t.dates)}
                      {t.by_use && t.moments.length > 0 && t.moments[0] && <span className="lib-date"> (the meter reaches it at {t.moments[0].slice(11)} on the first)</span>}
                    </div>
                    <div className="lib-date">{t.rests_on}{t.cost_each != null ? ` · ${moneyText(t.cost_each)} each time` : ""}</div>
                    {t.notes.map((n, i) => <div key={i} className="lib-date">{n}</div>)}
                  </li>
                ))}
              </ul>
            )}
          </ResultDetails>
          <ResultDetails summary={`Failures: the life models used (${fc.models.length})`} open={fc.models.length > 0 && fc.models.length <= 3}>
            {fc.models.length === 0 && <p className="lib-date">No life model in use on a position here with an item fitted. Attach one in {tabPlace("models")}.</p>}
            <ul className="td-rows fc-list">
              {fc.models.map((m) => (
                <li key={m.link_id}>
                  <strong>{m.position.name}</strong>: {m.name}
                  {m.placeholder && <span className="fc-flag-word"> · placeholder</span>}
                  <div>{failuresText(m.expected_failures, m.failures_range)} failures expected
                    {m.expected_cost != null ? `, ${costRangeText(m.expected_cost, m.cost_range)}` : ""}
                    {m.probability != null ? ` · ${formatChance(m.probability)} chance of at least one` : ""}
                  </div>
                  <div className="lib-date">{m.rests_on}</div>
                </li>
              ))}
            </ul>
          </ResultDetails>
          {fc.by_position.length > 1 && (
            <ResultDetails summary={`By position (${fc.by_position.length})`}>
              <div className="maint-scroll">
                <table className="lib-table fc-table">
                  <thead>
                    <tr><th scope="col">Position</th><th scope="col" className="num">Tasks</th><th scope="col" className="num">Labour hours</th>
                      <th scope="col" className="num">Planned cost</th><th scope="col" className="num">Expected failures</th><th scope="col" className="num">Unplanned cost</th></tr>
                  </thead>
                  <tbody>
                    {fc.by_position.map((p) => (
                      <tr key={p.position.id}>
                        <th scope="row" style={{ "--fc-depth": p.depth }} className="fc-depth" title={p.hours_basis || undefined}>{p.position.name}</th>
                        <td className="num">{p.tasks}</td>
                        <td className="num">{p.labour_hours ? hoursText(p.labour_hours) : "—"}</td>
                        <td className="num">{p.planned_cost ? moneyText(p.planned_cost) : "—"}</td>
                        <td className="num">{p.failures ? sig(p.failures, 2) : "—"}</td>
                        <td className="num">{p.failure_cost ? moneyText(p.failure_cost) : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </ResultDetails>
          )}
          {(fc.not_on_dates.length > 0 || fc.not_forecast.length > 0) && (
            <ResultDetails summary={`Left out (${fc.not_on_dates.length + fc.not_forecast.length})`}>
              <ul className="td-rows fc-list">
                {fc.not_on_dates.map((x) => (
                  <li key={`t-${x.task.id}`}><strong>{x.task.name}</strong> <span className="lib-date">· {x.position.name}</span><div className="lib-date">Not on dates: {x.reason}.</div></li>
                ))}
                {fc.not_forecast.map((x) => (
                  <li key={`m-${x.link_id}-${x.position.id}`}><strong>{x.position.name}</strong>: {x.name}<div className="lib-date">Failures not forecast: {x.reason}.</div></li>
                ))}
              </ul>
            </ResultDetails>
          )}
          <ResultDetails summary="Cost by kind">
            <div className="maint-scroll">
              <table className="lib-table fc-table">
                <caption className="sr-only">The cost to {dayText(fc.end)} by kind</caption>
                <tbody>
                  {costRows(fc).map(([label, value, basis]) => (
                    <tr key={label}><th scope="row">{label}</th><td className="num">{value}</td><td className="lib-date">{basis}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </ResultDetails>
          {fc.notes.length > 0 && <ul className="lib-date fc-notes">{fc.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
        </>
      )}
    </section>
  );
}

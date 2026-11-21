import { useEffect, useState } from "react";
import { getSparesYear, getSparesYearCsv } from "../api.js";
import { formatNumber } from "../format.js";
import { saveBlob } from "../sparesPlan.js";
import { countIsOld, countedText, dayText, demandText, holdBasis, orderLines, splitText } from "../sparesYear.js";
import ResultSummary, { ResultDetails } from "./ui/ResultSummary.jsx";
import "./SparesYear.css";
import { ShowMe } from "./SectionPage.jsx";

// Spares for the year: one row per part that a failure or a task uses, here and inside it, worked out
// on read by the server (backend/maintenance/spares_year.py; maintenance get.spares_year over MCP).
// The Explorer's Maintenance › Spares on a position or location (inside the asset opened, `root`), and
// on a product's design (the items built from it, or a planned fleet when none is built yet: the
// sizes are asked for here). The answer first, then the table (it scrolls inside its card at phone
// width), the rule it follows, and what couldn't be counted. Quantities and dates only: costing and
// orders are your own systems, so the CSV is plain numbers for a spreadsheet.
//
//   id: the row (position, location, or a design position)   root: the asset opened   name: its name
//   design: a product's design row (asks for a planned fleet when nothing is built)   bar: the view switch
//
// Built from the design system's shared parts: ResultSummary for the answer, ResultDetails for the
// folds; the table is the app's lib-table inside maint-scroll.

function headline(data) {
  const parts = data.parts || [];
  const order = parts.filter((r) => r.order_now > 0);
  const old = parts.filter((r) => countIsOld(r, data.today));
  const bits = [<span key="n"><b>{parts.length}</b> part{parts.length === 1 ? "" : "s"} over the next {data.months} months</span>];
  if (order.length) {
    bits.push(<span key="o">; order now: {order.map((r, i) => (
      <span key={r.part.id}>{i ? ", " : ""}<b>{formatNumber(r.order_now)}</b> {r.part.part_number}</span>))}</span>);
  } else if (parts.length) {
    bits.push(<span key="o">; nothing to order today</span>);
  }
  if (old.length) bits.push(<span key="c">; {old.length} not counted in the last 12 weeks</span>);
  return [...bits, "."];
}

// Where a part is used: "HLP-01 seal, HLP-02 seal and 4 more".
function usedAt(r) {
  const all = [...new Set([...r.positions.failures, ...r.positions.planned])];
  return all.length > 2 ? `${all.slice(0, 2).join(", ")} and ${all.length - 2} more` : all.join(" and ");
}

export default function SparesYear({ id, root = null, name = "", design = false, bar = null }) {
  const [fleet, setFleet] = useState({ size: "", hours: "" });
  const [asked, setAsked] = useState({ size: "", hours: "" });
  const [state, setState] = useState({ key: null, data: null, error: null });
  const [busy, setBusy] = useState(false);
  const key = `${id}:${root || ""}:${asked.size}:${asked.hours}`;
  useEffect(() => {
    let live = true;
    getSparesYear({ id, root, fleetSize: asked.size || null, hoursPerDay: asked.hours || null })
      .then((data) => live && setState({ key, data, error: null }))
      .catch((e) => live && setState({ key, data: null, error: e.message }));
    return () => { live = false; };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  const data = state.key === key ? state.data : null;
  const error = state.key === key ? state.error : null;
  const unbuilt = design && data && data.of && data.of.built === 0;
  const exportCsv = async () => {
    setBusy(true);
    try {
      const blob = await getSparesYearCsv({ id, root, fleetSize: asked.size || null, hoursPerDay: asked.hours || null });
      saveBlob(blob, `${String(name || "spares").replace(/[^\w\- ]+/g, "").trim() || "spares"} — spares for the year.csv`);
    } catch (e) {
      setState((s) => ({ ...s, error: e.message }));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="fc-view sy-view" aria-label="Spares for the year" data-testid="spares-year">
      <div className="pk-bar fc-bar">
        <span className="lib-date">
          {design ? "The parts the items built from this design will use." : "Every part a failure or a task uses here and inside it."}
        </span>
        <ShowMe help={{ guide: "spares-for-the-year" }} asHelp />
        {bar}
      </div>
      {unbuilt && (
        <form className="sy-fleet" onSubmit={(e) => { e.preventDefault(); setAsked(fleet); }}>
          <label className="login-field">
            <span>Planned fleet size</span>
            <input type="number" inputMode="numeric" min="1" step="1" value={fleet.size} placeholder="e.g. 5"
                   onChange={(e) => setFleet({ ...fleet, size: e.target.value })} />
          </label>
          <label className="login-field">
            <span>Hours a day each (lives by use)</span>
            <input type="number" inputMode="decimal" min="0" max="24" step="any" value={fleet.hours} placeholder="e.g. 24"
                   onChange={(e) => setFleet({ ...fleet, hours: e.target.value })} />
          </label>
          <button type="submit" className="secondary">Work it out</button>
        </form>
      )}
      {error && <div className="card error">Couldn&apos;t work out the spares: {error}</div>}
      {!data && !error && <div className="card empty">Working out the spares…</div>}
      {data && unbuilt && !data.fleet_size && (
        <p className="lib-date">Nothing is built from it yet. Say how many you plan to build to size their spares, each new today.</p>
      )}
      {data && !(unbuilt && !data.fleet_size) && (
        <>
          <ResultSummary className="fc-summary" tone={(data.parts || []).some((r) => r.order_now > 0) ? "caveat" : "neutral"}
                         sentence={headline(data)}>
            For {data.of?.name || name}{data.fleet_size ? ` (a planned fleet of ${data.fleet_size})` : ""}, from today
            ({dayText(data.today)}) to {dayText(data.end)}. Each part&apos;s stock to hold covers its lead time at its
            service level; quantities only, for your own budget and purchasing.
          </ResultSummary>
          {(data.parts || []).length === 0 ? (
            <div className="card empty">
              <p>No part is used here yet. Put parts on the positions&apos; parts lists (what replaces each item) or name
                the spares each task uses in What it needs; failures and planned jobs then count against them.</p>
            </div>
          ) : (
            <div className="maint-scroll fc-scroll">
              <table className="lib-table sy-table">
                <thead>
                  <tr>
                    <th scope="col">Part</th>
                    <th scope="col">Needed over {data.months} months</th>
                    <th scope="col">Hold</th>
                    <th scope="col">Usable now</th>
                    <th scope="col">Order</th>
                    <th scope="col">Buy for the year</th>
                  </tr>
                </thead>
                <tbody>
                  {data.parts.map((r) => {
                    const lines = orderLines(r);
                    return (
                      <tr key={r.part.id} title={r.summary}>
                        <td>
                          <b>{r.part.part_number}</b> {r.part.name}
                          {r.critical && <span className="lib-date"> · critical</span>}
                          <div className="lib-date">{usedAt(r)}</div>
                        </td>
                        <td className="num">{demandText(r.demand)}<div className="lib-date">{splitText(r.demand)}</div></td>
                        <td className="num"><b>{formatNumber(r.hold)}</b><div className="lib-date">{holdBasis(r)}</div></td>
                        <td className="num">{formatNumber(r.usable_now)}
                          <div className={countIsOld(r, data.today) ? "maint-overdue" : "lib-date"}>
                            {countIsOld(r, data.today) ? "! " : ""}{countedText(r, data.today)}</div></td>
                        <td>{lines.length ? lines.map((l) => <div key={l}>{l}</div>) : <span className="lib-date">nothing yet</span>}
                          {r.reorder_at != null && r.hold > 0 && <div className="lib-date">then one for one</div>}</td>
                        <td className="num"><b>{formatNumber(r.buy_for_year)}</b>
                          <div className="lib-date">high case {formatNumber(r.buy_high_case)}</div></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <div className="maint-row" style={{ flexWrap: "wrap", gap: "0.5rem" }}>
            <button type="button" className="secondary" onClick={exportCsv} disabled={busy || !(data.parts || []).length}>
              Export spares for the year (CSV)
            </button>
          </div>
          <ResultDetails summary="How it's worked out" rows={[]}>
            <p className="lib-date">{data.rule} The high case puts the demand&apos;s 90th percentile in place of the
              expected. A shutdown task done only on an older item counts at its chance of being done. Stock to hold is
              read off {formatNumber(data.sims)} simulated runs.</p>
            <ul className="lib-date">{(data.notes || []).map((n) => <li key={n}>{n}</li>)}</ul>
          </ResultDetails>
          {(data.parts || []).some((r) => r.jobs?.length) && (
            <ResultDetails summary="Planned jobs that use these parts">
              <div className="maint-scroll">
                <table className="lib-table">
                  <thead><tr><th scope="col">Date</th><th scope="col">Part</th><th scope="col">Job</th><th scope="col">Where</th><th scope="col">Chance it&apos;s done</th></tr></thead>
                  <tbody>
                    {data.parts.flatMap((r) => (r.jobs || []).map((j, i) => (
                      <tr key={`${r.part.id}-${i}`}>
                        <td>{dayText(j.date)}</td><td>{r.part.part_number} × {formatNumber(j.qty)}</td><td>{j.label}</td>
                        <td>{j.unit}{j.package ? <span className="lib-date"> · {j.package.name}</span> : null}</td>
                        <td className="num">{j.chance >= 0.995 ? "certain" : j.chance <= 0.005 ? "skipped (too young)" : `${Math.round(j.chance * 100)}%`}</td>
                      </tr>
                    )))}
                  </tbody>
                </table>
              </div>
            </ResultDetails>
          )}
          {(data.not_forecast.length > 0 || data.not_dated.length > 0) && (
            <ResultDetails summary="Not counted" open>
              <ul className="lib-date">
                {data.not_forecast.map((x) => <li key={`f-${x.position.id}`}>{x.position.name}: failures not counted ({x.reason}).</li>)}
                {data.not_dated.map((x) => <li key={`d-${x.task.id}`}>{x.position.name}, {x.task.name}: not put on dates ({x.reason}).</li>)}
              </ul>
            </ResultDetails>
          )}
        </>
      )}
    </section>
  );
}

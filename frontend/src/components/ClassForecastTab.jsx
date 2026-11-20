import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { getClassForecast } from "../api.js";
import { formatNumber, formatPercent } from "../format.js";
import { classForecastGroups, horizonText, scopedForecast } from "../maintenanceForecast.js";
import ResultSummary from "./ui/ResultSummary.jsx";

// An item class's Forecast and Spares tabs, beside the Explorer's tree arranged by Classes.
// A forecast is a position class's (its fitted life model, from its own history: the
// class forecast, GET /api/maintenance/classes/forecast), so both tabs work through the
// position classes of this class's positions in the tree on show (an asset opened: its own).
//
// Forecast: the failures expected at this class's positions, added up from each position's
// own expected failures (expectations add), with each position as a row and the ones that
// can't be forecast said with why. Nothing from positions outside the tree on show.
// Spares: the class page's spares card (MaintenanceLists ForecastCard, show "spares") for each
// position class. Stock is shared across the register, so the demand is the position class's
// and the card says so.

const ForecastCard = lazy(() => import("../views/MaintenanceLists.jsx").then((m) => ({ default: m.ForecastCard })));
const loading = <p className="hint">Loading…</p>;
const forecastsPath = (key) => `/forecasts?class=${encodeURIComponent(key)}`;

// The positions not forecast, one line per reason: [[reason, names]].
function byReason(missing) {
  const out = new Map();
  for (const m of missing) {
    const r = /[.!?]$/.test(m.reason) ? m.reason : `${m.reason.charAt(0).toUpperCase()}${m.reason.slice(1)}.`;
    if (!out.has(r)) out.set(r, []);
    out.get(r).push(m.position.name || "(no name)");
  }
  return [...out];
}

function useGroups(display, row) {
  return useMemo(() => classForecastGroups(display, row), [display, row]);
}

export function ClassForecastTab({ row, display, onSelect }) {
  const { groups, none, count } = useGroups(display, row);
  const [reads, setReads] = useState({});
  const keys = groups.map((g) => g.key).join("\n");
  useEffect(() => {
    let live = true;
    setReads({});
    for (const key of keys ? keys.split("\n") : []) {
      getClassForecast(key)
        .then((f) => live && setReads((s) => ({ ...s, [key]: f })))
        // The reason in words ("Fit a non-repairable model for … first"), without a tool's name after it.
        .catch((e) => live && setReads((s) => ({ ...s, [key]: { error: String(e?.message || "").replace(/\s*\((maintenance|get|list|analyse|change) [^)]*\)\.?$/, ".") || true } })));
    }
    return () => { live = false; };
  }, [keys]);
  const f = scopedForecast(groups, reads);
  const name = row.ref?.name || "this class";

  if (!count) return <p className="hint">No position here has an item of this class fitted.</p>;
  if (!groups.length) {
    return (
      <p className="hint">None of these {formatNumber(count)} positions has a position class, so there's nothing to forecast them from.
        Give each a position class (what duty it does) when you edit it, then fit the class's life model.</p>
    );
  }
  if (f.pending) return <p className="hint">Working out the forecast…</p>;

  const horizon = f.period ? horizonText(f.periods, f.period) : "";
  const missing = [...f.missing, ...none.map((p) => ({ position: p, reason: "no position class" }))];
  const sentence = f.rows.length ? (
    <>≈ <b>{formatNumber(f.expected, { sig: 3 })}</b> failures expected at the <b>{formatNumber(f.rows.length)}</b>
      {f.rows.length < count ? <> of <b>{formatNumber(count)}</b></> : null} {name} positions here in the next <b>{horizon}</b>.</>
  ) : `None of the ${formatNumber(count)} ${name} positions here can be forecast yet.`;

  return (
    <div className="cf">
      <ResultSummary tone={missing.length ? "caveat" : "neutral"} sentence={sentence}>
        Each position's expected failures come from its position class's life model, fitted to that class's own history,
        and are added up here. The whole position class, with its likely range and budget, is on Forecasts.
      </ResultSummary>
      {f.rows.length > 0 && (
        <section className="card cf-card" aria-label="Positions forecast">
          <div className="maint-scroll"><table className="lib-table">
            <thead><tr><th>Position</th><th>Position class</th><th>Item</th><th className="num">Chance it fails next {f.period}</th><th className="num">Failures in {horizon}</th></tr></thead>
            <tbody>
              {f.rows.map((r) => (
                <tr key={r.position.id}>
                  <td><button type="button" className="link cf-pos" title="Show this position in the tree"
                              onClick={() => onSelect?.(r.position.id)}>{r.position.name || "(no name)"}</button></td>
                  <td className="lib-date">{r.label}</td>
                  <td>{r.item?.name || "—"}</td>
                  <td className="num">{formatPercent(r.prob_next_period)}</td>
                  <td className="num">≈ {formatNumber(r.expected_failures, { sig: 2 })}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        </section>
      )}
      {missing.length > 0 && (
        <div className="lib-date">
          {byReason(missing).map(([reason, names]) => (
            <p key={reason}>Not forecast: {names.slice(0, 8).join(", ")}{names.length > 8 ? ` and ${names.length - 8} more` : ""}. {reason}</p>
          ))}
        </div>
      )}
      {/* Forecasts lists the position classes with a fitted model: link those alone. */}
      {groups.some((g) => reads[g.key]?.n_forecast) && <p className="lib-date">
        On Forecasts:{" "}
        {groups.filter((g) => reads[g.key]?.n_forecast).map((g, i) => (
          <span key={g.key}>{i > 0 && " · "}<Link to={forecastsPath(g.key)}>{g.label}</Link></span>
        ))}
      </p>}
    </div>
  );
}

export function ClassSparesTab({ row, display }) {
  const { groups, none, count } = useGroups(display, row);
  const name = row.ref?.name || "this class";
  if (!count) return <p className="hint">No position here has an item of this class fitted.</p>;
  if (!groups.length) {
    return <p className="hint">None of these positions has a position class, so there's no forecast to plan spares from.</p>;
  }
  return (
    <div className="cf">
      <p className="cf-answer">The spare parts on the parts lists of the {name} positions, by position class: what's usable in stock,
        what the forecast says will be needed and whether stock covers it.</p>
      <Suspense fallback={loading}>
        {groups.map((g) => (
          <ForecastCard key={g.key} name={g.key} label={g.label} show="spares"
                        note={`Stock is shared across the register, so the demand counts every “${g.label}” position, not only the ${formatNumber(g.positions.length)} here.`} />
        ))}
      </Suspense>
      {none.length > 0 && (
        <p className="lib-date">Left out, with no position class: {none.slice(0, 12).map((p) => p.name || "(no name)").join(", ")}
          {none.length > 12 ? ` and ${none.length - 12} more` : ""}.</p>
      )}
    </div>
  );
}

import { useEffect, useMemo, useRef, useState } from "react";
import { getFailureRanking } from "../api.js";
import { csvFileName, downloadCsv } from "../csv.js";
import {
  rankingAsked,
  GROUP_BY, METRIC_AXIS, RANK_BY, WINDOWS, downtimeText, groupHeading, hoursText, moneyText,
  paretoSeries, rangeText, rankingCsv, rankingParams, rateText, reportsFilter, shareText, totalsLine,
} from "../failureRanking.js";
import { ACCENT, INK } from "../plotTheme.js";
import { RowActions } from "./LibRows.jsx";
import Plot from "./Plot.jsx";
import { DateInput } from "./ui/DateTimeInput.jsx";
import { Fold } from "./ui/Fold.jsx";
import LoadFailed from "./LoadFailed.jsx";
import Loading from "./ui/Loading.jsx";
import { Select } from "./ui/Controls.jsx";

// The History tab's Ranking view (FRACAS): the groups below the row (the position opened
// and everything inside it; a product's design: the items built from it), ranked by
// failures, rate, downtime or cost over a window, with a Pareto chart and, for each, the
// count it would have at the pooled rate and how likely this many (or this few) is by
// chance. Numbers and what they mean; never a verdict. Worked out on the server
// (backend/maintenance/failure_ranking.py).
//
// onOpenReports(filters): the Reports view filtered to a group; onSelect(id): pick a
// position in the tree; onAdd: add a failure report (null: can't here).

function Pareto({ data }) {
  const s = paretoSeries(data);
  if (s.x.length < 2) return null;
  const axis = METRIC_AXIS[data.rank_by];
  return (
    <Plot
      data={[
        { type: "bar", name: axis, x: s.x, y: s.y, marker: { color: ACCENT },
          hovertemplate: "%{x}: %{y:,.3~g}<extra></extra>" },
        { type: "scatter", mode: "lines+markers", name: "Cumulative share", x: s.x, y: s.cumulative, yaxis: "y2",
          line: { color: INK, width: 1.5 }, marker: { color: INK, size: 6 },
          hovertemplate: "%{x}: %{y:.0f}% of the total so far<extra></extra>" },
      ]}
      layout={{
        height: 300, showlegend: true,
        xaxis: { type: "category", automargin: true, tickvals: s.x, ticktext: s.labels,
          tickangle: s.labels.some((l) => l.length > 12) ? -30 : 0 },
        yaxis: { title: { text: axis }, rangemode: "tozero" },
        yaxis2: { title: { text: "Cumulative share (%)" }, overlaying: "y", side: "right", range: [0, 105],
          showgrid: false, ticksuffix: "%" },
      }}
      download={`Failure ranking — ${data.scope?.name || ""}`}
    />
  );
}

export default function FailureRanking({ positionId, version, onOpenReports, onSelect, onAdd = null }) {
  // ?group= ?rank= ?window= (failureRanking.js rankingAsked): the ranking a link asks for.
  const [opts, setOpts] = useState(() => rankingAsked(typeof window !== "undefined" ? window.location.search : ""));
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const seq = useRef(0);
  const set = (k, v) => setOpts((o) => ({ ...o, [k]: v }));
  const params = useMemo(() => rankingParams(positionId, opts), [positionId, opts]);

  const load = () => {
    const n = ++seq.current;
    setLoading(true);
    setError(null);
    getFailureRanking(params)
      .then((d) => n === seq.current && setData(d))
      .catch((e) => n === seq.current && setError(e.message))
      .finally(() => n === seq.current && setLoading(false));
  };
  useEffect(load, [params, version]); // eslint-disable-line react-hooks/exhaustive-deps

  const heading = groupHeading(opts.group_by, data?.scope?.kind);
  const controls = (
    <div className="fr-controls fr-rank-controls">
      <label className="fr-date"><span>Rank by</span>
        <Select value={opts.rank_by} aria-label="Rank by" onChange={(e) => set("rank_by", e.target.value)}>
          {RANK_BY.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </Select>
      </label>
      <label className="fr-date"><span>Group by</span>
        <Select value={opts.group_by} aria-label="Group by" onChange={(e) => set("group_by", e.target.value)}>
          {GROUP_BY.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </Select>
      </label>
      <Select value={opts.window} aria-label="Time window" onChange={(e) => set("window", e.target.value)}>
        {WINDOWS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </Select>
      {opts.window === "range" && (
        <>
          <label className="fr-date"><span>Since</span><DateInput value={opts.since} max={opts.until || undefined} onChange={(e) => set("since", e.target.value)} /></label>
          <label className="fr-date"><span>Until</span><DateInput value={opts.until} min={opts.since || undefined} onChange={(e) => set("until", e.target.value)} /></label>
        </>
      )}
      {data?.rows?.length > 0 && (
        <button type="button" className="secondary sm" onClick={() => downloadCsv(rankingCsv(data), csvFileName(data.scope?.name || "Failures", "failure ranking"))}>
          Export CSV
        </button>
      )}
    </div>
  );

  let body;
  if (error) body = <LoadFailed what="the failure ranking" error={error} onRetry={load} />;
  else if (!data) body = <Loading />;
  else if (!data.totals.failures) {
    body = (
      <div className="fr-empty">
        <p>No failures recorded in this window.</p>
        {onAdd && <p><button type="button" className="link" onClick={onAdd}>Add a failure report</button></p>}
      </div>
    );
  } else {
    const rows = data.rows;
    body = (
      <>
        <p className="fr-rank-answer">{data.sentence}</p>
        <p className="fr-counts">{totalsLine(data.totals)}</p>
        <Pareto data={data} />
        <div className="maint-scroll fr-rank-scroll">
          <table className="fr-rank-table" aria-busy={loading || undefined}>
            <thead>
              <tr>
                <th scope="col">Rank</th>
                <th scope="col">{heading}</th>
                <th scope="col" className="num">Failures</th>
                <th scope="col" className="num">Operating hours</th>
                <th scope="col" className="num">Rate per 1,000 h<span className="fr-rank-sub">90% two-sided range</span></th>
                <th scope="col" className="num">Expected<span className="fr-rank-sub">at the pooled rate</span></th>
                <th scope="col" className="num">Downtime</th>
                <th scope="col" className="num">Cost</th>
                <th scope="col" className="num">Share<span className="fr-rank-sub">cumulative</span></th>
                <th scope="col"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            {/* One tbody a group: its numbers, then what they mean on a line under them (so the table
                fits a wide screen without its widest cell, and the sentence wraps). */}
              {rows.map((r) => {
                const filter = reportsFilter(r, data.window);
                const pos = r.link?.kind === "position" ? r.link.id : null;
                const actions = [
                  filter && { id: "open-in", label: "Open in", items: [
                    { id: `reports-${r.key}`, label: "Failure reports", onSelect: () => onOpenReports(filter, r.name) }] },
                  pos && pos !== positionId && { id: `pick-${r.key}`, label: "Show in the tree", onSelect: () => onSelect?.(pos) },
                ].filter(Boolean);
                return (
                  <tbody key={r.key} className="fr-rank-group">
                  <tr>
                    <td className="num">{r.rank}</td>
                    <td className="fr-rank-name">
                      {pos && pos !== positionId && onSelect
                        ? <button type="button" className="link" onClick={() => onSelect(pos)}>{r.name}</button>
                        : r.name}
                      {r.no_fault_found > 0 && <span className="fr-rank-sub">{r.no_fault_found} no fault found (not counted)</span>}
                    </td>
                    <td className="num">{r.failures.toLocaleString("en-AU")}</td>
                    <td className="num">{hoursText(r.hours)}</td>
                    <td className="num">{rateText(r.rate_per_1000h)}<span className="fr-rank-sub">{rangeText(r.rate_per_1000h)}</span></td>
                    <td className="num">{r.expected == null ? "—" : r.expected.toLocaleString("en-AU", { maximumSignificantDigits: 3 })}</td>
                    <td className="num">{downtimeText(r.downtime_hours)}{r.downtime_missing > 0 && r.failures > 0 && <span className="fr-rank-sub">{r.downtime_missing} not set</span>}</td>
                    <td className="num">{moneyText(r.cost)}{r.cost_missing > 0 && r.failures > 0 && <span className="fr-rank-sub">{r.cost_missing} not set</span>}</td>
                    <td className="num">{shareText(r.share)}<span className="fr-rank-sub">{shareText(r.cumulative_share)}</span></td>
                    {actions.length ? <RowActions item={{ name: r.name }} actions={actions} /> : <td />}
                  </tr>
                  <tr className="fr-rank-means-row">
                    <td />
                    <td colSpan={9} className="fr-rank-means">{r.sentence}</td>
                  </tr>
                  </tbody>
                );
              })}
          </table>
        </div>
        <Fold title="How this is counted">
          <ul className="fr-rank-notes">
            {data.notes.map((n) => <li key={n}>{n}</li>)}
          </ul>
        </Fold>
      </>
    );
  }
  return (
    <div className="fr-panel fr-rank">
      {controls}
      {body}
    </div>
  );
}

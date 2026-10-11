import { useEffect, useState } from "react";
import { getWorkspaceChanges } from "../api.js";
import { PERIODS, changeRows, periodQuery } from "../changes.js";
import { formatPercent } from "../format.js";
import PageHeader from "../components/ui/PageHeader.jsx";
import SegmentedControl from "../components/ui/SegmentedControl.jsx";
import ResultSummary, { ResultDetails } from "../components/ui/ResultSummary.jsx";
import { ChangeList, ChangesSentence } from "../components/WhatChanged.jsx";

// What changed in the workspace over a period (#41): the server's sentence
// (its counts in bold, so no tiles repeat them), then every change with a
// link, most important first. What
// can't be compared (nothing stored to compare against) is under Details.
export default function ChangesPage() {
  const [period, setPeriod] = useState("30");
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let live = true;
    setError(null);
    getWorkspaceChanges(periodQuery(period))
      .then((d) => live && setData(d))
      .catch((e) => live && setError(e.message || "Couldn't load the changes."));
    return () => {
      live = false;
    };
  }, [period]);

  const rows = changeRows(data);
  return (
    <div className="app wc-page">
      <PageHeader
        title="What changed"
        meta="Worked out from what this workspace stores. Nothing is estimated."
      />
      <div className="wc-controls">
        <SegmentedControl options={PERIODS} value={period} onChange={setPeriod} label="Period" />
      </div>
      {error && <p className="card empty">{error}</p>}
      {!error && !data && <div className="card empty view-loading">Loading…</div>}
      {!error && data && (
        <>
          <ResultSummary
            tone="neutral"
            sentence={<ChangesSentence sentence={data.sentence} as="span" className="wc-inline" />}
          >
            {data.period?.note}
          </ResultSummary>
          {rows.length > 0 && (
            <div className="wc-card">
              <ChangeList rows={rows} />
            </div>
          )}
          <ResultDetails summary="What can't be compared">
            <ul className="wc-not-compared">
              {data.not_compared.map((n) => (
                <li key={n.what}>
                  <b>{n.what}.</b> {n.why}
                </li>
              ))}
              <li>
                <b>When an answer counts as moved.</b> A refit’s B10 or MTTF, or a forecast’s expected
                failures, moved by more than {formatPercent(data.thresholds.relative)}; a simulation’s
                availability by more than {data.thresholds.availability_points} percentage points.
              </li>
            </ul>
          </ResultDetails>
        </>
      )}
    </div>
  );
}

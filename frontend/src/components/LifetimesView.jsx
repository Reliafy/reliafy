import { useEffect, useMemo, useState } from "react";
import { getDatasetLifetimes } from "../api.js";
import { readingPayload } from "../datasetReading.js";
import Plot from "./Plot.jsx";
import Section from "./ui/Section.jsx";
import Select from "./Select.jsx";
import Loading from "./ui/Loading.jsx";
import LoadFailed from "./LoadFailed.jsx";
import {
  SAMPLE_LINES, lifetimesTraces, lineName, readingHint, rowHeight, sampleLines, sortOptions, sortedLines,
  summaryText, timeRange,
} from "../lifetimes.js";
import "./LifetimesView.css";

// The chart's margins (px); the plot scrolls inside its card past 480 px (LifetimesView.css).
const MARGIN = { l: 56, r: 24, t: 8, b: 44 };
// The tallest the chart is drawn without Show all (px), inside the 480 px scroll box.
const FIT_HEIGHT = 470;

// A dataset's lifetimes: one line per unit (per system for repairable data),
// read with the dataset's reading exactly as a fit reads it (the server builds
// SurPyval's SurpyvalData and returns its lines), so a wrong reading shows at
// a glance: everything "failed" when the status column was read backwards.
//
// ``datasetId``; ``draft``: a reading being changed (not saved yet), drawn in
// place of the saved one; ``version``: changes when the saved reading does,
// to fetch again; ``onChange``: opens the reading's Change (absent when the
// dataset can't be changed); ``name``: the dataset's name for the download.
export default function LifetimesView({ datasetId, draft = null, version = 0, onChange, name = "" }) {
  const [payload, setPayload] = useState(null);
  const [error, setError] = useState(null);
  const [sort, setSort] = useState("time");
  const [showAll, setShowAll] = useState(false);
  const draftKey = draft ? JSON.stringify(draft) : "";

  useEffect(() => {
    let live = true;
    setError(null);
    // A draft is fetched once typing settles; the saved reading at once.
    const timer = setTimeout(() => {
      getDatasetLifetimes(datasetId, draft ? readingPayload(draft) : null)
        .then((p) => { if (live) setPayload(p); })
        .catch((e) => { if (live) setError(e); });
    }, draft ? 300 : 0);
    return () => { live = false; clearTimeout(timer); };
  }, [datasetId, draftKey, version]);

  const options = useMemo(() => sortOptions(payload), [payload]);
  const chosen = options.some((o) => o.value === sort) ? sort : "time";
  const sorted = useMemo(() => sortedLines(payload, chosen), [payload, chosen]);
  const shown = useMemo(() => (showAll ? sorted : sampleLines(sorted, SAMPLE_LINES)), [sorted, showAll]);
  const mode = payload?.mode || "rows";
  const traces = useMemo(() => lifetimesTraces(shown, { mode, unit: payload?.unit, colourBy: chosen.startsWith("group:") }),
    [shown, mode, payload, chosen]);

  const noun = mode === "repairable" ? "systems" : mode === "rows" ? "lines" : "units";
  const total = payload?.total || 0;
  const sampled = shown.length < sorted.length;
  // The sample fits the card whole (the time axis in view); Show all scrolls inside it.
  const natural = Math.max(160, shown.length * rowHeight(shown.length) + MARGIN.t + MARGIN.b + 40);
  const height = showAll ? natural : Math.min(FIT_HEIGHT, natural);
  const ids = shown.length <= 40;
  const unit = payload?.unit ? ` (${payload.unit.toLowerCase()})` : "";
  const layout = useMemo(() => ({
    height,
    margin: { ...MARGIN, l: ids ? 88 : 24 },
    showlegend: true,
    legend: { orientation: "h", x: 0, y: 1, yanchor: "bottom", xanchor: "left" },
    xaxis: { title: { text: `Time${unit}` }, range: timeRange(shown, Math.min(0, payload?.floor ?? 0)), zeroline: false },
    yaxis: {
      autorange: false, range: [shown.length - 0.5, -0.5], showgrid: false, zeroline: false,
      tickmode: ids ? "array" : undefined, tickvals: ids ? shown.map((_, y) => y) : [],
      ticktext: ids ? shown.map((l) => lineName(l, mode)) : [], showticklabels: ids,
      title: { text: ids ? "" : `${shown.length.toLocaleString()} ${noun}, top to bottom` },
    },
  }), [height, ids, unit, shown, payload, mode, noun]);

  const hint = readingHint(payload);
  const aside = payload && !payload.error && options.length > 1 && (
    <span className="lt-sort">
      <span className="lt-sort-label" id="lt-sort-label">Sort by</span>
      <Select options={options} value={chosen} onChange={setSort} ariaLabel="Sort the lifetimes by" />
    </span>
  );

  return (
    <Section title="Lifetimes" className="lt" id="lifetimes" aside={aside}
             action={onChange && !draft ? { label: "Change how it's read", onClick: onChange } : null}
             tip="One line per unit, from when it came under observation to its last time, read the way a fit reads this dataset. Check that the units you know failed are marked failed.">
      {error ? (
        <LoadFailed error={error} what="The lifetimes" />
      ) : !payload ? (
        <Loading rows={2} label="Drawing the lifetimes…" />
      ) : payload.error ? (
        <p className="calc-warn lt-msg" role="status">
          ! These rows can't be read this way, so a fit would refuse them too: {payload.error}
        </p>
      ) : (
        <>
          <p className="lt-summary" data-testid="lifetimes-summary">
            {draft && <span className="lt-draft">With your changes, not saved yet: </span>}
            <strong>{summaryText(payload)}</strong>
          </p>
          {hint && <p className="calc-warn lt-msg" role="status">! {hint}</p>}
          <div className="lt-scroll" tabIndex={0} aria-label={`Lifetimes chart, ${shown.length} ${noun}`}>
            <div className="lt-plot">
              <Plot data={traces} layout={layout} download={name ? `${name} — lifetimes` : "Lifetimes"} />
            </div>
          </div>
          {(sampled || (showAll && sorted.length > SAMPLE_LINES) || payload.sampled || payload.left_out > 0 || payload.notes?.length > 0) && (
            <p className="muted-line lt-note">
              {sampled && (
                <>
                  Showing {shown.length.toLocaleString()} of {sorted.length.toLocaleString()} {noun}, an even sample
                  across the order; the counts above are of every one.{" "}
                  <button type="button" className="link" onClick={() => setShowAll(true)}>Show all</button>
                </>
              )}
              {!sampled && showAll && sorted.length > SAMPLE_LINES && (
                <button type="button" className="link" onClick={() => setShowAll(false)}>Show a sample</button>
              )}
              {payload.sampled && ` The chart holds an even sample of ${sorted.length.toLocaleString()} of ${total.toLocaleString()} ${noun}.`}
              {payload.left_out > 0 && ` ${payload.left_out.toLocaleString()} row${payload.left_out === 1 ? " has" : "s have"} no number in the time column and ${payload.left_out === 1 ? "isn't" : "aren't"} drawn.`}
              {(payload.notes || []).map((n) => ` ${n}`)}
            </p>
          )}
        </>
      )}
    </Section>
  );
}

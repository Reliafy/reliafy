import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { getRbdJob, rbdMeasures } from "../api.js";
import Plot from "./Plot.jsx";
import { CATEGORY, COLORWAY, DATA_INK } from "../plotTheme.js";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import ResultSummary, { ResultDetails } from "./ui/ResultSummary.jsx";
import { formatNumber } from "../format.js";
import { unitInText } from "./unitText.js";
import "./RbdMeasures.css";

// What to improve's other measures (#225, #325), one tab each beside the
// ranked steps: RePyability's importance over time, shares of a change, joint
// importance, availability rate with Barlow–Proschan, and uncertainty
// importance. Each tab asks one plain question and answers it first (the
// backend's sentence, numbers in bold), then at most a few tiles and one chart;
// the rest is under Details. The heavy uncertainty runs (Sobol, the
// availability over time over draws) are Pro and run on the calculation
// service, polled here.

export const TABS = [
  { value: "levers", label: "Ranked steps", question: "Which change gains most?" },
  { value: "over_time", label: "Over time", question: "Which blocks matter most, and when?" },
  { value: "shares", label: "Shares", question: "Where would an all-round improvement pay off?" },
  { value: "joint", label: "Pairs", question: "Which blocks are worth improving together?" },
  { value: "rate", label: "Right now", question: "What's moving availability now?" },
  { value: "uncertainty", label: "Uncertainty", question: "Whose uncertainty widens the answer?" },
];

const POLL_FIRST_MS = 1500;
const POLL_MAX_MS = 6000;
const TOP = 6; // curves and bars shown

const pct = (v, d = 1) => (v == null || !Number.isFinite(v) ? "—" : `${(v * 100).toFixed(d)}%`);
const unitWord = (unit) => (unit ? ` ${unitInText(unit)}` : "");

// The backend's sentence with its numbers in bold.
export function boldNumbers(text) {
  if (!text) return null;
  const parts = String(text).split(/([−+-]?\d[\d,]*(?:\.\d+)?(?:e[−+-]?\d+)?%?)/g);
  return parts.map((p, i) => (i % 2 === 1 ? <b key={i}>{p}</b> : p));
}

// Decimals that tell two fractions apart, shown as percentages.
function pctPair(lo, hi) {
  const s = Math.abs(hi - lo) * 100;
  const d = !Number.isFinite(s) || s <= 0 ? 2 : Math.min(6, Math.max(1, Math.ceil(-Math.log10(s)) + 1));
  return [pct(lo, d), pct(hi, d), d];
}

// One colour per block, by its place in the diagram (never by rank).
function useBlockColors(graph) {
  return useMemo(() => {
    const ids = (graph.nodes || []).filter((n) => n.type !== "input" && n.type !== "output").map((n) => n.id);
    const map = {};
    ids.forEach((id, i) => { map[id] = COLORWAY[i % COLORWAY.length]; });
    return (id) => map[id] || map[String(id).split("+")[0]] || DATA_INK;
  }, [graph.nodes]);
}

function jobText(job) {
  if (!job) return "";
  if (job.status === "running") return "Working it out on the calculation service…";
  const ahead = job.queue_position;
  return ahead == null || ahead <= 0 ? "Queued — you're next…" : `Queued — ${ahead} ahead of you…`;
}

export default function RbdMeasure({ graph, rbdId = null, measure, windowLen = null, over = "long_run",
                                     trigger = null }) {
  const [groupBy, setGroupBy] = useState("block");
  const [method, setMethod] = useState("delta");
  const [timesText, setTimesText] = useState("");
  const [sentTimes, setSentTimes] = useState(null);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [job, setJob] = useState(null);
  const [busy, setBusy] = useState(false);
  const live = useRef(0);
  const unit = graph.unit || "";
  const colorOf = useBlockColors(graph);
  const win = (over === "window" || measure === "over_time" || measure === "rate") ? windowLen : null;

  const run = async () => {
    const ticket = ++live.current;
    setBusy(true);
    setError(null);
    setJob(null);
    try {
      const res = await rbdMeasures({
        graph, rbdId, measure,
        window: measure === "uncertainty" ? null : win,
        groupBy: measure === "shares" ? groupBy : null,
        method: measure === "uncertainty" ? method : null,
        times: measure === "uncertainty" ? sentTimes : null,
      });
      if (ticket !== live.current) return;
      if (res.job) {
        setJob(res.job);
        return;
      }
      setData(res);
      setBusy(false);
    } catch (err) {
      if (ticket !== live.current) return;
      setError(err.message);
      setBusy(false);
    }
  };

  useEffect(() => {
    run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [measure, trigger, groupBy, method, sentTimes, win]);

  const jobId = job?.job_id;
  useEffect(() => {
    if (!jobId) return undefined;
    let cancelled = false;
    let timer = null;
    let delay = POLL_FIRST_MS;
    let failures = 0;
    const poll = async () => {
      try {
        const view = await getRbdJob(jobId);
        if (cancelled) return;
        failures = 0;
        if (view.status === "done" || view.status === "failed") {
          setJob(null);
          if (view.status === "done") setData(view.result);
          else setError(view.error || "The calculation failed.");
          setBusy(false);
          return;
        }
        setJob((prev) => (prev && prev.job_id === jobId ? { ...prev, ...view } : prev));
      } catch (err) {
        if (cancelled) return;
        if (err.status === 404 || ++failures >= 6) {
          setJob(null);
          setError(err.status === 404 ? "The calculation was lost — run it again." : err.message);
          setBusy(false);
          return;
        }
      }
      delay = Math.min(delay * 1.3, POLL_MAX_MS);
      timer = setTimeout(poll, delay);
    };
    timer = setTimeout(poll, POLL_FIRST_MS);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [jobId]);

  const shown = data && data.measure === measure ? data : null;
  const controls = measure === "shares" ? (
    <SegmentedControl label="Group by" showLabel size="sm" value={groupBy} onChange={setGroupBy}
      options={[{ value: "block", label: "Block" }, { value: "kind", label: "Kind of lever",
        title: "Lives, repair times, proof tests…" }]} />
  ) : measure === "uncertainty" ? (
    <UncertaintyControls method={method} setMethod={setMethod} timesText={timesText} setTimesText={setTimesText}
      sentTimes={sentTimes} setSentTimes={setSentTimes} unit={unit} busy={busy} />
  ) : null;

  return (
    <div className="rbd-measure">
      {controls && <div className="rbd-improve-controls">{controls}</div>}
      {error && <div className="card error">{error}</div>}
      {job && <p className="rbd-job-status" role="status" aria-live="polite">{jobText(job)}</p>}
      {busy && !job && <p className="hint" role="status" style={{ margin: 0 }}>Working it out…</p>}
      {shown && !busy && <MeasureBody data={shown} unit={unit} colorOf={colorOf} />}
    </div>
  );
}

function UncertaintyControls({ method, setMethod, timesText, setTimesText, sentTimes, setSentTimes, unit, busy }) {
  const parsed = timesText.split(/[\s,;]+/).filter(Boolean).map(Number);
  const valid = parsed.length > 0 && parsed.length <= 6 && parsed.every((v) => Number.isFinite(v) && v > 0);
  return (
    <>
      <SegmentedControl label="Method" showLabel size="sm" value={method} onChange={setMethod}
        options={[
          { value: "delta", label: "Quick", title: "The delta method: each input's share from the slopes (free)" },
          { value: "sobol", label: "Sobol (Pro)", title: "Sobol indices from draws, counting interactions (Pro)" },
        ]} />
      <details className="rbd-measure-adv">
        <summary>Advanced</summary>
        <div className="rbd-measure-adv-body">
          <label className="param-field rbd-cost-field">
            <span>Also at times</span>
            <input type="text" value={timesText} placeholder="e.g. 730, 8760" onChange={(e) => setTimesText(e.target.value)} />
            <small>{unit || "time"} · up to 6 · Pro</small>
          </label>
          <button type="button" className="secondary" disabled={busy || (!valid && !sentTimes)}
                  onClick={() => setSentTimes(valid ? parsed : null)}>
            {valid ? "Work out at these times" : "Clear times"}
          </button>
        </div>
      </details>
    </>
  );
}

function MeasureBody({ data, unit, colorOf }) {
  if (data.status === "pro_required") {
    return (
      <div className="card note" role="status">
        <p style={{ margin: 0 }}>{data.message}</p>
        <div className="rbd-upgrade-actions"><Link className="cta cta-solid" to="/billing">Upgrade to Pro</Link></div>
      </div>
    );
  }
  if (data.status !== "ok") {
    return (
      <div className="rbd-measure-empty" role="status">
        <p className="muted-line" style={{ margin: 0 }}>{data.message}</p>
        {data.fixed?.length > 0 && <FixedNote fixed={data.fixed} />}
      </div>
    );
  }
  const View = { over_time: OverTime, shares: Shares, joint: Joint, rate: Rate, uncertainty: Uncertainty }[data.measure];
  return View ? <View data={data} unit={unit} colorOf={colorOf} /> : null;
}

const xTitle = (unit) => `Time from new${unit ? ` (${unit})` : ""}`;

function lineChart({ x, series, colorOf, yTitle, unit, yRange, tickformat, name }) {
  const traces = series.map((s) => ({
    x, y: s.values, mode: "lines", type: "scatter", name: s.label,
    line: { color: colorOf(s.id), width: 2 },
    hovertemplate: `${s.label}: %{y${tickformat ? `:${tickformat}` : ""}}<extra></extra>`,
  }));
  const layout = {
    height: 320, showlegend: series.length > 1,
    xaxis: { title: { text: xTitle(unit) } },
    yaxis: { title: { text: yTitle }, ...(yRange ? { range: yRange } : {}), ...(tickformat ? { tickformat } : {}) },
    hovermode: "x unified",
  };
  return <Plot data={traces} layout={layout} download={name} />;
}

function barChart({ rows, color, xTitle: xt, name, tickformat = ".0%" }) {
  const shown = rows.slice(0, 8).reverse();
  const trace = {
    type: "bar", orientation: "h",
    x: shown.map((r) => r.value), y: shown.map((r) => r.label),
    marker: { color: shown.map((r) => r.color || color) },
    hovertemplate: `%{y}: %{x:${tickformat}}<extra></extra>`,
  };
  const layout = {
    height: Math.max(160, 44 + 34 * shown.length), showlegend: false,
    xaxis: { title: { text: xt }, tickformat, zeroline: true },
    yaxis: { automargin: true },
    margin: { l: 8 },
  };
  return <Plot data={[trace]} layout={layout} download={name} />;
}

function OverTime({ data, unit, colorOf }) {
  const series = (data.series || []).slice(0, TOP);
  const stats = (data.series || []).slice(0, 3).map((s) => ({
    label: s.label, value: pct(s.long_run, 1), hint: "critical in the long run",
  }));
  return (
    <>
      <ResultSummary sentence={boldNumbers(data.answer)} stats={stats} />
      <div className="rbd-measure-chart">
        {lineChart({ x: data.time, series, colorOf, yTitle: "Chance it's critical", unit,
          tickformat: ".1%", name: "Importance over time" })}
      </div>
      <ResultDetails>
        <p className="muted-line">
          Each block's Birnbaum importance at each time from new: the chance the system works only while that block
          does. {data.basis === "exact" ? "Exact" : "Numerical"} (RePyability {data.repyability_version}), no simulation.
          {(data.notes || []).map((n) => ` ${n}`)}
        </p>
      </ResultDetails>
    </>
  );
}

function Shares({ data }) {
  const rows = (data.shares || []).map((r) => ({ label: r.group, value: r.share }));
  return (
    <>
      <ResultSummary sentence={boldNumbers(data.answer)} />
      <div className="rbd-measure-chart">
        {barChart({ rows, color: CATEGORY.blue, xTitle: "Share of the gain", name: "Shares of an all-round improvement" })}
      </div>
      <ResultDetails>
        <p className="muted-line">
          Every lever (lives, repair times, intervals, coverage) improved by the same small fraction: each one's share of
          the total gain {data.window ? "over the window" : "in the long run"} (RePyability's differential importance).
          Counts such as one more crew take no part.{(data.notes || []).map((n) => ` ${n}`)}
        </p>
        {data.levers?.length > 0 && (
          <div className="rbd-avail-imp-scroll">
            <table className="calc-table rbd-measure-table">
              <thead><tr><th>Lever</th><th>Share</th></tr></thead>
              <tbody>
                {data.levers.map((r) => (
                  <tr key={`${r.block}|${r.name}`}>
                    <td><b>{r.block}</b> · {r.name}</td>
                    <td>{pct(r.share, 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </ResultDetails>
    </>
  );
}

function Joint({ data }) {
  const rows = (data.pairs || []).map((r) => ({
    label: r.label, value: r.value, color: r.value >= 0 ? CATEGORY.blue : CATEGORY.amber,
  }));
  return (
    <>
      <ResultSummary sentence={boldNumbers(data.answer)} />
      <div className="rbd-measure-chart">
        {barChart({ rows, xTitle: "Joint importance (+ complements, − substitutes)", name: "Joint importance",
          tickformat: ".2f" })}
      </div>
      <ResultDetails>
        <p className="muted-line">
          How much improving one block raises the other's importance: positive, they are complements (improve them
          together); negative, substitutes (one covers for the other). {data.window ? "Over the window" : "In the long run"},
          exact.
        </p>
        <div className="rbd-avail-imp-scroll">
          <table className="calc-table rbd-measure-table">
            <thead><tr><th>Pair</th><th>Joint importance</th><th>They are</th></tr></thead>
            <tbody>
              {(data.pairs || []).map((r) => (
                <tr key={`${r.a}|${r.b}`}>
                  <td>{r.label}</td>
                  <td>{r.value >= 0 ? "+" : "−"}{Math.abs(r.value).toFixed(3)}</td>
                  <td>{r.kind}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </ResultDetails>
    </>
  );
}

function Rate({ data, unit, colorOf }) {
  // Points of availability per unit time, or per 1,000 when that's tiny.
  const max = Math.max(0, ...(data.series || []).flatMap((s) => s.values.map((v) => Math.abs(v || 0))));
  const per1000 = max * 100 < 0.01;
  const k = per1000 ? 100000 : 100;
  const u = (unit || "unit time").toLowerCase().replace(/s$/, "");
  const yTitle = `Points per ${per1000 ? `1,000 ${u}s` : u}`;
  const ranked = [...(data.series || [])].sort((a, b) =>
    Math.max(...b.values.map((v) => Math.abs(v || 0))) - Math.max(...a.values.map((v) => Math.abs(v || 0))));
  const series = ranked.slice(0, TOP).map((s) => ({ ...s, values: s.values.map((v) => (v == null ? null : v * k)) }));
  const stats = (data.causes || []).slice(0, 3).map((c) => ({
    label: c.label, value: pct(c.share, 0), hint: "of system failures",
  }));
  return (
    <>
      <ResultSummary sentence={boldNumbers(data.answer)} stats={stats} />
      <div className="rbd-measure-chart">
        {lineChart({ x: data.time, series, colorOf, yTitle, unit, name: "What's moving availability" })}
      </div>
      <ResultDetails>
        <p className="muted-line">
          Each block's part in how fast the availability changes (negative pulls it down, positive lifts it as repairs
          finish): its Birnbaum importance times the rate its own availability changes, which add up to the system's
          rate. Numerical, no simulation.
          {data.jumps?.length > 0 && ` Scheduled tests or replacements make it jump at ${data.jumps.length} times in the window.`}
          {data.causes_note ? ` Shares of failures: ${data.causes_note}` : ""}
        </p>
        {data.causes?.length > 0 && (
          <div className="rbd-avail-imp-scroll">
            <table className="calc-table rbd-measure-table">
              <thead><tr><th>Block</th><th>Share of system failures, long run</th>
                {data.causes_window?.length > 0 && <th>Over the window</th>}</tr></thead>
              <tbody>
                {data.causes.map((c) => (
                  <tr key={c.id}>
                    <td>{c.label}</td>
                    <td>{pct(c.share, 1)}</td>
                    {data.causes_window?.length > 0 && (
                      <td>{pct(data.causes_window.find((w) => w.id === c.id)?.share, 1)}</td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </ResultDetails>
    </>
  );
}

function FixedNote({ fixed }) {
  return (
    <p className="muted-line" style={{ margin: 0 }}>
      Kept fixed: {fixed.map((f) => `${f.label} (${f.reason})`).join(" · ")}.
    </p>
  );
}

function Uncertainty({ data, unit }) {
  const a = data.availability || {};
  const [lo, hi, d] = pctPair(a.lower, a.upper);
  const sobol = data.method === "sobol";
  const rows = (data.shares || []).map((r) => ({
    label: `${r.label} · ${r.what}`, value: Math.min(1, Math.max(0, r.first_order ?? 0)),
  }));
  const stats = [
    { label: "Long-run availability", value: pct(a.nominal, d), hint: `${Math.round((data.level || 0.95) * 100)}%: ${lo} – ${hi}` },
    { label: "Uncertain inputs", value: String((data.shares || []).length), hint: "saved fitted models" },
  ];
  return (
    <>
      <ResultSummary sentence={boldNumbers(data.answer)} stats={stats} />
      <div className="rbd-measure-chart">
        {barChart({ rows, color: CATEGORY.blue, xTitle: sobol ? "First-order share of the variance" : "Share of the variance",
          name: "Uncertainty importance" })}
      </div>
      <ResultDetails>
        {data.at_times?.length > 0 && (
          <div className="rbd-avail-imp-scroll">
            <table className="calc-table rbd-measure-table">
              <thead>
                <tr><th>Time{unitWord(unit)}</th><th>Availability then</th><th>Mean availability to then</th></tr>
              </thead>
              <tbody>
                {data.at_times.map((r) => {
                  const [pl, ph, pd] = pctPair(r.availability.lower, r.availability.upper);
                  const [ml, mh, md] = pctPair(r.mean_availability.lower, r.mean_availability.upper);
                  return (
                    <tr key={r.t}>
                      <td>{formatNumber(r.t)}</td>
                      <td>{pct(r.availability.nominal, pd)}<div className="muted rbd-improve-iv">{pl} – {ph}</div></td>
                      <td>{pct(r.mean_availability.nominal, md)}<div className="muted rbd-improve-iv">{ml} – {mh}</div></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {sobol && (
          <div className="rbd-avail-imp-scroll">
            <table className="calc-table rbd-measure-table">
              <thead><tr><th>Input</th><th>First-order</th><th>Total</th></tr></thead>
              <tbody>
                {(data.shares || []).map((r) => (
                  <tr key={r.id}>
                    <td><b>{r.label}</b> · {r.what}<div className="muted">{r.model}</div></td>
                    <td>{pct(Math.min(1, Math.max(0, r.first_order ?? 0)), 1)}</td>
                    <td>{pct(Math.min(1, Math.max(0, r.total ?? 0)), 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="muted-line">
          {(data.n_draws || 0).toLocaleString()} draws of the fitted models' parameters (each fit's covariance); blocks
          sharing a saved model are drawn together. Shares: {sobol
            ? `Sobol indices from ${(data.n_draws_sobol || 0).toLocaleString()} draws a set (the total counts interactions)`
            : "the delta method (each input's slopes against its covariance)"}.
          {data.at_times?.length ? ` Over time: ${(data.n_draws_over_time || 0).toLocaleString()} draws.` : ""}
        </p>
        {data.fixed?.length > 0 && <FixedNote fixed={data.fixed} />}
      </ResultDetails>
    </>
  );
}

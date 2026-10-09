import { useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { analyzeRbd, getRbdJob, optimiseIntervals } from "../api.js";
import { graphSignature } from "./RbdValidation.jsx";
import { fmtMoney } from "./AvailabilityCosts.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";

// Maintenance and proof-test intervals chosen together (#172, #228), on the
// Design tab of a repairable diagram: RePyability's
// optimal_replacement_intervals / optimal_inspection_intervals, scored by the
// exact long-run values (free). Proof tests choose from a calendar and may be
// staggered (the first tests' times chosen too), with the best plan with every
// test at once beside it, so the effect on the PFDavg and cost shows. With
// fewer repair crews than jobs the intervals are chosen as if no repair waits;
// "Simulate with your crews" runs the availability simulation (Pro, or a free
// quick estimate) of the diagram with the plan on it, to show what the
// waiting costs. "Apply to diagram" writes the intervals on the blocks,
// unsaved, as the cheapest design does.

const POLL_FIRST_MS = 1500;
const POLL_MAX_MS = 6000;
const UNITS_PER_YEAR = { hour: 8760, hours: 8760, h: 8760, day: 365, days: 365, week: 365 / 7, weeks: 365 / 7,
  month: 12, months: 12, year: 1, years: 1 };
const MONTHS = [1, 3, 6, 12, 24, 36, 48];

const num = (v) => {
  if (v == null || !Number.isFinite(v)) return "—";
  const r = Number(v.toPrecision(4));
  return Math.abs(r) >= 1000 ? Math.round(r).toLocaleString() : r.toString();
};
const pct = (v) => (v == null || !Number.isFinite(v) ? "—" : `${(v * 100).toFixed(4)}%`);
const sci = (v) => (v == null || !Number.isFinite(v) ? "—" : v >= 0.01 ? v.toFixed(4) : v.toExponential(2));
const per = (unit) => (unit ? ` /${unit.toLowerCase().replace(/s$/, "")}` : " per unit time");

// The default proof-test calendar in the diagram's unit (as the backend's).
function calendar(unit) {
  const perYear = UNITS_PER_YEAR[String(unit || "").trim().toLowerCase()];
  return perYear ? MONTHS.map((m) => Number(((m * perYear) / 12).toPrecision(6))) : null;
}

// The diagram with a plan's rows on its blocks (as rbd_intervals.apply_plan):
// each interval, a proof test's first test, and "never" removing the schedule.
export function applyIntervals(graph, rows) {
  const byId = Object.fromEntries(rows.map((r) => [r.id, r]));
  const nodes = (graph.nodes || []).map((n) => {
    const r = byId[n.id];
    if (!r) return n;
    const data = { ...n.data };
    if (data.preventive) {
      if (r.never) delete data.preventive;
      else data.preventive = { ...data.preventive, interval: r.interval };
    } else if (data.inspection) {
      const test = { ...data.inspection, interval: r.interval };
      if (r.offset) test.offset = r.offset;
      else delete test.offset;
      data.inspection = test;
    }
    return { ...n, data };
  });
  return { ...graph, nodes };
}

// The blocks with age replacement and with (full-coverage) proof tests.
export function maintainedBlocks(graph) {
  const out = { replacement: [], proof_test: [] };
  for (const n of graph.nodes || []) {
    if (n.type !== "component") continue;
    const d = n.data || {};
    if (d.preventive && (d.preventive.policy || "age") === "age") out.replacement.push(n);
    else if (d.inspection && !(d.inspection.coverage !== undefined && d.inspection.coverage !== "" && Number(d.inspection.coverage) < 1))
      out.proof_test.push(n);
  }
  return out;
}

async function poll(jobId, live, ticket) {
  let delay = POLL_FIRST_MS;
  let failures = 0;
  for (;;) {
    await new Promise((r) => setTimeout(r, delay));
    if (live.current !== ticket) return null;
    try {
      const view = await getRbdJob(jobId);
      failures = 0;
      if (view.status === "done") return view.result;
      if (view.status === "failed") throw new Error(view.error || "The calculation failed.");
    } catch (err) {
      if (err.status === 404 || ++failures >= 6) throw err;
    }
    delay = Math.min(delay * 1.3, POLL_MAX_MS);
  }
}

function Interval({ row, unit, schedule }) {
  if (row.never) return <>never (run to failure)</>;
  const u = unit ? ` ${unit.toLowerCase()}` : "";
  return (
    <>
      {num(row.interval)}{u}
      {schedule === "proof_test" && row.offset ? <div className="muted">first at {num(row.offset)}{u}</div> : null}
    </>
  );
}

export default function RbdIntervals({ graph, onApply, onView }) {
  const found = useMemo(() => maintainedBlocks(graph), [graph]);
  const kinds = ["proof_test", "replacement"].filter((k) => found[k].length);
  const safety = !!graph.safety_function;
  const [schedule, setSchedule] = useState(null);
  const kind = schedule && found[schedule].length ? schedule : kinds[0];
  const [target, setTarget] = useState(safety ? (graph.target_sil ? "sil" : "pfd") : "cost"); // cost | availability | pfd | sil | budget
  const [value, setValue] = useState(safety ? (graph.target_sil ? String(graph.target_sil) : "0.001") : "");
  const [allowedText, setAllowedText] = useState("");
  const [stagger, setStagger] = useState(true);
  const [phase, setPhase] = useState("idle");
  const [error, setError] = useState(null);
  const [job, setJob] = useState(null);
  const [run, setRun] = useState(null); // {result, sig}
  const [crewSim, setCrewSim] = useState(null); // {state, result?, message?, quick?}
  const [applied, setApplied] = useState(null); // {prev, sig}
  const live = useRef(0);
  const sig = graphSignature(graph);
  const unit = graph.unit || "";
  const cal = calendar(unit);
  const tested = found.proof_test.length;

  if (!kinds.length) {
    return (
      <div className="rbd-design rbd-intervals">
        <div className="ds-section-h">Maintenance and proof-test intervals</div>
        <p className="muted-line" style={{ margin: 0 }}>
          Give blocks <b>age replacement</b> or <b>proof tests</b> (double-click a block on the Builder tab → Cost
          &amp; maintenance) to choose their intervals together here — the cheapest, or the cheapest that keeps the
          availability (or a safety function's PFDavg) on target.
        </p>
      </div>
    );
  }

  const targetBody = () => {
    const v = value === "" ? null : Number(value);
    if (target === "availability") return { minAvailability: v == null ? null : v / 100 };
    if (target === "pfd") return { maxPfd: v };
    if (target === "sil") return { targetSil: v };
    if (target === "budget") return { maxCostRate: v };
    return {};
  };

  const choose = async () => {
    const ticket = ++live.current;
    setPhase("working");
    setError(null);
    setJob(null);
    setCrewSim(null);
    try {
      const allowed = allowedText.trim()
        ? allowedText.split(/[\s,;]+/).filter(Boolean).map(Number)
        : null;
      let res = await optimiseIntervals({
        graph,
        schedule: kind,
        ...targetBody(),
        allowed: kind === "proof_test" ? allowed : null,
        stagger: kind === "proof_test" && stagger && tested > 1,
        assumeUnlimitedCrews: true,
      });
      if (live.current !== ticket) return;
      if (res.job) {
        setJob(res.job);
        res = await poll(res.job.job_id, live, ticket);
        if (res == null) return;
        setJob(null);
      }
      setRun({ result: res, sig });
    } catch (e) {
      if (live.current !== ticket) return;
      setJob(null);
      setRun(null);
      setError(e.message);
    } finally {
      if (live.current === ticket) setPhase("idle");
    }
  };

  const result = run?.result;
  const appliedCurrent = applied && applied.sig === sig;
  const stale = run != null && run.sig !== sig && !appliedCurrent;
  const rows = result?.blocks || [];
  const crews = result?.crews;
  const together = result?.together;

  const apply = () => {
    const prev = { nodes: graph.nodes, edges: graph.edges };
    const next = applyIntervals(graph, rows);
    onApply(next);
    setApplied({ prev, sig: graphSignature(next) });
  };
  const undo = () => {
    onApply(applied.prev);
    setApplied(null);
  };

  // The plan simulated with the diagram's own crews: what the waiting costs.
  const simulateCrews = async (quick = false) => {
    const ticket = ++live.current;
    setCrewSim({ state: "running" });
    try {
      let res;
      try {
        res = await analyzeRbd(applyIntervals(graph, rows), null, {}, null, quick ? { quick: true } : { simulate: true });
      } catch (e) {
        if (e.status === 402) {
          setCrewSim({ state: "pro", quick: e.data?.quick || null });
          return;
        }
        if (e.status === 429) {
          setCrewSim({ state: "error", message: e.message });
          return;
        }
        throw e;
      }
      if (live.current !== ticket) return;
      if (res.job) {
        setCrewSim({ state: "running", job: res.job });
        res = await poll(res.job.job_id, live, ticket);
        if (res == null) return;
      }
      if (!res.has_simulation) {
        const status = res.simulation_status || {};
        setCrewSim({ state: "pro", quick: status.quick || null });
        return;
      }
      setCrewSim({ state: "done", result: res });
    } catch (e) {
      if (live.current === ticket) setCrewSim({ state: "error", message: e.message });
    }
  };

  const sim = crewSim?.state === "done" ? crewSim.result : null;
  const simFig = sim && {
    availability: sim.precision?.window_availability,
    lower: sim.precision?.lower,
    upper: sim.precision?.upper,
    pfd: sim.safety?.pfd_avg,
    sil: sim.safety?.sil,
    cost: sim.costs?.cost_rate,
  };
  const showTogether = together && kind === "proof_test";
  const cols = [
    { key: "now", label: "As drawn", fig: result?.current },
    ...(showTogether ? [{ key: "together", label: "Best, tests together", fig: together.met ? together : null }] : []),
    { key: "plan", label: result?.stagger ? "Best, staggered" : "Chosen", fig: result?.plan },
  ];
  const waits = crews?.waits;

  return (
    <div className="rbd-design rbd-intervals">
      <div className="ds-section-h">Maintenance and proof-test intervals</div>
      <p className="muted-line" style={{ marginTop: 0 }}>
        Every block's interval chosen together — a block whose failure stops the system is worth maintaining
        sooner than one with a standby. Each candidate plan is scored by the diagram's exact long-run cost and
        availability{safety ? " (PFDavg, with its common-cause groups)" : ""}.
      </p>

      {kinds.length > 1 && (
        <SegmentedControl
          label="Intervals"
          value={kind}
          onChange={setSchedule}
          options={[
            { value: "proof_test", label: "Proof tests" },
            { value: "replacement", label: "Replacement ages" },
          ]}
        />
      )}

      <div className="param-fields rbd-cheapest-inputs">
        <label className="param-field rbd-cost-field">
          <span>Choose for</span>
          <select value={target} onChange={(e) => {
            const t = e.target.value;
            setTarget(t);
            setValue(t === "pfd" ? "0.001" : t === "sil" ? String(graph.target_sil || 2) : t === "availability" ? "99.9" : "");
          }}>
            <option value="cost">Lowest cost</option>
            <option value="availability">Lowest cost, availability at least</option>
            {safety && <option value="pfd">Lowest cost, PFDavg at most</option>}
            {safety && <option value="sil">Lowest cost, reaching SIL</option>}
            <option value="budget">Most available within a cost rate</option>
          </select>
        </label>
        {target !== "cost" && (
          <label className="param-field rbd-cost-field">
            <span>{{ availability: "Minimum availability", pfd: "Maximum PFDavg", sil: "Target SIL", budget: "Maximum cost rate" }[target]}</span>
            {target === "sil" ? (
              <select value={value} onChange={(e) => setValue(e.target.value)}>
                {[1, 2, 3, 4].map((s) => <option key={s} value={String(s)}>SIL {s}</option>)}
              </select>
            ) : (
              <input type="number" step="any" min="0" value={value} onChange={(e) => setValue(e.target.value)} />
            )}
            <small>{{ availability: "% (e.g. 99.9)", pfd: "e.g. 0.001", sil: "PFDavg below the band's top", budget: `${per(unit).trim()}` }[target]}</small>
          </label>
        )}
        {kind === "proof_test" && (
          <label className="param-field rbd-cost-field rbd-intervals-allowed"
                 title="The test intervals each block chooses from, separated by commas.">
            <span>Intervals to choose from</span>
            <input type="text" value={allowedText} onChange={(e) => setAllowedText(e.target.value)}
                   placeholder={cal ? "monthly … four-yearly" : "e.g. 100, 250, 500"} />
            <small>{cal ? `${unit || "time"} · blank: ${cal.map(num).join(", ")} and each block's own` : unit || "time"}</small>
          </label>
        )}
      </div>
      {kind === "proof_test" && tested > 1 && (
        <label className="rbd-intervals-check">
          <input type="checkbox" checked={stagger} onChange={(e) => setStagger(e.target.checked)} />
          <span>
            Stagger the tests — choose when each block is first tested too, so redundant channels are tested apart
            and a common-cause failure is found sooner
          </span>
        </label>
      )}
      <div className="rbd-calc-actions">
        <button type="button" onClick={choose}
                disabled={phase === "working" || (target !== "cost" && value === "") || (kind === "proof_test" && !cal && !allowedText.trim() && tested > 1)}>
          {phase === "working" ? "Choosing…" : "Choose intervals"}
        </button>
        <span className="hint">
          {found[kind].length} block{found[kind].length === 1 ? "" : "s"} ({found[kind].map((n) => n.data?.label || n.id).join(", ")})
        </span>
      </div>
      {job && (
        <p className="rbd-job-status" role="status" aria-live="polite">
          {job.status === "running" ? "Searching the intervals…" : job.queue_position > 0 ? `Queued — ${job.queue_position} ahead of you…` : "Queued — you're next…"}
        </p>
      )}
      {error && <div className="card error">{error}</div>}

      {result && result.status === "ok" && (
        <div className={"rbd-cheapest-result" + (stale ? " stale" : "")}>
          {stale && <p className="hint">The diagram changed since these intervals were chosen — choose them again.</p>}
          <p className={`rbd-compare-verdict ${result.changed ? "b_higher" : ""}`}>
            {!result.changed
              ? <>The intervals as drawn are already the best for this target.</>
              : <>
                  {result.plan.cost_rate != null && result.current?.cost_rate != null && (
                    <>Running cost {fmtMoney(result.current.cost_rate)} → <b>{fmtMoney(result.plan.cost_rate)}</b>{per(unit)}</>
                  )}
                  {safety && result.plan.pfd_avg != null && (
                    <>; PFDavg {sci(result.current?.pfd_avg)} → <b>{sci(result.plan.pfd_avg)}</b> (SIL {result.plan.sil ?? "—"})</>
                  )}
                  {!safety && result.plan.availability != null && (
                    <>; availability {pct(result.current?.availability)} → <b>{pct(result.plan.availability)}</b></>
                  )}
                  .
                </>}
            {showTogether && together.met && together.cost_rate > 0 && result.plan.cost_rate != null && (
              <> Staggered, the tests cost{" "}
                {result.plan.cost_rate < together.cost_rate
                  ? <b>{Math.round((1 - result.plan.cost_rate / together.cost_rate) * 100)}% less</b>
                  : "no less"}{" "}
                than the best plan with every test at once ({fmtMoney(together.cost_rate)}{per(unit)}).</>
            )}
            {showTogether && !together.met && <> Tested at once, no intervals to choose from meet the target: staggering does.</>}
          </p>
          <div className="rbd-avail-imp-scroll">
            <table className="calc-table rbd-costs-table">
              <thead>
                <tr>
                  <th>Block</th>
                  <th>Now</th>
                  {showTogether && <th>Tests together</th>}
                  <th>{result.stagger ? "Staggered" : "Chosen"}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const t = showTogether && together.met ? together.blocks.find((b) => b.id === r.id) : null;
                  return (
                    <tr key={r.id} className={r.changed ? "changed" : ""}>
                      <td className="calc-row-label">{r.label}</td>
                      <td><Interval row={{ interval: r.interval_now, offset: r.offset_now }} unit={unit} schedule={kind} /></td>
                      {showTogether && <td>{t ? <Interval row={t} unit={unit} schedule={kind} /> : "—"}</td>}
                      <td><Interval row={r} unit={unit} schedule={kind} /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="rbd-avail-imp-scroll">
            <table className="calc-table rbd-costs-table">
              <thead>
                <tr>
                  <th></th>
                  {cols.map((c) => <th key={c.key}>{c.label}</th>)}
                  {waits && <th>Chosen, with your {crews.crews} crew{crews.crews === 1 ? "" : "s"}</th>}
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td className="calc-row-label">Running cost{per(unit)}</td>
                  {cols.map((c) => <td key={c.key}>{c.fig?.cost_rate != null ? fmtMoney(c.fig.cost_rate) : "—"}</td>)}
                  {waits && <td>{simFig?.cost != null ? fmtMoney(simFig.cost) : "—"}</td>}
                </tr>
                {safety ? (
                  <>
                    <tr>
                      <td className="calc-row-label">PFDavg</td>
                      {cols.map((c) => <td key={c.key}>{sci(c.fig?.pfd_avg)}</td>)}
                      {waits && <td>{simFig ? sci(simFig.pfd) : "—"}</td>}
                    </tr>
                    <tr>
                      <td className="calc-row-label">SIL band</td>
                      {cols.map((c) => <td key={c.key}>{c.fig ? (c.fig.sil ? `SIL ${c.fig.sil}` : "none") : "—"}</td>)}
                      {waits && <td>{simFig ? (simFig.sil ? `SIL ${simFig.sil}` : "none") : "—"}</td>}
                    </tr>
                  </>
                ) : (
                  <tr>
                    <td className="calc-row-label">Availability</td>
                    {cols.map((c) => <td key={c.key}>{pct(c.fig?.availability)}</td>)}
                    {waits && (
                      <td>
                        {pct(simFig?.availability)}
                        {simFig?.lower != null && <div className="muted">{pct(simFig.lower)} – {pct(simFig.upper)}</div>}
                      </td>
                    )}
                  </tr>
                )}
                {result.target?.type !== "lowest_cost" && (
                  <tr>
                    <td className="calc-row-label">Meets the target</td>
                    {cols.map((c) => <td key={c.key}>{c.fig?.meets_target == null ? "—" : c.fig.meets_target ? "yes" : "no"}</td>)}
                    {waits && <td>—</td>}
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          {showTogether && !together.met && <p className="hint" style={{ margin: 0 }}>Tests together: {together.message}</p>}
          {result.current == null && result.current_note && (
            <p className="hint" style={{ margin: 0 }}>As drawn: {result.current_note}</p>
          )}

          {waits && (
            <div className="card note" role="status">
              <p style={{ margin: 0 }}>
                {crews.note} These intervals are chosen as if every repair started at once.
              </p>
              {crewSim?.state === "done" ? (
                <p style={{ margin: "6px 0 0" }}>
                  With your {crews.crews} crew{crews.crews === 1 ? "" : "s"}, simulated
                  {sim.quick ? " (a quick estimate)" : ""} over {num(sim.t_simulation)}{unit ? ` ${unit.toLowerCase()}` : ""} from
                  new ({(sim.n_simulations || 0).toLocaleString()} runs):{" "}
                  {safety
                    ? <>PFDavg <b>{sci(simFig.pfd)}</b> against {sci(result.plan.pfd_avg)} with no waiting.</>
                    : <>availability <b>{pct(simFig.availability)}</b> against {pct(result.plan.availability)} with no waiting.</>}
                </p>
              ) : crewSim?.state === "pro" ? (
                <div style={{ margin: "6px 0 0" }}>
                  <p style={{ margin: 0 }}>Simulating the plan with your crews is part of Pro, or buy AI credits.</p>
                  <div className="rbd-upgrade-actions">
                    {crewSim.quick?.remaining_today > 0 && (
                      <button type="button" onClick={() => simulateCrews(true)}>
                        Quick estimate ({crewSim.quick.remaining_today} left today)
                      </button>
                    )}
                    <Link className="cta cta-solid" to="/billing">Upgrade to Pro</Link>
                  </div>
                </div>
              ) : (
                <div className="rbd-upgrade-actions">
                  <button type="button" disabled={crewSim?.state === "running" || stale} onClick={() => simulateCrews(false)}>
                    {crewSim?.state === "running" ? "Simulating…" : `Simulate with your ${crews.crews} crew${crews.crews === 1 ? "" : "s"}`}
                  </button>
                </div>
              )}
              {crewSim?.state === "error" && <p className="hint" style={{ margin: "6px 0 0" }}>{crewSim.message}</p>}
            </div>
          )}
          {result.common_cause?.note && <p className="hint" style={{ margin: 0 }}>{result.common_cause.note}</p>}
          {(result.notes || []).map((n) => <p key={n} className="hint" style={{ margin: 0 }}>{n}</p>)}

          {result.changed && (!stale || appliedCurrent) && (
            <div className="rbd-calc-actions">
              {appliedCurrent ? (
                <>
                  <button type="button" onClick={() => onView?.()}>View on canvas</button>
                  <button type="button" className="secondary" onClick={undo}>Undo</button>
                  <span className="hint">Written on the blocks — review and save when you're happy.</span>
                </>
              ) : (
                <>
                  <button type="button" onClick={apply} title="Write these intervals on the blocks — nothing is saved">
                    Apply to diagram
                  </button>
                  <span className="hint">Writes the intervals{kind === "proof_test" ? " and first tests" : ""} on the blocks; nothing is saved.</span>
                </>
              )}
            </div>
          )}
          <p className="muted-line" style={{ margin: 0 }}>
            RePyability {result.repyability_version} ·{" "}
            {kind === "replacement"
              ? "optimal_replacement_intervals: a gradient search over the exact long-run values, shown to four significant figures."
              : `optimal_inspection_intervals${result.stagger ? " with offsets=\"stagger\" (first tests at even shares of the interval)" : ""}: every combination of the intervals to choose from, up to 2,000 (a local search beyond).`}
            {" "}Figures are {result.basis === "numerical" ? "numerical (deterministic)" : "exact"} long-run values{waits ? ", with no repair waiting for a crew" : ""}.
          </p>
        </div>
      )}
    </div>
  );
}

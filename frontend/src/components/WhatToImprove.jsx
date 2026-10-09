import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { getRbdJob, rbdSensitivity } from "../api.js";
import MethodTag from "./MethodTag.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";

// "What to improve" on a repairable diagram's availability results (#225):
// every lever RePyability exposes (a block's mean life and repair time, its
// other model parameters, maintenance intervals and coverage, one more crew)
// moved one step the way that helps, ranked by what that gains — or, with a
// cost to make each change, by gain per unit of cost. The backend says how
// each answer was found (exact, numerical or simulated); a numerical, windowed
// or simulated one runs on the calculation service and is polled here.

const STEPS = [0.1, 0.25, 0.5];
const SHOWN = 8; // rows before "Show all"
const POLL_FIRST_MS = 1500;
const POLL_MAX_MS = 6000;

const sig = (v, d = 2) => (v == null || !Number.isFinite(v) ? "—" : Number(v.toPrecision(d)).toString());
const num = (v) => {
  if (v == null || !Number.isFinite(v)) return "—";
  const r = Number(v.toPrecision(3));
  return Math.abs(r) >= 1000 ? Math.round(r).toLocaleString() : r.toString();
};
const signed = (v, f) => (v == null || !Number.isFinite(v) ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${f(Math.abs(v))}`);
const money = (v) => (Math.abs(v) >= 100 ? Math.round(v).toLocaleString() : Number(v.toPrecision(3)).toLocaleString());
const per = (unit) => (unit ? `/${unit.toLowerCase().replace(/s$/, "")}` : "/unit time");
const BASIS_TAG = { exact: "exact", numerical: "numerical", simulation: "simulated" };

const BASIS_TEXT = {
  exact:
    "Each effect is the diagram's exact long-run availability (and cost) recomputed with the lever moved — no simulation. " +
    "The slopes are RePyability's central differences of the same exact values.",
  numerical:
    "Each effect is RePyability's numerical (deterministic, to about 1e-7) value recomputed with the lever moved — no simulation.",
  simulation:
    "Each effect is simulated: the diagram with the lever moved against the diagram as it is, with common random numbers, " +
    "with its 95% interval.",
};

const WINDOW_TEXT =
  "Each effect is RePyability's slope of the window's mean availability (numerical: each block's renewal " +
  "equation on a grid, no simulation) times the step.";

function jobText(job) {
  if (!job) return "";
  if (job.status === "running") return "Working out what to improve…";
  const ahead = job.queue_position;
  if (ahead == null || ahead <= 0) return "Queued — you're next…";
  return `Queued — ${ahead} ahead of you…`;
}

// "8.37 → 7.54 h", "720 → 648 h", "1 → 2".
function span(row, unit) {
  if (row.shown_value == null || row.shown_to == null) return null;
  const u = unit && (row.kind === "mean" || row.kind === "time") ? ` ${unit.toLowerCase()}` : "";
  return `${num(row.shown_value)} → ${num(row.shown_to)}${u}`;
}

export default function WhatToImprove({ graph, rbdId = null, result: availability }) {
  const [step, setStep] = useState(0.1);
  const [rankBy, setRankBy] = useState("availability");
  const [over, setOver] = useState("long_run"); // long_run | window
  const [costs, setCosts] = useState({}); // {lever id: "cost"} as typed
  const [sentCosts, setSentCosts] = useState({});
  // "benefit": by the step's gain alone; "benefit_per_cost": costed levers first.
  const [order, setOrder] = useState("benefit");
  const [editCosts, setEditCosts] = useState(false);
  const [data, setData] = useState(null);
  const [phase, setPhase] = useState("idle"); // idle | running
  const [error, setError] = useState(null);
  const [job, setJob] = useState(null);
  const [showAll, setShowAll] = useState(false);
  // Once asked for, the simulated route stays on as the step or ranking changes.
  const [simWanted, setSimWanted] = useState(false);
  const live = useRef(0);

  const unit = graph.unit || "";
  const windowLen = availability?.exact?.window ?? availability?.t_simulation ?? null;

  const run = async ({ simulate = simWanted, withCosts = sentCosts } = {}) => {
    const ticket = ++live.current;
    setPhase("running");
    setError(null);
    setJob(null);
    try {
      const numeric = Object.fromEntries(
        Object.entries(withCosts)
          .map(([k, v]) => [k, Number(v)])
          .filter(([, v]) => Number.isFinite(v) && v > 0)
      );
      const res = await rbdSensitivity({
        graph,
        rbdId,
        step,
        rankBy,
        order,
        window: over === "window" ? windowLen : null,
        costs: Object.keys(numeric).length ? numeric : null,
        simulate,
      });
      if (ticket !== live.current) return;
      if (res.job) {
        setJob(res.job);
        // Nothing to rank until the job is done (an older ranking would mislead).
        setData({ status: "pending", basis: res.basis, basis_reason: res.basis_reason });
        return;
      }
      setData(res);
      setPhase("idle");
    } catch (err) {
      if (ticket !== live.current) return;
      setError(err.message);
      setPhase("idle");
    }
  };

  // Recompute when the diagram's results, the step, the ranking or the window change.
  useEffect(() => {
    run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [availability, step, rankBy, over, order, sentCosts]);

  // Poll a queued job until it's done.
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
        if (view.status === "done") {
          setJob(null);
          setData(view.result);
          setPhase("idle");
          return;
        }
        if (view.status === "failed") {
          setJob(null);
          setError(view.error || "The calculation failed.");
          setPhase("idle");
          return;
        }
        setJob((prev) => (prev && prev.job_id === jobId ? { ...prev, ...view } : prev));
      } catch (err) {
        if (cancelled) return;
        if (err.status === 404 || ++failures >= 6) {
          setJob(null);
          setError(err.status === 404 ? "The calculation was lost — run it again." : err.message);
          setPhase("idle");
          return;
        }
      }
      delay = Math.min(delay * 1.3, POLL_MAX_MS);
      timer = setTimeout(poll, delay);
    };
    timer = setTimeout(poll, POLL_FIRST_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [jobId]);

  const rows = data?.status === "ok" ? data.levers || [] : [];
  const ranked = rows.filter((r) => r.effect);
  const visible = showAll ? rows : ranked.slice(0, SHOWN);
  const withCosts = rows.some((r) => r.cost_to_change);
  const priced = !!data?.priced;
  const costChanged = useMemo(
    () => JSON.stringify(costs) !== JSON.stringify(sentCosts),
    [costs, sentCosts]
  );
  const positive = (m) => Object.values(m).some((v) => Number(v) > 0);
  const hasSentCosts = positive(sentCosts);
  const hasTypedCosts = positive(costs);
  const basis = data?.basis;
  const sim = basis === "simulation" && data?.status === "ok";
  const tag = BASIS_TAG[basis];

  return (
    <div className="rbd-improve">
      <div className="ds-section-h">
        What to improve {tag && <MethodTag method={tag} />}
      </div>
      <p className="hint" style={{ margin: 0 }}>
        Each lever moved one step the way that helps — a {Math.round(step * 100)}% longer mean life, a{" "}
        {Math.round(step * 100)}% shorter mean repair time or test interval, one more repair crew — and ranked by
        what it gains{over === "window" ? ` over the first ${num(windowLen)}${unit ? ` ${unit.toLowerCase()}` : ""}` : " in the long run"}.
      </p>

      <div className="rbd-improve-controls">
        <SegmentedControl
          label="Step"
          size="sm"
          value={step}
          onChange={setStep}
          options={STEPS.map((s) => ({ value: s, label: `${Math.round(s * 100)}%`, title: `Move each lever ${Math.round(s * 100)}%` }))}
        />
        <SegmentedControl
          label="Over"
          size="sm"
          value={over}
          onChange={(v) => {
            setOver(v);
            if (v === "window") setRankBy("availability");
          }}
          options={[
            { value: "long_run", label: "Long run", title: "Rank by the long-run (steady-state) availability" },
            { value: "window", label: "Window", disabled: !windowLen,
              title: "Rank by the mean availability over the results' window, from new (runs on the calculation service)" },
          ]}
        />
        {over === "long_run" && (priced || rankBy === "cost") && (
          <SegmentedControl
            label="Rank by"
            size="sm"
            value={rankBy}
            onChange={setRankBy}
            options={[
              { value: "availability", label: "Availability" },
              { value: "cost", label: "Cost", title: "Rank by the running cost saved per unit time" },
            ]}
          />
        )}
        {(editCosts || hasSentCosts) && rows.length > 0 && (
          <SegmentedControl
            label="Order"
            size="sm"
            value={order}
            onChange={(v) => {
              if (v === "benefit_per_cost" && costChanged) setSentCosts(costs);
              setOrder(v);
            }}
            options={[
              { value: "benefit", label: "Benefit",
                title: "Rank by the step's benefit alone, whether or not a lever has a cost" },
              { value: "benefit_per_cost", label: "Benefit per cost", disabled: !hasSentCosts && !hasTypedCosts,
                title: "The levers with a cost to change first, by benefit per unit spent; then the rest by benefit" },
            ]}
          />
        )}
        {rows.length > 0 && (
          <button type="button" className="secondary" onClick={() => setEditCosts((v) => !v)}>
            {editCosts ? "Hide costs to change" : "Add costs to change…"}
          </button>
        )}
      </div>

      {error && <div className="card error">{error}</div>}
      {job && <p className="rbd-job-status" role="status" aria-live="polite">{jobText(job)}</p>}
      {phase === "running" && !job && <p className="hint" role="status" style={{ margin: 0 }}>Working out what to improve…</p>}

      {data?.status === "pro_required" && (
        <div className="card note" role="status">
          <p style={{ margin: 0 }}>
            <b>This diagram's effects need the simulation.</b> {data.basis_reason}
          </p>
          <p style={{ margin: "6px 0 0" }}>
            Each lever's step is simulated against the diagram as it is — that's part of Pro, or buy AI credits.
          </p>
          <div className="rbd-upgrade-actions">
            <Link className="cta cta-solid" to="/billing">Upgrade to Pro</Link>
          </div>
        </div>
      )}
      {data?.status === "needs_simulation" && (
        <div className="card note" role="status">
          <p style={{ margin: 0 }}>{data.basis_reason}</p>
          <p style={{ margin: "6px 0 0" }}>{data.message}</p>
          <div className="rbd-upgrade-actions">
            <button type="button" disabled={phase === "running"}
                    onClick={() => { setSimWanted(true); run({ simulate: true }); }}>
              {phase === "running" ? "Simulating…" : "Simulate the effects"}
            </button>
          </div>
        </div>
      )}
      {data?.status === "too_large" && <div className="card note" role="status">{data.message}</div>}

      {data?.status === "ok" && data.top && (
        <p className="rbd-improve-top">
          <b>Top:</b> {data.top}
        </p>
      )}

      {visible.length > 0 && (
        <div className="rbd-avail-imp-scroll">
          <table className="calc-table rbd-improve-table">
            <thead>
              <tr>
                <th className="rbd-improve-rank">#</th>
                <th>Lever and change</th>
                <th title="Change in availability, in percentage points">
                  <span className="rbd-improve-wide">Availability</span>
                  <span className="rbd-improve-narrow">Avail.</span>
                </th>
                {priced && (
                  <th title={`Change in the running cost per unit time (${per(unit)})`}>
                    <span className="rbd-improve-wide">Cost {per(unit)}</span>
                    <span className="rbd-improve-narrow">Cost</span>
                  </th>
                )}
                {editCosts && <th title="What making this change would cost you (any currency)">Cost to change</th>}
                {withCosts && (
                  <th title={rankBy === "cost" ? "Running cost saved per unit time, for every 1,000 spent" : "Availability points gained for every 1,000 spent"}>
                    Per 1,000 spent
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {visible.map((r) => {
                const a = r.effect?.availability;
                const c = r.effect?.cost_rate;
                const slope = r.derivative_shown?.availability;
                const iv = r.interval?.availability;
                const dTitle = slope != null
                  ? `RePyability's slope: ${sig(slope * 100, 3)} points per unit of ${r.kind === "mean" ? r.name.toLowerCase() : r.lever}`
                  : undefined;
                return (
                  <tr key={r.id} className={r.kind === "shape" ? "is-shape" : ""}>
                    <td className="rbd-improve-rank">{r.rank}</td>
                    <td className="rbd-improve-lever">
                      <div><b>{r.block}</b> · {r.name}</div>
                      {r.change && (
                        <div className="muted">
                          {r.change[0].toUpperCase() + r.change.slice(1)}
                          {span(r, unit) ? ` (${span(r, unit)})` : ""}
                        </div>
                      )}
                      {r.unranked && <div className="muted">{r.unranked}</div>}
                    </td>
                    <td title={dTitle}>
                      {a == null ? "—" : (
                        <>
                          {signed(a * 100, (v) => sig(v, 2))}
                          {r.effect_basis === "linear" && <span className="rbd-improve-approx" title="The slope times the step"> ≈</span>}
                          {sim && iv && (
                            <div className="muted rbd-improve-iv">
                              {signed(iv[0] * 100, (v) => sig(v, 2))} to {signed(iv[1] * 100, (v) => sig(v, 2))}
                            </div>
                          )}
                        </>
                      )}
                    </td>
                    {priced && <td>{c == null ? "—" : signed(c, money)}</td>}
                    {editCosts && (
                      <td>
                        <input
                          type="number"
                          min="0"
                          step="any"
                          className="rbd-improve-cost"
                          value={costs[r.id] ?? ""}
                          placeholder="—"
                          aria-label={`Cost of ${r.change || "this change"} for ${r.block}`}
                          onChange={(e) => setCosts((prev) => ({ ...prev, [r.id]: e.target.value }))}
                        />
                      </td>
                    )}
                    {withCosts && (
                      <td>
                        {r.benefit_per_cost == null
                          ? "—"
                          : rankBy === "cost"
                          ? money(r.benefit_per_cost * 1000)
                          : `${sig(r.benefit_per_cost * 100 * 1000, 2)} pts`}
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {editCosts && rows.length > 0 && (
        <div className="rbd-improve-controls">
          <button
            type="button"
            disabled={phase === "running" || !costChanged}
            onClick={() => setSentCosts(costs)}
          >
            Apply costs
          </button>
          <span className="hint">
            Enter what each change would cost: each lever then shows its gain per 1,000 spent. Order by
            “Benefit per cost” to put the costed levers first, by gain per unit spent.
          </span>
        </div>
      )}

      {rows.length > 0 && (rows.length > visible.length || showAll) && (
        <button type="button" className="secondary rbd-improve-more" onClick={() => setShowAll((v) => !v)}>
          {showAll ? "Show the top levers" : `Show all ${rows.length} levers`}
        </button>
      )}

      {data?.status === "ok" && (
        <p className="muted-line" style={{ margin: 0 }}>
          {data.of === "window" && !sim ? WINDOW_TEXT : BASIS_TEXT[basis] || ""}
          {sim && data.n_simulations
            ? ` ${data.n_simulations.toLocaleString()} simulations of each over ${num(data.t_simulation)}${unit ? ` ${unit.toLowerCase()}` : ""}.`
            : ""}
          {rows.some((r) => r.effect_basis === "linear") && " ≈: the slope times the step (over a window, or an interval on a shared calendar)."}
          {" "}Effects are in percentage points of availability{priced ? ` and running cost ${per(unit)}` : ""}; hover an effect for the slope.
          {(data.notes || []).map((n) => ` ${n}`)}
          {data.pinned?.length ? ` Pinned blocks (${data.pinned.join(", ")}) are left out.` : ""}
        </p>
      )}
    </div>
  );
}

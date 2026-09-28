import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Select from "./Select.jsx";
import { compareRbds, listRbds } from "../api.js";
import { pctAt, pctDigits, pointsAt } from "./availabilityPrecision.js";

// "Compare with…" on a repairable diagram's availability results (#104): pick
// another saved repairable diagram — typically a copy of this one with one
// change, or the saved version of what's being edited — and see how much more
// (or less) available it is, with a confidence interval. Both designs are
// simulated with common random numbers, so blocks with the same id share their
// failures and repairs and the interval reflects the design change, not chance.
//
// Each compared quantity is one entry of QUANTITIES, read from
// ``result.differences[key]``; cost of ownership (#99) slots in as another.
const QUANTITIES = [
  {
    key: "availability",
    label: "Availability",
    more: "more available",
    less: "less available",
    unit: "percentage points",
    designValue: (d) => d.steady_state_availability,
    windowValue: (d) => d.window_availability,
  },
];

// Design A: whatever is in the builder, saved or not.
const THIS = "This diagram";

// The plain-language verdict for one quantity's difference (B − A).
function verdict(q, diff, nameA, nameB) {
  if (diff.estimate === 0 && diff.standard_error === 0) {
    return <>No difference: {nameA} and <b>{nameB}</b> behaved identically in every simulated history.</>;
  }
  const conf = Math.round((diff.confidence || 0.95) * 100);
  const d = pctDigits(diff.half_width || diff.tolerance || diff.estimate);
  const ci = (lo, hi) => `${conf}% CI ${pointsAt(lo, d)} to ${pointsAt(hi, d)}`;
  if (diff.verdict === "b_higher") {
    return <><b>{nameB}</b> is {q.more} than {nameA} by <b>{Math.abs(diff.estimate * 100).toFixed(d)}</b> {q.unit} ({ci(diff.lower, diff.upper)}).</>;
  }
  if (diff.verdict === "a_higher") {
    return <><b>{nameB}</b> is {q.less} than {nameA} by <b>{Math.abs(diff.estimate * 100).toFixed(d)}</b> {q.unit} ({ci(diff.lower, diff.upper)}).</>;
  }
  return <>No detectable difference in {q.label.toLowerCase()} between {nameA} and <b>{nameB}</b> ({ci(diff.lower, diff.upper)}).</>;
}

export default function AvailabilityCompare({ graph, rbdId, result: availability }) {
  const [rbds, setRbds] = useState(null); // saved repairable diagrams
  const [otherId, setOtherId] = useState("");
  const [phase, setPhase] = useState("idle"); // idle | running
  const [comparison, setComparison] = useState(null);
  const [error, setError] = useState(null);
  const [needsPro, setNeedsPro] = useState(false);

  useEffect(() => {
    let live = true;
    listRbds()
      .then((r) => live && setRbds((r.rbds || []).filter((d) => d.repairable)))
      .catch(() => live && setRbds([]));
    return () => { live = false; };
  }, []);

  // A new availability run (the diagram changed) makes an old comparison stale.
  useEffect(() => {
    setComparison(null);
    setError(null);
  }, [availability]);

  const options = (rbds || []).map((d) => ({
    value: d.id,
    label: d.id === rbdId ? `${d.name} (saved version)` : d.name,
    hint: d.is_sample ? "sample" : undefined,
  }));
  const other = (rbds || []).find((d) => d.id === otherId);

  const run = async () => {
    if (!otherId) return;
    setPhase("running");
    setError(null);
    setNeedsPro(false);
    try {
      const nameB = other?.id === rbdId ? `${other.name} (saved version)` : other?.name;
      setComparison(await compareRbds(graph, otherId, { name: THIS, otherName: nameB }));
    } catch (err) {
      setComparison(null);
      if (err.status === 402 && err.code === "pro_required") setNeedsPro(true);
      else setError(err.message);
    }
    setPhase("idle");
  };

  const u = graph.unit ? ` ${graph.unit}` : "";
  const c = comparison;
  const nameA = c?.designs?.a?.name || THIS;
  const nameB = c?.designs?.b?.name || "the other diagram";

  return (
    <div className="rbd-compare">
      <div className="ds-section-h">Compare with…</div>
      <div className="rbd-compare-bar">
        <Select
          value={otherId}
          onChange={(v) => { setOtherId(v); setComparison(null); }}
          options={options}
          placeholder={rbds == null ? "Loading diagrams…" : options.length ? "Choose a saved repairable diagram…" : "No saved repairable diagrams"}
          disabled={!options.length}
          title="Another saved repairable diagram to compare this one with"
        />
        <button type="button" onClick={run} disabled={!otherId || phase === "running"}>
          {phase === "running" ? "Comparing…" : "Compare"}
        </button>
      </div>
      {!c && !error && !needsPro && (
        <p className="hint" style={{ margin: 0 }}>
          Save a copy of this diagram with one change (a faster repair, a spare) and compare the two.
          Blocks with the same id are simulated with the same random numbers, so the interval
          measures the change itself, not simulation noise.
        </p>
      )}
      {needsPro && (
        <div className="card note" role="status">
          Comparing designs runs the availability simulation — it's part of Pro.{" "}
          <Link to="/billing">Upgrade to Pro</Link>
        </div>
      )}
      {error && <div className="card error">{error}</div>}

      {c && QUANTITIES.filter((q) => c.differences?.[q.key]).map((q) => {
        const diff = c.differences[q.key];
        const d = pctDigits(diff.half_width || diff.tolerance);
        const dExact = Math.max(d, 3);
        const a = c.designs.a;
        const b = c.designs.b;
        return (
          <div className="rbd-compare-result" key={q.key}>
            <p className={`rbd-compare-verdict ${diff.verdict}`}>
              {verdict(q, diff, nameA === THIS ? "this diagram" : nameA, nameB)}
            </p>
            <div className="rbd-avail-imp-scroll">
              <table className="calc-table rbd-compare-table">
                <thead>
                  <tr>
                    <th>Design</th>
                    <th title="Exact long-run (steady-state) value">Long-run {q.label.toLowerCase()}</th>
                    <th title={`Simulated mean over the ${fmtT(c.t_simulation)}${u} window`}>Over the window</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td className="calc-row-label"><span className="rbd-compare-tag">A</span>{nameA}</td>
                    <td>{pctAt(q.designValue(a), dExact)}</td>
                    <td>{pctAt(q.windowValue(a), d)}</td>
                  </tr>
                  <tr>
                    <td className="calc-row-label"><span className="rbd-compare-tag">B</span>{nameB}</td>
                    <td>{pctAt(q.designValue(b), dExact)}</td>
                    <td>{pctAt(q.windowValue(b), d)}</td>
                  </tr>
                  <tr className="rbd-compare-diff">
                    <td className="calc-row-label">Difference (B − A), points</td>
                    <td>{pointsAt(diff.exact, dExact)}</td>
                    <td>
                      {pointsAt(diff.estimate, d)}{" "}
                      <span className="muted">({pointsAt(diff.lower, d)} to {pointsAt(diff.upper, d)})</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p className="muted-line" style={{ margin: 0 }}>
              {c.n_simulations?.toLocaleString()} simulations of each design over {fmtT(c.t_simulation)}{u}
              {c.common_random_numbers
                ? `, with common random numbers (${c.shared_blocks} block${c.shared_blocks === 1 ? "" : "s"} paired by id)`
                : ", run independently (a block's model can't be replayed for common random numbers)"}
              .{" "}
              {diff.reached
                ? `The difference is pinned to within ±${Math.abs(diff.tolerance * 100).toFixed(pctDigits(diff.tolerance))} points.`
                : "The precision target wasn't reached within the time budget; the interval shows the precision achieved."}
              {c.horizon_shortened && " The window was shortened to keep the simulation quick."}
              {" "}The long-run values are exact and don't depend on the simulation.
            </p>
          </div>
        );
      })}
    </div>
  );
}

const fmtT = (v) => (v == null || !Number.isFinite(v) ? "—" : Number(v.toPrecision(5)).toLocaleString());

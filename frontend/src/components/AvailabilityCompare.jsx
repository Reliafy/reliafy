import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Select from "./Select.jsx";
import { compareRbds, listRbds } from "../api.js";
import { pctAt, pctDigits, pointsAt } from "./availabilityPrecision.js";
import { fmtMoney } from "./AvailabilityCosts.jsx";
import { unitInText } from "./unitText.js";

// "Compare with…" on a repairable diagram's availability results (#104): pick
// another saved repairable diagram — typically a copy of this one with one
// change, or the saved version of what's being edited — and see how much more
// (or less) available it is, with a confidence interval. Both designs are
// simulated with common random numbers, so blocks with the same id share their
// failures and repairs and the interval reflects the design change, not chance.
//
// Since #321 the difference is exact (``method: "exact"``, no interval) where
// both designs have exact values over the window, and simulated only where
// they don't.
//
// Each compared quantity is one entry of QUANTITIES, read from
// ``result.differences[key]``: availability, and cost (#99) when both designs
// are priced — what owning each for the window costs, purchases included. ``digits`` sizes the rounding to the interval, ``value`` formats
// a design's figure, ``diff`` a signed difference, ``amount`` the verdict's.
const signed = (v, f) => (v == null || !Number.isFinite(v) ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${f(Math.abs(v))}`);
const QUANTITIES = [
  {
    key: "availability",
    label: "Availability",
    more: "more available",
    less: "less available",
    unit: " percentage points",
    longRun: "Long-run availability",
    window: "Over the window",
    diffLabel: "Difference (B − A), points",
    designValue: (d) => d.steady_state_availability,
    windowValue: (d) => d.window_availability,
    digits: (spread) => pctDigits(spread),
    value: (v, d) => pctAt(v, d),
    exactValue: (v, d) => pctAt(v, Math.max(d, 3)),
    diff: (v, d) => pointsAt(v, d),
    exactDiff: (v, d) => pointsAt(v, Math.max(d, 3)),
    amount: (v, d) => Math.abs(v * 100).toFixed(d),
    tone: (verdict) => verdict,
  },
  {
    key: "cost",
    label: "Cost",
    more: "costs more to own",
    less: "costs less to own",
    unit: " over the window, purchases included",
    longRun: "Running cost per unit time",
    window: "Owning it for the window",
    diffLabel: "Difference (B − A)",
    designValue: (d) => d.cost_rate,
    windowValue: (d) => d.window_cost,
    digits: () => 0,
    value: (v) => fmtMoney(v),
    exactValue: (v) => fmtMoney(v),
    diff: (v) => signed(v, fmtMoney),
    exactDiff: (v) => signed(v, fmtMoney),
    amount: (v) => fmtMoney(Math.abs(v)),
    // Costing more is the worse outcome: colour it as the other way round.
    tone: (verdict) => (verdict === "b_higher" ? "a_higher" : verdict === "a_higher" ? "b_higher" : verdict),
  },
];

// Design A: whatever is in the builder, saved or not.
const THIS = "This diagram";

// The plain-language verdict for one quantity's difference (B − A).
function verdict(q, diff, nameA, nameB) {
  const exact = diff.method === "exact";
  if (diff.estimate === 0 && diff.standard_error === 0) {
    return exact
      ? <>No difference: {nameA} and <b>{nameB}</b> have the same expected {q.label.toLowerCase()} over the window.</>
      : <>No difference: {nameA} and <b>{nameB}</b> behaved identically in every simulated history.</>;
  }
  const conf = Math.round((diff.confidence || 0.95) * 100);
  const d = q.digits(diff.half_width || diff.tolerance || diff.estimate);
  const ci = (lo, hi) => (exact ? "exact" : `${conf}% CI ${q.diff(lo, d)} to ${q.diff(hi, d)}`);
  const is = q.key === "availability" ? "is " : "";
  if (diff.verdict === "b_higher") {
    return <><b>{nameB}</b> {is}{q.more} than {nameA} by <b>{q.amount(diff.estimate, d)}</b>{q.unit} ({ci(diff.lower, diff.upper)}).</>;
  }
  if (diff.verdict === "a_higher") {
    return <><b>{nameB}</b> {is}{q.less} than {nameA} by <b>{q.amount(diff.estimate, d)}</b>{q.unit} ({ci(diff.lower, diff.upper)}).</>;
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

  const u = graph.unit ? ` ${unitInText(graph.unit)}` : "";
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
          The difference is exact where both designs allow it; otherwise blocks with the same id are
          simulated with the same random numbers, so the interval measures the change itself.
        </p>
      )}
      {needsPro && (
        <div className="card note" role="status">
          Comparing designs runs the availability simulation — it's part of Pro.{" "}
          <Link to="/billing">Upgrade to Pro</Link>
        </div>
      )}
      {error && <div className="card error">{error}</div>}
      {c?.cost_note && <p className="hint" style={{ margin: 0 }}>{c.cost_note}</p>}

      {c && QUANTITIES.filter((q) => c.differences?.[q.key]).map((q) => {
        const diff = c.differences[q.key];
        const d = q.digits(diff.half_width || diff.tolerance);
        const a = c.designs.a;
        const b = c.designs.b;
        return (
          <div className="rbd-compare-result" key={q.key}>
            <p className={`rbd-compare-verdict ${q.tone(diff.verdict)}`}>
              {verdict(q, diff, nameA === THIS ? "this diagram" : nameA, nameB)}
            </p>
            <div className="rbd-avail-imp-scroll">
              <table className="calc-table rbd-compare-table">
                <thead>
                  <tr>
                    <th>Design</th>
                    <th title="Exact long-run (steady-state) value">{q.longRun}</th>
                    <th title={`${diff.method === "exact" ? "Exact" : "Simulated"} mean over the ${fmtT(c.t_simulation)}${u} window from new`}>{q.window}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td className="calc-row-label"><span className="rbd-compare-tag">A</span>{nameA}</td>
                    <td>{q.exactValue(q.designValue(a), d)}</td>
                    <td>{q.value(q.windowValue(a), d)}</td>
                  </tr>
                  <tr>
                    <td className="calc-row-label"><span className="rbd-compare-tag">B</span>{nameB}</td>
                    <td>{q.exactValue(q.designValue(b), d)}</td>
                    <td>{q.value(q.windowValue(b), d)}</td>
                  </tr>
                  <tr className="rbd-compare-diff">
                    <td className="calc-row-label">{q.diffLabel}</td>
                    <td>{q.exactDiff(diff.exact, d)}</td>
                    <td>
                      {q.diff(diff.estimate, d)}
                      {diff.method !== "exact" && (
                        <> <span className="muted">({q.diff(diff.lower, d)} to {q.diff(diff.upper, d)})</span></>
                      )}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            {q.key === "cost" ? (
              <p className="muted-line" style={{ margin: 0 }}>
                Owning each design for {fmtT(c.t_simulation)}{u} from new: its purchase prices
                {diff.acquisition ? ` (${signed(diff.acquisition, fmtMoney)} for ${nameB})` : ""} plus its running
                costs{diff.method === "exact"
                  ? ", exact"
                  : `, from the same paired simulations as the availability${c.common_random_numbers ? " (common random numbers)" : ""}`}.
                The running cost per unit time is the long-run rate, exact where RePyability has it. Costs aren&rsquo;t
                discounted.
              </p>
            ) : diff.method === "exact" ? (
              <p className="muted-line" style={{ margin: 0 }}>
                Exact: RePyability works out both designs&rsquo; expected availability over a window of{" "}
                {fmtT(c.t_simulation)}{u} from new, so the difference has no simulation noise and nothing is simulated.
                The long-run values are exact too.
              </p>
            ) : (
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
            )}
          </div>
        );
      })}
    </div>
  );
}

const fmtT = (v) => (v == null || !Number.isFinite(v) ? "—" : Number(v.toPrecision(5)).toLocaleString());

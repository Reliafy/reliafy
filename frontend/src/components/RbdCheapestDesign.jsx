import { useState } from "react";
import { Link } from "react-router-dom";
import { cheapestRbdDesign } from "../api.js";
import { graphSignature } from "./RbdValidation.jsx";
import { fmtMoney } from "./AvailabilityCosts.jsx";
import { unitInText } from "./unitText.js";

// The Design tab for a repairable diagram (#99): how many copies of each block
// with a purchase price own the system at the lowest total cost over a
// horizon — buying them, running them (repairs, parts, maintenance, tests)
// and the lost production they save — optionally keeping it at least so
// available. RePyability's allocate_redundancy scores every design exactly.
// "Apply to diagram" draws the copies on the canvas, unsaved (as the
// non-repairable Design panel does). A discount rate (% a year, prefilled
// from the diagram's costs) makes every total a present value, and the design
// chosen the one with the lowest (#219). Trains (#227, RePyability 0.12): pick
// the blocks of a chain in series — a pump with its valve and motor — and the
// search weighs whole copies of it, each another path into the node the train
// feeds (a vote there gains a branch: 2-out-of-3 becomes 2-out-of-4).
const fmtT = (v) => (v == null || !Number.isFinite(v) ? "—" : Number(v.toPrecision(5)).toLocaleString());
const pct = (v) => (v == null || !Number.isFinite(v) ? "—" : `${(v * 100).toFixed(4)}%`);

export default function RbdCheapestDesign({ graph, onApply, onView }) {
  const priced = (graph.nodes || []).filter((n) => n.type === "component" && Number(n.data?.costs?.acquisition) > 0);
  const components = (graph.nodes || []).filter((n) => n.type === "component");
  const componentIds = new Set(components.map((n) => n.id));
  const [trainsDraft, setTrains] = useState([]); // [{name, blocks: [ids]}]
  const [singles, setSingles] = useState(true); // also copy priced blocks outside the trains
  // Blocks deleted from the canvas leave their trains.
  const trains = trainsDraft.map((t) => ({ ...t, blocks: t.blocks.filter((b) => componentIds.has(b)) }));
  const ownerOf = {};
  trains.forEach((t, i) => t.blocks.forEach((b) => { ownerOf[b] = i; }));
  const usedTrains = trains.filter((t) => t.blocks.length > 0);
  const addTrain = () => setTrains([...trains, { name: `Train ${trains.length + 1}`, blocks: [] }]);
  const updateTrain = (i, patch) => setTrains(trains.map((t, j) => (j === i ? { ...t, ...patch } : t)));
  const toggleBlock = (i, id) => {
    const t = trains[i];
    updateTrain(i, { blocks: t.blocks.includes(id) ? t.blocks.filter((b) => b !== id) : [...t.blocks, id] });
  };
  const [horizon, setHorizon] = useState(graph.costs?.horizon != null ? String(graph.costs.horizon) : "");
  const [floor, setFloor] = useState("");
  const [discount, setDiscount] = useState(graph.costs?.discount_rate != null ? String(graph.costs.discount_rate) : "");
  const [phase, setPhase] = useState("idle");
  const [run, setRun] = useState(null); // {result, sig}
  const [error, setError] = useState(null);
  const [needsPro, setNeedsPro] = useState(false);
  const [applied, setApplied] = useState(null); // {prev, sig}
  const sig = graphSignature(graph);
  const unit = graph.unit ? ` ${unitInText(graph.unit)}` : "";

  const find = async () => {
    setPhase("working");
    setError(null);
    setNeedsPro(false);
    try {
      const result = await cheapestRbdDesign({
        graph,
        horizon: horizon === "" ? null : Number(horizon),
        minAvailability: floor === "" ? null : Number(floor) / 100,
        discountRate: discount === "" ? 0 : Number(discount),
        trains: usedTrains.length ? usedTrains.map((t) => ({ name: t.name, blocks: t.blocks })) : null,
        blocks: usedTrains.length && !singles ? [] : null,
      });
      setRun({ result, sig });
    } catch (e) {
      setRun(null);
      if (e.status === 402 && e.code === "pro_required") setNeedsPro(true);
      else setError(e.message);
    } finally {
      setPhase("idle");
    }
  };

  const result = run?.result;
  const pv = result?.discount_rate > 0 ? ` (present value at ${result.discount_rate}% a year)` : "";
  const appliedCurrent = applied && applied.sig === sig;
  const stale = run != null && run.sig !== sig && !appliedCurrent;
  const apply = () => {
    // Common-cause groups too: a grouped block's copies join its group (#226).
    const prev = { nodes: graph.nodes, edges: graph.edges, ccf_groups: graph.ccf_groups || [] };
    onApply(result.graph);
    setApplied({ prev, sig: graphSignature({ ...graph, ...result.graph }) });
  };
  const undo = () => {
    onApply(applied.prev);
    setApplied(null);
  };

  return (
    <div className="rbd-design rbd-cheapest">
      <p className="muted-line" style={{ marginTop: 0 }}>
        The cheapest design: how many copies of each block with a purchase price own this system at the
        lowest total cost — buying the copies, running them (repairs, parts, maintenance, tests), and the
        lost production they save. Every design is scored exactly.
      </p>
      {priced.length === 0 && (
        <div className="card note" role="status">
          Give at least one block a <b>purchase price</b> (double-click it on the Builder tab →
          Cost &amp; maintenance), and set the <b>system downtime cost</b> under Costs, so extra copies can be
          weighed against the downtime they save.
        </div>
      )}
      {priced.length > 0 && (
        <>
          <div className="param-fields rbd-cheapest-inputs">
            <label className="param-field rbd-cost-field" title="How long the system is owned: purchase prices plus running cost over this long.">
              <span>Ownership horizon</span>
              <input type="number" step="any" min="0" value={horizon} placeholder="e.g. 87600"
                     onChange={(e) => setHorizon(e.target.value)} />
              <small>{graph.unit || "time"}</small>
            </label>
            <label className="param-field rbd-cost-field" title="Only designs at least this available (long run). Blank: no floor.">
              <span>Minimum availability</span>
              <input type="number" step="any" min="0" max="100" value={floor} placeholder="optional"
                     onChange={(e) => setFloor(e.target.value)} />
              <small>% (e.g. 99.95)</small>
            </label>
            <label className="param-field rbd-cost-field" title="Makes the totals present values: copies bought now, running costs and the downtime they save discounted over the horizon. Blank or 0: undiscounted.">
              <span>Discount rate</span>
              <input type="number" step="any" min="0" max="100" value={discount} placeholder="optional"
                     onChange={(e) => setDiscount(e.target.value)} />
              <small>% a year (e.g. 7)</small>
            </label>
          </div>
          <div className="rbd-trains">
            <div className="rbd-trains-head">
              <b>Trains</b>
              <span className="hint">
                Optional: copy a whole chain of blocks in series — a pump with its valve and motor. A copy is another
                path alongside it into the node it feeds, so copies of a train into a 2-out-of-3 vote make it
                2-out-of-4. Pick one of identical trains.
              </span>
            </div>
            {trains.map((t, i) => (
              <div className="rbd-train" key={i}>
                <div className="rbd-train-row">
                  <input type="text" value={t.name} maxLength={80} aria-label={`Train ${i + 1} name`}
                         onChange={(e) => updateTrain(i, { name: e.target.value })} />
                  <button type="button" className="secondary" onClick={() => setTrains(trains.filter((_, j) => j !== i))}>
                    Remove
                  </button>
                </div>
                <div className="cov-chips" role="group" aria-label={`Blocks in ${t.name || `train ${i + 1}`}`}>
                  {components.map((n) => {
                    const on = t.blocks.includes(n.id);
                    const elsewhere = ownerOf[n.id] != null && ownerOf[n.id] !== i;
                    return (
                      <label key={n.id} className={"cov-chip" + (on ? " on" : "") + (elsewhere ? " disabled" : "")}
                             title={elsewhere ? `In ${trains[ownerOf[n.id]].name}` : undefined}>
                        <input type="checkbox" checked={on} disabled={elsewhere} onChange={() => toggleBlock(i, n.id)} />
                        {n.data?.label || n.id}
                      </label>
                    );
                  })}
                </div>
              </div>
            ))}
            <div className="rbd-train-row">
              <button type="button" className="secondary" onClick={addTrain} disabled={trains.length >= 6}>
                + Add a train
              </button>
              {usedTrains.length > 0 && (
                <label className="rbd-train-singles">
                  <input type="checkbox" checked={singles} onChange={(e) => setSingles(e.target.checked)} />
                  Also copy single priced blocks outside the trains
                </label>
              )}
            </div>
          </div>
          <div className="rbd-calc-actions">
            <button type="button" onClick={find} disabled={phase === "working" || horizon === ""}>
              {phase === "working" ? "Finding…" : "Find the cheapest design"}
            </button>
            <span className="hint">
              Copies are active and repaired independently; {priced.length} priced block{priced.length === 1 ? "" : "s"}
              {" "}({priced.map((n) => n.data?.label || n.id).join(", ")}){usedTrains.length > 0 && (
                <>; {usedTrains.length} train{usedTrains.length === 1 ? "" : "s"} copied whole</>
              )}.
            </span>
          </div>
        </>
      )}
      {needsPro && (
        <div className="card note" role="status">
          The cheapest design uses the exact availability and cost figures of the availability analysis —
          it's part of Pro. <Link to="/billing">Upgrade to Pro</Link>
        </div>
      )}
      {error && <div className="card error">{error}</div>}

      {result && (
        <div className={"rbd-cheapest-result" + (stale ? " stale" : "")}>
          {stale && <p className="hint">The diagram changed since this design was found — find it again.</p>}
          <p className={`rbd-compare-verdict ${result.changed ? "b_higher" : ""}`}>
            {!result.changed
              ? <>The design as drawn is already the cheapest over {fmtT(result.horizon)}{unit}{pv}: extra copies cost more than the downtime they save.</>
              : result.saving >= 0
                ? <>Adding copies saves <b>{fmtMoney(result.saving)}</b> over {fmtT(result.horizon)}{unit}{pv}: {fmtMoney(result.current.total_cost)} → <b>{fmtMoney(result.design.total_cost)}</b>.</>
                : <>Meeting {pct(result.min_availability)} availability at the lowest cost takes <b>{fmtMoney(-result.saving)}</b> more than the design as drawn (which is {pct(result.current.availability)} available).</>}
          </p>
          <div className="rbd-avail-imp-scroll">
            <table className="calc-table rbd-costs-table">
              <thead>
                <tr><th>Block</th><th>Copies now</th><th>Cheapest</th><th>Price each</th></tr>
              </thead>
              <tbody>
                {(result.design.trains || []).map((t) => (
                  <tr key={`train-${t.name}`} className={t.copies !== 1 ? "changed" : ""}>
                    <td className="calc-row-label">
                      {t.name} <small className="muted">(train: {t.blocks.map((b) => b.label).join(" → ")})</small>
                    </td>
                    <td>1</td>
                    <td>{t.copies}</td>
                    <td>{fmtMoney(t.price)}</td>
                  </tr>
                ))}
                {result.design.blocks.map((b) => (
                  <tr key={b.id} className={b.copies !== 1 ? "changed" : ""}>
                    <td className="calc-row-label">{b.label}</td>
                    <td>1</td>
                    <td>{b.copies}</td>
                    <td>{fmtMoney(b.price)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="rbd-avail-imp-scroll">
            <table className="calc-table rbd-costs-table">
              <thead>
                <tr><th></th><th>As drawn</th><th>Cheapest</th></tr>
              </thead>
              <tbody>
                <tr><td className="calc-row-label">Total cost over {fmtT(result.horizon)}{unit}{result.discount_rate > 0 && <><br /><small className="muted">present value, {result.discount_rate}% a year</small></>}</td><td>{fmtMoney(result.current.total_cost)}</td><td><b>{fmtMoney(result.design.total_cost)}</b></td></tr>
                <tr><td className="calc-row-label">Purchase</td><td>{fmtMoney(result.current.acquisition_cost)}</td><td>{fmtMoney(result.design.acquisition_cost)}</td></tr>
                <tr><td className="calc-row-label">Running cost{unit ? ` /${graph.unit.replace(/s$/, "")}` : " per unit time"}</td><td>{fmtMoney(result.current.cost_rate)}</td><td>{fmtMoney(result.design.cost_rate)}</td></tr>
                <tr><td className="calc-row-label">Long-run availability</td><td>{pct(result.current.availability)}</td><td>{pct(result.design.availability)}</td></tr>
              </tbody>
            </table>
          </div>
          {result.note && <p className="hint" style={{ margin: 0 }}>{result.note}</p>}
          {result.common_cause?.note && <p className="hint" style={{ margin: 0 }}>{result.common_cause.note}</p>}
          {result.changed && (!stale || appliedCurrent) && (
            <div className="rbd-calc-actions">
              {appliedCurrent ? (
                <>
                  <button type="button" onClick={() => onView?.()}>View on canvas</button>
                  <button type="button" className="secondary" onClick={undo}>Undo</button>
                  <span className="hint">Drawn on the canvas — review it and save when you're happy.</span>
                </>
              ) : (
                <>
                  <button type="button" onClick={apply} title="Draw these copies on the canvas — nothing is saved">
                    Apply to diagram
                  </button>
                  <span className="hint">Draws the copies on the canvas for you to review; nothing is saved.</span>
                </>
              )}
            </div>
          )}
          <p className="muted-line" style={{ margin: 0 }}>
            RePyability {result.repyability_version} · allocate_redundancy ({result.method}), up to {result.max_copies} copies
            of each priced block{result.design.trains?.length ? " and train" : ""}. Copies of a proof-tested block are tested together.{" "}
            {result.discount_rate > 0
              ? `Totals are present values at ${result.discount_rate}% a year: purchases at the start, running costs discounted continuously.`
              : "Costs aren't discounted."}
          </p>
        </div>
      )}
    </div>
  );
}

import { unitInText } from "./unitText.js";
import { horizonWords } from "../rbdOwnership.js";
import ScrollCue from "./ui/ScrollCue.jsx";
import { prefixCurrency } from "../money.js";

// Cost of ownership (#99) and the failures/maintenance downtime split (#100)
// in a repairable diagram's availability results. Shown only when the diagram
// prices or maintains something (``result.costs`` / ``result.downtime``).
// Every figure says whether it's exact (RePyability's long-run values) or
// simulated (limited repair crews for wear-out lives, say).

const CATEGORY_LABELS = {
  repair: "Repairs",
  replace: "Parts",
  preventive: "Scheduled replacement",
  inspection: "Proof tests",
  component_downtime: "Block downtime",
  setup: "Maintenance set-up",
  system_downtime: "Lost production",
};

// A cost with the workspace's currency symbol (Settings › Currency).
export const fmtMoney = (v) =>
  v == null || !Number.isFinite(v)
    ? "—"
    : prefixCurrency(Math.abs(v) >= 1000
      ? Math.round(v).toLocaleString()
      : Number(v.toPrecision(3)).toLocaleString());
const fmtPct = (v, d = 1) => (v == null || !Number.isFinite(v) ? "—" : `${(v * 100).toFixed(d)}%`);
const fmtT = (v) => (v == null || !Number.isFinite(v) ? "—" : Number(v.toPrecision(5)).toLocaleString());
const per = (unit) => (unit ? ` /${unitInText(unit).replace(/s$/, "")}` : " per unit time");
const basisTag = (basis) => (
  <span className={"rbd-basis " + (basis || "")}>{basis === "simulation" ? "simulated" : "exact"}</span>
);

// The cost of ownership over several horizons (#319): from new (RePyability's
// expected_cost, each cost discounted from when it falls) and at the long-run
// rate (total_cost), with for ever — the net present cost — when discounted.
function HorizonTable({ table, unit, disc }) {
  const rows = table?.rows || [];
  if (rows.length < 2) return null;
  const hasNew = rows.some((r) => r.from_new != null);
  return (
    <ScrollCue className="rbd-avail-imp-scroll">
      <table className="calc-table rbd-costs-table rbd-horizons-table">
        <thead>
          <tr>
            <th>Owned for</th>
            {hasNew && <th title="The expected cost of owning it from new: purchases plus every repair, part, test and hour of lost production as it falls">From new</th>}
            <th title="Purchases plus the long-run running cost over the horizon">At the long-run rate</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.endless ? "endless" : r.horizon} className={r.set ? "changed" : ""}>
              <td className="calc-row-label">
                {horizonWords(r, unit)}
                {r.set && <small className="muted"> (set)</small>}
                {r.endless && <small className="muted"> (net present cost)</small>}
              </td>
              {hasNew && <td>{r.endless ? <span className="muted" title="Worked out from new up to a finite horizon only">—</span> : fmtMoney(r.from_new)}</td>}
              <td>{fmtMoney(r.total_cost)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted-line" style={{ margin: 0 }}>
        {disc ? `Present values at ${disc}% a year. ` : ""}
        {hasNew
          ? "From new counts the early years as they are — a new system fails less (or more) than in the long run."
          : table.from_new_note || ""}
      </p>
    </ScrollCue>
  );
}

// Planned vs unplanned (the Maintenance plan's results): the system's downtime from failures vs
// from planned outages (maintenance and test time), and the running cost the same way. The split is
// Reliafy's own: the failures' downtime is a copy of the diagram whose planned work takes no time,
// and lost production is shared out as the downtime is. It says so.
export function DowntimeSplit({ result, unit }) {
  const d = result.downtime;
  if (!d) return null;
  const total = d.total || 0;
  const share = (v) => (total > 0 ? v / total : 0);
  const u = unit ? ` ${unitInText(unit)}` : "";
  const cost = result.planned_unplanned?.cost;
  const costTotal = cost ? (cost.planned || 0) + (cost.unplanned || 0) + (cost.not_split || 0) : 0;
  const bar = (label, v, of, help, planned, text) => (
    <div className="rbd-avail-bar" key={label} title={help}>
      <span className="rbd-avail-bar-label">{label}</span>
      <span className="rbd-avail-bar-track">
        <span className={"rbd-avail-bar-fill" + (planned ? " planned" : "")} style={{ width: `${Math.round((of > 0 ? v / of : 0) * 100)}%` }} />
      </span>
      <span className="rbd-avail-bar-pct">{text}</span>
    </div>
  );
  return (
    <div className="rbd-avail-nodes rbd-downtime-split">
      <div className="ds-section-h">
        Planned vs unplanned {basisTag(d.basis)}
      </div>
      <div className="rbd-split-sub">Downtime</div>
      {bar("Unplanned", d.failures, total, "Failures, including the time a hidden failure lies undetected until a proof test.", false, fmtPct(d.failures, 3))}
      {bar("Planned", d.maintenance, total, "The time scheduled replacements and proof tests take blocks off-line, where that takes the system down.", true, fmtPct(d.maintenance, 3))}
      {cost && costTotal > 0 && (
        <>
          <div className="rbd-split-sub">Running cost{per(unit)} {basisTag(cost.basis)}</div>
          {bar("Unplanned", cost.unplanned, costTotal, "Repairs and parts at failures, and the lost production failures cause.", false, fmtMoney(cost.unplanned))}
          {bar("Planned", cost.planned, costTotal, "Scheduled replacements, proof tests and condition inspections, and the lost production planned outages cause.", true, fmtMoney(cost.planned))}
          {cost.not_split > 0 && bar("Not split", cost.not_split, costTotal, "Maintenance-group set-up costs (charged at failures and planned work alike) and blocks' own downtime costs.", false, fmtMoney(cost.not_split))}
        </>
      )}
      <p className="muted-line" style={{ margin: 0 }}>
        Of the {fmtPct(total, 3)} unavailability, {fmtPct(share(d.failures))} comes from failures and{" "}
        {fmtPct(share(d.maintenance))} from maintenance and test time
        {d.planned_outages_per_window != null && ` (${fmtT(d.planned_outages_per_window)} planned outages of the system per ${fmtT(result.t_simulation)}${u} window)`}.
        {" "}Split by Reliafy:{" "}
        {d.basis === "simulation" && d.paired_simulations
          ? `the first ${d.paired_simulations.toLocaleString()} histories re-run with planned work taking no time`
          : "the failures' share is the same diagram with planned work taking no time"}
        {cost?.lost_production ? "; lost production is shared out in the same proportions" : ""}.
      </p>
    </div>
  );
}

// What the scheduled replacements buy against running to failure (exact long-run values): failures
// avoided, by block and for the system, and the downtime and running cost with and without them.
export function PlanEffect({ result, unit }) {
  const e = result.plan_effect;
  if (!e) return null;
  if (!e.available) {
    return (
      <div className="rbd-avail-nodes rbd-plan-effect">
        <div className="ds-section-h">What the plan buys</div>
        <p className="muted-line" style={{ margin: 0 }}>{e.reason}</p>
      </div>
    );
  }
  // Per year where the diagram's unit is a calendar one, else per unit time.
  const yearly = e.units_per_year != null;
  const scale = yearly ? e.units_per_year : 1;
  const perTxt = yearly ? " a year" : unit ? ` per ${unitInText(unit).replace(/s$/, "")}` : " per unit time";
  const n = (v) => (v == null || !Number.isFinite(v) ? "—" : Number((v * scale).toPrecision(3)).toLocaleString());
  const sys = e.system_failures;
  const una = e.unavailability;
  const c = e.cost_rate;
  return (
    <div className="rbd-avail-nodes rbd-plan-effect">
      <div className="ds-section-h">What the plan buys {basisTag(e.basis)}</div>
      <div className="rbd-avail-metrics">
        <div className="alt-metric" title={`Block failures${perTxt} with the scheduled replacements, against running every block to failure`}>
          <span className="k">Failures avoided{perTxt}</span>
          <span className="v">{n(e.block_failures_avoided)}</span>
        </div>
        <div className="alt-metric" title="The system's failures with the plan, and running to failure">
          <span className="k">System failures{perTxt}</span>
          <span className="v">{n(sys.with_plan)} <small className="muted">vs {n(sys.run_to_failure)}</small></span>
        </div>
        <div className="alt-metric" title="Long-run unavailability with the plan, and running to failure">
          <span className="k">Unavailability</span>
          <span className="v">{fmtPct(una.with_plan, 3)} <small className="muted">vs {fmtPct(una.run_to_failure, 3)}</small></span>
        </div>
        {c && (
          <div className="alt-metric" title="Long-run running cost with the plan, and running to failure">
            <span className="k">Running cost{per(unit)}</span>
            <span className="v">{fmtMoney(c.with_plan)} <small className="muted">vs {fmtMoney(c.run_to_failure)}</small></span>
          </div>
        )}
      </div>
      {e.blocks.length > 0 && (
        <ScrollCue className="rbd-avail-imp-scroll">
          <table className="calc-table rbd-costs-table">
            <thead>
              <tr>
                <th>Block</th>
                <th title="Its failures with the scheduled replacement">Failures{perTxt}</th>
                <th title="Its failures if it ran to failure">Run to failure</th>
                <th>Avoided</th>
              </tr>
            </thead>
            <tbody>
              {e.blocks.map((b) => (
                <tr key={b.id}>
                  <td className="calc-row-label">{b.label}</td>
                  <td>{n(b.failures_with_plan)}</td>
                  <td>{n(b.failures_run_to_failure)}</td>
                  <td>{n(b.failures_avoided)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollCue>
      )}
      <p className="muted-line" style={{ margin: 0 }}>
        Against the same diagram with no scheduled replacements (proof tests kept), in the long run.
        {una.with_plan > una.run_to_failure ? " Here the plan costs more downtime than it saves: its work takes longer than the failures it avoids." : ""}
      </p>
    </div>
  );
}

export default function AvailabilityCosts({ result, unit }) {
  const c = result.costs;
  if (!c) return null;
  const u = unit ? ` ${unitInText(unit)}` : "";
  const sim = c.simulated;
  // The window's mean cost is exact (RePyability's expected_cost) where it can
  // be; the interval and percentiles are the simulation's.
  const simMeanExact = !!sim && !!sim.mean_basis && sim.mean_basis !== "simulation";
  const cats = Object.entries(c.by_category || {}).filter(([, v]) => v > 0);
  const catTotal = cats.reduce((s, [, v]) => s + v, 0);
  const blocks = c.blocks || [];
  const hasAcq = c.acquisition_cost > 0;
  // A discount rate (% a year, #219) makes the total a present value.
  const disc = c.discount_rate > 0 ? c.discount_rate : null;
  // From new where RePyability has it (#319), else at the long-run rate; a
  // simulated rate has no present value (the undiscounted total stands).
  const fromNew = c.total_cost_from_new != null;
  const noPv = c.total_cost == null && c.present_value_note;
  const total = fromNew ? c.total_cost_from_new : noPv ? c.undiscounted_total_cost : c.total_cost;
  const totalTitle = fromNew
    ? `The expected cost of owning it from new: purchases plus every cost as it falls over ${fmtT(c.horizon)}${u}${disc ? `, discounted at ${disc}% a year` : ""}. At the long-run rate: ${fmtMoney(c.total_cost)}.`
    : noPv ? c.present_value_note
    : `Purchase prices + running cost over ${fmtT(c.horizon)}${u}${disc ? `, discounted at ${disc}% a year (present value; undiscounted ${fmtMoney(c.undiscounted_total_cost)})` : ""}${c.horizon_basis === "window" ? " (the simulated window — set an ownership horizon under Costs on the Builder tab)" : ""}`;

  return (
    <div className="rbd-costs">
      <div className="ds-section-h">Cost of ownership</div>
      <div className="rbd-avail-metrics">
        {c.priced && (
          <div className="alt-metric" title={c.cost_rate_basis === "exact" ? "Exact long-run cost per unit time" : "Simulated mean cost per unit time over the window"}>
            <span className="k">Running cost {basisTag(c.cost_rate_basis)}</span>
            <span className="v">{fmtMoney(c.cost_rate)}{per(unit)}</span>
          </div>
        )}
        <div className="alt-metric" title={totalTitle}>
          <span className="k">
            Total cost over {fmtT(c.horizon)}{u}
            {disc && !noPv && <> <span className="rbd-basis">PV {disc}%/yr</span></>}
            {fromNew && <> <span className="rbd-basis">from new</span></>}
          </span>
          <span className="v">{fmtMoney(total)}</span>
        </div>
        {hasAcq && (
          <div className="alt-metric" title="Sum of the blocks' purchase prices">
            <span className="k">Purchase</span>
            <span className="v">{fmtMoney(c.acquisition_cost)}</span>
          </div>
        )}
        {sim && (
          <div className="alt-metric" title={`Cost of a ${fmtT(sim.t_simulation)}${u} window from new: the mean (${simMeanExact ? "exact" : "simulated"}), and the simulated budget 9 windows in 10 stay under`}>
            <span className="k">Window cost {basisTag(simMeanExact ? "exact" : "simulation")}</span>
            <span className="v">{fmtMoney(sim.mean)} <small className="muted">P90 {fmtMoney(sim.percentiles?.["90"])}</small></span>
          </div>
        )}
      </div>

      <HorizonTable table={c.by_horizon} unit={unit} disc={noPv ? null : disc} />

      {cats.length > 0 && (
        <div className="rbd-avail-nodes">
          {cats.map(([k, v]) => (
            <div className="rbd-avail-bar" key={k}>
              <span className="rbd-avail-bar-label">{CATEGORY_LABELS[k] || k}</span>
              <span className="rbd-avail-bar-track">
                <span className="rbd-avail-bar-fill cost" style={{ width: `${Math.round((v / (catTotal || 1)) * 100)}%` }} />
              </span>
              <span className="rbd-avail-bar-pct">{fmtPct(v / (catTotal || 1), 0)}</span>
            </div>
          ))}
        </div>
      )}

      {blocks.length > 0 && (
        <ScrollCue className="rbd-avail-imp-scroll">
          <table className="calc-table rbd-costs-table">
            <thead>
              <tr>
                <th>Block</th>
                <th title="The block's own running cost: its repairs, parts, scheduled replacements, proof tests and own downtime (lost production is the system's)">Cost{per(unit)}</th>
                <th title="Its share of the blocks' running cost">Share of cost</th>
                <th title="Its share of the system's downtime (exact failure-oriented criticality where available, else simulated)">Share of downtime</th>
                {hasAcq && <th>Purchase</th>}
              </tr>
            </thead>
            <tbody>
              {blocks.map((b) => (
                <tr key={b.id}>
                  <td className="calc-row-label">{b.label}</td>
                  <td>{fmtMoney(b.rate)}</td>
                  <td>{fmtPct(b.cost_share)}</td>
                  <td>{fmtPct(b.downtime_share)}</td>
                  {hasAcq && <td>{b.acquisition ? fmtMoney(b.acquisition) : "—"}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollCue>
      )}

      <p className="muted-line" style={{ margin: 0 }}>
        {c.priced
          ? c.cost_rate_basis === "exact"
            ? "The running cost is RePyability's exact long-run rate"
            : "The running cost is the simulated mean — this diagram has no exact long-run value (limited repair crews for wear-out lives, say)"
          : "Nothing is priced per failure or per hour"}
        {c.downtime_cost_rate > 0 && `; lost production is ${fmtMoney(c.downtime_cost_rate)}${per(unit)} of system downtime`}.{" "}
        The total cost of ownership is the purchase prices plus the running costs over {fmtT(c.horizon)}{u}
        {c.horizon_basis === "window" ? " (the simulated window; set an ownership horizon under Costs on the Builder tab)" : ""}
        {fromNew ? ", from new" : ", at that rate"}
        {noPv
          ? <>, undiscounted. {c.present_value_note}</>
          : disc
          ? <>, as a present value at {disc}% a year: the purchases at the start and the running costs discounted ({fmtMoney(c.undiscounted_total_cost)} undiscounted at the long-run rate).{c.present_value_note ? ` ${c.present_value_note}` : ""}{sim ? " The window's cost isn't discounted." : ""}</>
          : ", undiscounted."}
        {sim && sim.lower != null && (simMeanExact
          ? ` A ${fmtT(sim.t_simulation)}${u} window from new costs ${fmtMoney(sim.mean)} on average (exact; the simulation's ${Math.round((sim.confidence || 0.95) * 100)}% CI ${fmtMoney(sim.lower)} to ${fmtMoney(sim.upper)}); 1 simulated window in 10 costs more than ${fmtMoney(sim.percentiles?.["90"])}.`
          : ` A simulated ${fmtT(sim.t_simulation)}${u} window from new costs ${fmtMoney(sim.mean)} on average (${Math.round((sim.confidence || 0.95) * 100)}% CI ${fmtMoney(sim.lower)} to ${fmtMoney(sim.upper)}); 1 window in 10 costs more than ${fmtMoney(sim.percentiles?.["90"])}.`)}
      </p>
    </div>
  );
}

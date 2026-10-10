import { unitInText } from "./unitText.js";
import { horizonWords } from "../rbdOwnership.js";

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

export const fmtMoney = (v) =>
  v == null || !Number.isFinite(v)
    ? "—"
    : Math.abs(v) >= 1000
      ? Math.round(v).toLocaleString()
      : Number(v.toPrecision(3)).toLocaleString();
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
    <div className="rbd-avail-imp-scroll">
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
    </div>
  );
}

// Downtime from failures vs from planned outages (maintenance and test time).
export function DowntimeSplit({ result, unit }) {
  const d = result.downtime;
  if (!d) return null;
  const total = d.total || 0;
  const share = (v) => (total > 0 ? v / total : 0);
  const u = unit ? ` ${unitInText(unit)}` : "";
  return (
    <div className="rbd-avail-nodes rbd-downtime-split">
      <div className="ds-section-h">
        Downtime: failures vs maintenance
      </div>
      {[
        ["Failures", d.failures, "Unplanned: failures, including the time a hidden failure lies undetected until a proof test."],
        ["Maintenance & tests", d.maintenance, "Planned outages: the time scheduled replacements and proof tests take the block off-line."],
      ].map(([label, v, help]) => (
        <div className="rbd-avail-bar" key={label} title={help}>
          <span className="rbd-avail-bar-label">{label}</span>
          <span className="rbd-avail-bar-track">
            <span className={"rbd-avail-bar-fill" + (label === "Failures" ? "" : " planned")} style={{ width: `${Math.round(share(v) * 100)}%` }} />
          </span>
          <span className="rbd-avail-bar-pct">{fmtPct(v, 3)}</span>
        </div>
      ))}
      <p className="muted-line" style={{ margin: 0 }}>
        Of the {fmtPct(total, 3)} unavailability, {fmtPct(share(d.failures))} comes from failures and{" "}
        {fmtPct(share(d.maintenance))} from maintenance and test time
        {d.planned_outages_per_window != null && ` (${fmtT(d.planned_outages_per_window)} planned outages of the system per ${fmtT(result.t_simulation)}${u} window)`}.
        {d.basis === "simulation" && d.paired_simulations
          ? ` Estimated by re-running the first ${d.paired_simulations.toLocaleString()} histories with instant maintenance.`
          : " The failures' share is the same diagram with maintenance taking no time."}
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
        <div className="rbd-avail-imp-scroll">
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
        </div>
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
          ? <>, as a present value at {disc}% a year: the purchases at the start and the running costs discounted ({fmtMoney(c.undiscounted_total_cost)} undiscounted at the long-run rate).{sim ? " The window's cost isn't discounted." : ""}</>
          : ", undiscounted."}
        {sim && sim.lower != null && (simMeanExact
          ? ` A ${fmtT(sim.t_simulation)}${u} window from new costs ${fmtMoney(sim.mean)} on average (exact; the simulation's ${Math.round((sim.confidence || 0.95) * 100)}% CI ${fmtMoney(sim.lower)} to ${fmtMoney(sim.upper)}); 1 simulated window in 10 costs more than ${fmtMoney(sim.percentiles?.["90"])}.`
          : ` A simulated ${fmtT(sim.t_simulation)}${u} window from new costs ${fmtMoney(sim.mean)} on average (${Math.round((sim.confidence || 0.95) * 100)}% CI ${fmtMoney(sim.lower)} to ${fmtMoney(sim.upper)}); 1 window in 10 costs more than ${fmtMoney(sim.percentiles?.["90"])}.`)}
      </p>
    </div>
  );
}

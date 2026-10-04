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
const per = (unit) => (unit ? ` /${unit.replace(/s$/, "")}` : " per unit time");
const basisTag = (basis) => (
  <span className={"rbd-basis " + (basis || "")}>{basis === "simulation" ? "simulated" : "exact"}</span>
);

// Downtime from failures vs from planned outages (maintenance and test time).
export function DowntimeSplit({ result, unit }) {
  const d = result.downtime;
  if (!d) return null;
  const total = d.total || 0;
  const share = (v) => (total > 0 ? v / total : 0);
  const u = unit ? ` ${unit}` : "";
  return (
    <div className="rbd-avail-nodes rbd-downtime-split">
      <div className="ds-section-h">
        Downtime: failures vs maintenance {basisTag(d.basis)}
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
  const u = unit ? ` ${unit}` : "";
  const sim = c.simulated;
  // The window's mean cost is exact (RePyability's expected_cost) where it can
  // be; the interval and percentiles are the simulation's.
  const simMeanExact = !!sim && !!sim.mean_basis && sim.mean_basis !== "simulation";
  const cats = Object.entries(c.by_category || {}).filter(([, v]) => v > 0);
  const catTotal = cats.reduce((s, [, v]) => s + v, 0);
  const blocks = c.blocks || [];
  const hasAcq = c.acquisition_cost > 0;

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
        <div className="alt-metric" title={`Purchase prices + running cost over ${fmtT(c.horizon)}${u}${c.horizon_basis === "window" ? " (the simulated window — set an ownership horizon under Costs on the Builder tab)" : ""}`}>
          <span className="k">Total cost over {fmtT(c.horizon)}{u}</span>
          <span className="v">{fmtMoney(c.total_cost)}</span>
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
        The total cost of ownership is the purchase prices plus that rate over {fmtT(c.horizon)}{u}
        {c.horizon_basis === "window" ? " (the simulated window; set an ownership horizon under Costs on the Builder tab)" : ""}, undiscounted.
        {sim && sim.lower != null && (simMeanExact
          ? ` A ${fmtT(sim.t_simulation)}${u} window from new costs ${fmtMoney(sim.mean)} on average (exact; the simulation's ${Math.round((sim.confidence || 0.95) * 100)}% CI ${fmtMoney(sim.lower)} to ${fmtMoney(sim.upper)}); 1 simulated window in 10 costs more than ${fmtMoney(sim.percentiles?.["90"])}.`
          : ` A simulated ${fmtT(sim.t_simulation)}${u} window from new costs ${fmtMoney(sim.mean)} on average (${Math.round((sim.confidence || 0.95) * 100)}% CI ${fmtMoney(sim.lower)} to ${fmtMoney(sim.upper)}); 1 window in 10 costs more than ${fmtMoney(sim.percentiles?.["90"])}.`)}
      </p>
    </div>
  );
}

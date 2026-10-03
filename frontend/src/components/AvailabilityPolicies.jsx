// What an availability result adds for repair crews, maintenance policies and
// safety functions (#156, #157): how RePyability found the long-run values
// (exactly, numerically, by simulation — and why), the repair crews and the
// jobs they share, opportunistic renewals, and a safety function's PFDavg
// with its SIL band. Each part shows only when the result carries it.

const ROUTE_LABELS = {
  exact: "Exact",
  numerical: "Numerical",
  simulated: "Simulated",
  refused: "Simulated",
};

const fmtPfd = (v) => (v == null || !Number.isFinite(v) ? "—" : v < 1e-3 ? v.toExponential(2) : v.toPrecision(3));
const fmtN = (v) => (v == null || !Number.isFinite(v) ? "—" : Number(v.toPrecision(3)).toLocaleString());

function SafetyCard({ safety }) {
  const met = safety.meets_target;
  return (
    <div className="rbd-policy-card rbd-sif">
      <div className="ds-section-h">Safety function</div>
      <div className="rbd-sif-row">
        <div>
          <div className="rbd-sif-big">{fmtPfd(safety.pfd_avg)}</div>
          <div className="muted">PFDavg (average probability of failure on demand)</div>
        </div>
        <div className={"rbd-sil-chip" + (safety.sil ? ` sil${safety.sil}` : " none")}>
          {safety.sil ? `SIL ${safety.sil}` : "No SIL"}
        </div>
        {safety.target_sil != null && (
          <div className={"rbd-sil-target " + (met ? "ok" : "no")}>
            Target SIL {safety.target_sil}: {met ? "met" : "not met"}
          </div>
        )}
      </div>
      <ul className="rbd-policy-notes">
        <li>
          {safety.basis === "simulated" ? "Simulated" : safety.basis === "numerical" ? "Numerical" : "Exact"} — the
          long-run unavailability averaged over the proof-test cycle (low-demand SIL bands, IEC 61508).
        </li>
        {safety.proof_tested_blocks > 0 && (
          <li>
            {safety.proof_tested_blocks} proof-tested block{safety.proof_tested_blocks === 1 ? "" : "s"}
            {safety.staggered ? " · tests staggered" : ""}
            {safety.imperfect_tests ? " · imperfect tests (coverage below 100%)" : ""}
          </li>
        )}
        {safety.common_cause && (
          <li>
            {safety.common_cause.included
              ? `Includes ${safety.common_cause.groups} common-cause group${safety.common_cause.groups === 1 ? "" : "s"}.`
              : `Common cause left out: ${safety.common_cause.note}`}
          </li>
        )}
      </ul>
    </div>
  );
}

export default function AvailabilityPolicies({ result }) {
  const method = result.long_run_method;
  const crews = result.repair_crews;
  const safety = result.safety;
  const renewals = result.opportunistic_renewals;
  const showMethod = method && (crews || safety || renewals || method.route !== "exact");
  if (!showMethod && !crews && !safety && !renewals) return null;
  return (
    <div className="rbd-avail-nodes rbd-policies">
      {safety && <SafetyCard safety={safety} />}
      {crews && (
        <div className="rbd-policy-card">
          <div className="ds-section-h">Repair crews</div>
          <p className="rbd-policy-line">
            <b>{crews.crews}</b> crew{crews.crews === 1 ? "" : "s"} for {crews.jobs} repair job
            {crews.jobs === 1 ? "" : "s"} ({crews.blocks} block{crews.blocks === 1 ? "" : "s"}) —{" "}
            {crews.limited ? "a failed block can wait for a crew, down, until one is free." : "never short: no repair waits."}
          </p>
          {Object.keys(crews.priorities || {}).length > 0 && (
            <p className="muted">
              Priority: {Object.entries(crews.priorities).sort((a, b) => b[1] - a[1])
                .map(([label, p]) => `${label} (${p})`).join(", ")}
            </p>
          )}
          {crews.own_repairer?.length > 0 && (
            <p className="muted">Own repairer, one unit at a time: {crews.own_repairer.join(", ")}</p>
          )}
        </div>
      )}
      {renewals && (
        <div className="rbd-policy-card">
          <div className="ds-section-h">Opportunistic renewals</div>
          <p className="muted">Early renewals at a group stop, per simulated window:{" "}
            {Object.entries(renewals).map(([label, n]) => `${label} ${fmtN(n)}`).join(" · ")}
          </p>
        </div>
      )}
      {showMethod && (
        <div className="rbd-policy-card">
          <div className="ds-section-h">
            How the long-run values are found{" "}
            <span className={"rbd-basis " + (method.route === "exact" || method.route === "numerical" ? "" : "simulation")}>
              {ROUTE_LABELS[method.route] || method.route}
            </span>
          </div>
          <p className="muted rbd-policy-reason">
            {method.route === "refused" ? "No exact long-run values, so the simulation gives them: " : ""}
            {method.reason}
            {method.blocks?.length ? ` (${method.blocks.join(", ")})` : ""}
          </p>
        </div>
      )}
    </div>
  );
}

// What an availability result adds for repair crews, maintenance policies and
// safety functions (#156, #157): how RePyability found the long-run values
// (exactly, numerically, by simulation — and why), the repair crews and the
// jobs they share, opportunistic renewals, and a safety function's notes (its
// PFDavg and SIL lead the calculator, #311). Each part shows only when the
// result carries it.

const ROUTE_LABELS = {
  exact: "Exact",
  numerical: "Numerical",
  simulated: "Simulated",
  refused: "Simulated",
};

const fmtPfd = (v) => (v == null || !Number.isFinite(v) ? "—" : v < 1e-3 ? v.toExponential(2) : v.toPrecision(3));
const fmtN = (v) => (v == null || !Number.isFinite(v) ? "—" : Number(v.toPrecision(3)).toLocaleString());

// A safety function's notes, folded under Details: the PFDavg itself, its SIL
// and any caveat are the calculator's answer card (#311).
export function SafetyNotes({ safety }) {
  const ccfLeftOut = safety.common_cause_included === false || (safety.common_cause && !safety.common_cause.included);
  return (
    <div className="rbd-policy-card">
      <div className="ds-section-h">Safety function</div>
      <ul className="rbd-policy-notes">
        <li>
          PFDavg {fmtPfd(safety.pfd_avg)}: the long-run unavailability averaged over the proof-test cycle
          (low-demand SIL bands, IEC 61508), {safety.basis === "simulated" ? "simulated" : safety.basis === "numerical" ? "numerical" : "exact"}.
        </li>
        {!ccfLeftOut && safety.common_cause?.included && (
          <li>
            Includes {safety.common_cause.groups} common-cause group{safety.common_cause.groups === 1 ? "" : "s"}.
          </li>
        )}
        {!ccfLeftOut && !safety.common_cause && safety.common_cause_included && <li>Common cause included.</li>}
        {safety.proof_tested_blocks > 0 && (
          <li>
            {safety.proof_tested_blocks} proof-tested block{safety.proof_tested_blocks === 1 ? "" : "s"}
            {safety.staggered ? " · tests staggered" : ""}
            {safety.imperfect_tests ? " · imperfect tests (coverage below 100%)" : ""}
          </li>
        )}
      </ul>
    </div>
  );
}

export default function AvailabilityPolicies({ result }) {
  const method = result.long_run_method;
  const crews = result.repair_crews;
  const renewals = result.opportunistic_renewals;
  const showMethod = method && (crews || result.safety || renewals || method.route !== "exact");
  if (!showMethod && !crews && !renewals) return null;
  return (
    <div className="rbd-avail-nodes rbd-policies">
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
            How the long-run values are found: {(ROUTE_LABELS[method.route] || method.route).toLowerCase()}
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

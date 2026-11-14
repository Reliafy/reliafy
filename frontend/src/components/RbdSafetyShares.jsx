import { formatPercent } from "../format.js";
import ScrollCue from "./ui/ScrollCue.jsx";

// "Where the PFDavg comes from" (#298): each element's share of a safety
// function's PFDavg and of its dangerous failures, with each common-cause
// group's on a row of its own — the backend's ``safety.shares``. Both columns
// add up to 100%. A column the engine couldn't give is left out with its reason.
export default function RbdSafetyShares({ shares }) {
  const elements = shares?.elements || [];
  const groups = shares?.common_cause || [];
  if (!elements.length) return null;
  const hasPfd = elements.some((r) => r.pfd_share != null) || groups.some((g) => g.pfd_share != null);
  const hasFail = elements.some((r) => r.failure_share != null) || groups.some((g) => g.failure_share != null);
  // The largest share of the PFDavg, a common cause included.
  const top = [...elements, ...groups.map((g) => ({ ...g, label: `The common cause of ${g.label}` }))]
    .filter((r) => r.pfd_share != null)
    .sort((a, b) => b.pfd_share - a.pfd_share)[0];
  return (
    <div className="rbd-sif-shares">
      <div className="ds-section-h">Where the PFDavg comes from</div>
      {hasPfd && top?.pfd_share != null && (
        <p className="rbd-details-p">
          <b>{top.label}</b> makes up {formatPercent(top.pfd_share)} of the PFDavg: a shorter proof-test interval, a
          better element or more redundancy there does the most good.
        </p>
      )}
      <ScrollCue className="rbd-avail-imp-scroll">
        <table className="calc-table rbd-sif-shares-table">
          <thead>
            <tr>
              <th>Element</th>
              {hasPfd && (
                <th title="This element's part of the PFDavg, with each common-cause group's on its own row. Redundant channels split the time they are down together. These add up to 100%.">
                  Share of PFDavg
                </th>
              )}
              {hasFail && (
                <th title="This element's share of the function's dangerous failures in the long run, with each common-cause group's on its own row. These add up to 100%.">
                  Share of dangerous failures
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {elements.map((r) => (
              <tr key={r.id}>
                <td className="calc-row-label">{r.label}</td>
                {hasPfd && (
                  <td>
                    <span className="rbd-sif-bar" style={{ "--share": Math.max(0, Math.min(1, r.pfd_share || 0)) }}
                          aria-hidden="true" />
                    {formatPercent(r.pfd_share)}
                  </td>
                )}
                {hasFail && <td>{formatPercent(r.failure_share)}</td>}
              </tr>
            ))}
            {groups.map((g) => (
              <tr key={g.members.join("+")}>
                <td className="calc-row-label">Common cause: {g.label}</td>
                {hasPfd && (
                  <td>
                    <span className="rbd-sif-bar" style={{ "--share": Math.max(0, Math.min(1, g.pfd_share || 0)) }}
                          aria-hidden="true" />
                    {formatPercent(g.pfd_share)}
                  </td>
                )}
                {hasFail && <td>{formatPercent(g.failure_share)}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollCue>
      {!hasPfd && shares.pfd_share_reason && (
        <p className="rbd-details-p muted">No share of the PFDavg: {shares.pfd_share_reason}</p>
      )}
      {!hasFail && shares.failure_share_reason && (
        <p className="rbd-details-p muted">No share of the dangerous failures: {shares.failure_share_reason}</p>
      )}
    </div>
  );
}

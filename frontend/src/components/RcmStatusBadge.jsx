// Evidence-status badge for an RCM decision, reusing the health-badge palette.
const STATUS = {
  supported: { label: "supported", cls: "health-green" },
  contradicted: { label: "contradicted", cls: "health-red" },
  inconclusive: { label: "inconclusive", cls: "health-amber" },
  unevidenced: { label: "no evidence", cls: "health-amber" },
  stale: { label: "stale link", cls: "health-grey" },
};

export default function RcmStatusBadge({ status }) {
  if (!status) return null;
  const s = STATUS[status] || { label: status, cls: "health-grey" };
  return <span className={`health-badge ${s.cls}`}>{s.label}</span>;
}

export function RollupBadges({ rollup }) {
  if (!rollup) return null;
  const parts = [
    ["supported", rollup.supported, "health-green"],
    ["contradicted", rollup.contradicted, "health-red"],
    ["inconclusive", (rollup.inconclusive || 0) + (rollup.unevidenced || 0), "health-amber"],
    ["stale", rollup.stale, "health-grey"],
  ].filter(([, n]) => n > 0);
  if (!parts.length) return null;
  return (
    <span className="rollup-badges">
      {parts.map(([label, n, cls]) => (
        <span key={label} className={`health-badge ${cls}`}>{n} {label}</span>
      ))}
    </span>
  );
}

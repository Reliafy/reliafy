import Chip from "./ui/Chip.jsx";

// Evidence status of an RCM decision, as a Chip: green only when the evidence
// supports the decision, red when it contradicts it, amber when it's missing
// or inconclusive.
const STATUS = {
  supported: { label: "Supported", tone: "success" },
  contradicted: { label: "Contradicted", tone: "danger" },
  inconclusive: { label: "Inconclusive", tone: "warning" },
  unevidenced: { label: "No evidence", tone: "warning" },
  stale: { label: "Stale link", tone: "neutral" },
};

export default function RcmStatusBadge({ status }) {
  if (!status) return null;
  const s = STATUS[status] || { label: status, tone: "neutral" };
  return <Chip tone={s.tone}>{s.label}</Chip>;
}

export function RollupBadges({ rollup }) {
  if (!rollup) return null;
  const parts = [
    ["supported", rollup.supported, "success"],
    ["contradicted", rollup.contradicted, "danger"],
    ["inconclusive", (rollup.inconclusive || 0) + (rollup.unevidenced || 0), "warning"],
    ["stale", rollup.stale, "neutral"],
  ].filter(([, n]) => n > 0);
  if (!parts.length) return null;
  return (
    <span className="chip-row">
      {parts.map(([label, n, tone]) => (
        <Chip key={label} tone={tone}>{n} {label}</Chip>
      ))}
    </span>
  );
}

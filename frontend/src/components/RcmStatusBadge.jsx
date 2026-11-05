import Chip from "./ui/Chip.jsx";

// Evidence status of an RCM decision, as a Chip: green only when the evidence
// supports the decision, red when it contradicts it, amber when it's
// inconclusive; grey when nothing is linked yet (not a warning: most RCM is
// done from judgement) or the link has gone.
const STATUS = {
  supported: { label: "Supported", tone: "success" },
  contradicted: { label: "Contradicted", tone: "danger" },
  inconclusive: { label: "Inconclusive", tone: "warning" },
  unevidenced: { label: "Not linked", tone: "neutral" },
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
    // Only linked evidence: a decision with nothing linked yet isn't inconclusive.
    ["inconclusive", rollup.inconclusive, "warning"],
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

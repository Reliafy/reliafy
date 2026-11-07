import Chip from "./ui/Chip.jsx";
import { LINKED_LABEL } from "../rcmWorksheet.js";

// Evidence status of an RCM decision, as a Chip: green only when the evidence
// supports the decision, red when it contradicts it, amber when it's
// inconclusive; grey when nothing is linked yet (not a warning: most RCM is
// done from judgement) or the link has gone. A linked report or working is
// grey too: it's linked, not checked, so it never claims to support anything.
const STATUS = {
  supported: { label: "Supported", tone: "success" },
  contradicted: { label: "Contradicted", tone: "danger" },
  inconclusive: { label: "Inconclusive", tone: "warning" },
  unevidenced: { label: "Not linked", tone: "neutral" },
  stale: { label: "Stale link", tone: "neutral" },
  linked: { label: "Linked", tone: "neutral" },
  // A combination of tasks with evidence for some of its tasks, not all: a nudge, not a fault.
  partly: { label: "Partly evidenced", tone: "neutral" },
};

// kind: what's linked (the read's evidence_kind), naming a linked-only one.
export default function RcmStatusBadge({ status, kind = null }) {
  if (!status) return null;
  const s = status === "linked" && LINKED_LABEL[kind] ? { label: LINKED_LABEL[kind], tone: "neutral" }
    : STATUS[status] || { label: status, tone: "neutral" };
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

import Chip from "./ui/Chip.jsx";
import { LINKED_LABEL } from "../rcmWorksheet.js";

// Evidence status of an RCM decision, as a Chip: green only when the evidence
// supports the decision, red when it contradicts it, amber when it's
// inconclusive or a fixed interval is far from its cost-optimal one (a fact,
// not a verdict: the analyst decides); grey when nothing is linked yet (not a warning: most RCM is
// done from judgement) or the link has gone. A linked report or working is
// grey too: it's linked, not checked, so it never claims to support anything.
const STATUS = {
  supported: { label: "Supported", tone: "success" },
  contradicted: { label: "Contradicted", tone: "danger" },
  inconclusive: { label: "Inconclusive", tone: "warning" },
  shorter_than_evidence: { label: "Shorter than its evidence", tone: "warning" },
  longer_than_evidence: { label: "Longer than its evidence", tone: "warning" },
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

// gap: the tasks at and below that serve no failure mode ({n, onClick}: a neutral chip, a fact
// not a verdict, that opens them on the Maintenance tab).
export function RollupBadges({ rollup, gap = null }) {
  const gapChip = gap?.n > 0 ? (
    <Chip tone="neutral" onClick={gap.onClick} data-testid="rcm-gap-chip"
          title="Tasks here and below that serve no failure mode yet: open them on the Maintenance tab">
      {gap.n} {gap.n === 1 ? "task" : "tasks"} not linked to a failure mode
    </Chip>
  ) : null;
  if (!rollup) return gapChip ? <span className="chip-row">{gapChip}</span> : null;
  const parts = [
    ["supported", rollup.supported, "success"],
    ["contradicted", rollup.contradicted, "danger"],
    // Only linked evidence: a decision with nothing linked yet isn't inconclusive.
    ["inconclusive", rollup.inconclusive, "warning"],
    // A fixed interval far from its cost-optimal one, either way.
    ["interval differs", (rollup.shorter_than_evidence || 0) + (rollup.longer_than_evidence || 0), "warning"],
    ["stale", rollup.stale, "neutral"],
  ].filter(([, n]) => n > 0);
  if (!parts.length && !gapChip) return null;
  return (
    <span className="chip-row">
      {parts.map(([label, n, tone]) => (
        <Chip key={label} tone={tone}>{n} {label}</Chip>
      ))}
      {gapChip}
    </span>
  );
}

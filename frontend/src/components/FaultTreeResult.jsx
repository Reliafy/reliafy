// A saved fault tree's analysis, read-only: the answer first (one sentence
// and three tiles), its notes, the tree drawn and the cut sets. The editor
// (views/FaultTreeEditor.jsx) and a report's fault tree section (the share
// page) both say the top event the same way.
import { ReactFlowProvider } from "reactflow";
import "reactflow/dist/style.css";
import ResultSummary from "./ui/ResultSummary.jsx";
import { CutSetTable, TreeCanvas } from "./RbdFaultTree.jsx";
import { formatNumber, formatPercent } from "../format.js";
import { plainUnit } from "../faultTree.js";
import "./RbdFaultTree.css";

// A share as a percentage with one decimal where it matters: 0.1025 → "10.3%".
const pct = (x) => `${formatNumber(x * 100, { sig: 3 })}%`;

// The answer first (as the prediction pages give it): one sentence, then
// three tiles — the top event's probability, the reliability and the cut sets.
export function topEventAnswer(result, unitWord) {
  const p = result.top_event_probability;
  const timed = result.kind === "reliability";
  const when = timed ? `${formatNumber(result.t)}${unitWord ? ` ${unitWord}` : ""}` : "";
  const events = Object.fromEntries((result.events || []).map((e) => [e.id, e]));
  const cuts = result.cut_sets || {};
  const lead = cuts.basis !== "low_order" ? cuts.listed?.[0] : null;
  const leadLabel = lead ? lead.events.map((id) => events[id]?.label || id).join(" + ") : null;
  const sentence = p == null ? (
    <>The top event's probability couldn't be worked out.</>
  ) : (
    <>
      {timed ? <>By {when}, the top event has a <b>{pct(p)}</b> chance of having occurred (reliability <b>{pct(1 - p)}</b>).</>
             : <>The top event has a <b>{pct(p)}</b> chance of occurring (<b>{pct(1 - p)}</b> that it doesn't). Every basic event is a fixed probability, so time doesn't enter.</>}
      {lead && lead.share != null && <> The most likely cause is <b>{leadLabel}</b>, {formatPercent(lead.share)} of that.</>}
    </>
  );
  const tiles = [
    { label: timed ? `Top event probability by ${when}` : "Top event probability",
      value: formatNumber(p, { sig: 4 }), hint: timed ? "chance it has occurred by then" : "chance it occurs" },
    { label: "Reliability", value: p == null ? "—" : formatNumber(1 - p, { sig: 4 }), hint: "1 − the top event probability" },
    { label: "Minimal cut sets", value: formatNumber(cuts.count), hint: "smallest groups of failures that cause it" },
  ];
  const guessed = (result.events || []).some((e) => e.placeholder);
  return { sentence, tiles, tone: guessed || result.notes?.length ? "caveat" : "neutral" };
}

// A report's section: the stored tree analysed when the page opened.
export default function FaultTreeResult({ result, name }) {
  if (!result) return null;
  const answer = topEventAnswer(result, plainUnit(result.unit));
  return (
    <div className="ft-public">
      <ResultSummary tone={answer.tone} sentence={answer.sentence} stats={answer.tiles}>
        {result.kind === "reliability" ? "Evaluated at the time the top event reaches about 10%. " : ""}
        Exact; a basic event that sits under several gates is counted once.
      </ResultSummary>
      {result.notes?.map((n, i) => <p key={i} className="muted-line warn">{n}</p>)}
      <div className="ft-section">
        <div className="rbd-section-head">The tree, drawn</div>
        <ReactFlowProvider>
          <TreeCanvas result={result} name={name} active />
        </ReactFlowProvider>
      </div>
      <CutSetTable result={result} />
    </div>
  );
}

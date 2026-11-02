import { SectionHeader } from "../components/SectionPage.jsx";
import { SavedOfKind } from "../components/StrategyTool.jsx";
import { STRATEGY_TOOLS } from "../strategyTools.js";
import Card from "../components/ui/Card.jsx";
import FailureFinding from "../components/FailureFinding.jsx";

const TOOL = STRATEGY_TOOLS.failureFinding;

// Strategy › Failure finding.
export default function StrategyFailureFinding() {
  return (
    <div className="app">
      <SectionHeader
        section="strategy"
        title="Failure finding"
        help={TOOL.help}
        purpose="How often to check a hidden function — a protective device whose failure only shows when it's demanded — to keep its availability above target."
      />
      <Card>
        <FailureFinding />
      </Card>
      <SavedOfKind kind={TOOL.kind} noun={TOOL.noun} />
    </div>
  );
}

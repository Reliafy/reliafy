import { Link } from "react-router-dom";
import { SectionHeader } from "../components/SectionPage.jsx";
import { SavedOfKind } from "../components/StrategyTool.jsx";
import { STRATEGY_TOOLS } from "../strategyTools.js";
import Card from "../components/ui/Card.jsx";
import CompareTwoModels from "../components/CompareTwoModels.jsx";

const TOOL = STRATEGY_TOOLS.compare;

// Strategy › Compare two models: which item is more reliable?
export default function StrategyCompare() {
  return (
    <div className="app">
      <SectionHeader
        section="strategy"
        title="Compare two models"
        help={TOOL.help}
        purpose="Put two items head-to-head — a fitted distribution or raw (non-parametric) data on each side — to see which is more reliable."
      />
      <p className="hint">
        One file with a column saying which group each unit is in? Open it in <Link to="/data">Data</Link> and
        use Compare groups: it tests every group at once.
      </p>
      <Card>
        <CompareTwoModels />
      </Card>
      <SavedOfKind kind={TOOL.kind} noun={TOOL.noun} />
    </div>
  );
}

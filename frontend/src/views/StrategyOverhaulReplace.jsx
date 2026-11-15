import { useSearchParams } from "react-router-dom";
import { SectionHeader } from "../components/SectionPage.jsx";
import { SavedOfKind } from "../components/StrategyTool.jsx";
import { STRATEGY_TOOLS } from "../strategyTools.js";
import Card from "../components/ui/Card.jsx";
import OverhaulReplace from "../components/OverhaulReplace.jsx";
import { modelFromSearch } from "../modelNext.js";

const TOOL = STRATEGY_TOOLS.overhaulReplace;

// Strategy › Overhaul and replace: overhaul every X, replace after N overhauls, for a repairable
// unit. A link can preset it: ?model=<saved repairable model>&repair=&overhaul=&replace=&restores=
// (a saved analysis's "Open in Overhaul and replace", a model's "Use this model").
export default function StrategyOverhaulReplace() {
  const [params] = useSearchParams();
  const presets = {
    cost_repair: params.get("repair"), cost_overhaul: params.get("overhaul"), cost_replace: params.get("replace"),
    overhaul_restores: params.get("restores"),
  };
  const model = modelFromSearch(`?${params}`);
  return (
    <div className="app">
      <SectionHeader
        section="strategy"
        title="Overhaul and replace"
        help={TOOL.help}
        purpose="For a repairable unit: how often to overhaul it, and after how many overhauls to replace it, for the lowest long-run cost."
      />
      <Card>
        <OverhaulReplace key={[...params.values()].join("|")} modelId={model} presets={presets} />
      </Card>
      <SavedOfKind kind={TOOL.kind} noun={TOOL.noun} />
    </div>
  );
}

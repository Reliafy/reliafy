import { useSearchParams } from "react-router-dom";
import { SectionHeader } from "../components/SectionPage.jsx";
import { SavedOfKind } from "../components/StrategyTool.jsx";
import { STRATEGY_TOOLS } from "../strategyTools.js";
import Card from "../components/ui/Card.jsx";
import SegmentedControl from "../components/ui/SegmentedControl.jsx";
import OptimalReplacement from "../components/OptimalReplacement.jsx";
import CalendarReplacement from "../components/CalendarReplacement.jsx";

// Strategy › Optimal replacement: by age (one planned price on any day), or
// over a shutdown calendar (?mode=calendar: replacing costs less at the shuts).
export default function StrategyReplacement() {
  const [params, setParams] = useSearchParams();
  const mode = params.get("mode") === "calendar" ? "calendar" : "age";
  const pick = (m) => {
    const next = new URLSearchParams(params);
    if (m === "calendar") next.set("mode", "calendar");
    else next.delete("mode");
    setParams(next, { replace: true });
  };
  const tool = STRATEGY_TOOLS[mode === "calendar" ? "calendar" : "replacement"];
  return (
    <div className="app">
      <SectionHeader
        section="strategy"
        title="Optimal replacement"
        help={tool.help}
        purpose={mode === "calendar"
          ? "The best replacement rule when replacing at a shutdown costs less than between shuts, against running to failure and plain age replacement."
          : "The age-based preventive-replacement interval that minimises the long-run cost rate, versus running to failure."}
      />
      <SegmentedControl
        label="Replacement mode"
        value={mode}
        onChange={pick}
        style={{ marginBottom: "var(--space-4)" }}
        options={[
          { value: "age", label: "Age replacement" },
          { value: "calendar", label: "Shutdown calendar" },
        ]}
      />
      <Card>
        {/* "Show me how" started here sets ?model=&planned=&unplanned= on this
            page: a new key starts the tool again from them, so the tour's costs fill in. */}
        {mode === "calendar" ? <CalendarReplacement />
          : <OptimalReplacement key={["model", "planned", "unplanned"].map((k) => params.get(k) || "").join("|")} />}
      </Card>
      <SavedOfKind kind={tool.kind} noun={tool.noun} />
    </div>
  );
}

import { useSearchParams } from "react-router-dom";
import PageHeader from "../components/ui/PageHeader.jsx";
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
  return (
    <div className="app">
      <PageHeader
        crumbs={[{ label: "Strategy", to: "/strategy" }]}
        title="Optimal replacement"
        meta={mode === "calendar"
          ? "The best replacement rule when replacing at a shutdown costs less than between shuts, against running to failure and plain age replacement."
          : "The age-based preventive-replacement interval that minimises the long-run cost rate, versus running to failure."}
      />
      <SegmentedControl
        label="Replacement mode"
        value={mode}
        onChange={pick}
        style={{ marginBottom: "var(--sp-4)" }}
        options={[
          { value: "age", label: "Age replacement" },
          { value: "calendar", label: "Shutdown calendar" },
        ]}
      />
      <Card>
        {mode === "calendar" ? <CalendarReplacement /> : <OptimalReplacement />}
      </Card>
    </div>
  );
}

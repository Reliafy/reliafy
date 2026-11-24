import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { getForecastStart } from "../api.js";
import { fromParam } from "../sparesForecast.js";
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
  // Opened from the Explorer (Open in › Optimise, ?from=task:<id>): the task's model in use, its cost
  // each time as the planned cost and a failure's cost there, filled in once; its interval now said.
  // A scratch version: to change the task's interval, use Optimise… on the task.
  const from = fromParam(params);
  const fromKey = from ? `${from.kind}:${from.id}` : "";
  const [start, setStart] = useState({ key: "", data: null, error: null });
  useEffect(() => {
    if (!fromKey || start.key === fromKey) return undefined;
    let live = true;
    getForecastStart({ kind: from.kind, id: from.id, root: params.get("root") })
      .then((data) => {
        if (!live) return;
        setStart({ key: fromKey, data, error: null });
        const next = new URLSearchParams(params);
        if (data.model?.id && !next.get("model")) next.set("model", data.model.id);
        if (data.planned_cost != null && !next.get("planned")) next.set("planned", String(data.planned_cost));
        if (data.failure_cost != null && !next.get("unplanned")) next.set("unplanned", String(data.failure_cost));
        setParams(next, { replace: true });
      })
      .catch((e) => live && setStart({ key: fromKey, data: null, error: e.message }));
    return () => { live = false; };
  }, [fromKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const fromLine = from && (
    <p className="hint" role="note" data-testid="repl-from">
      {start.error ? `Couldn't fill it in from the Explorer: ${start.error}`
        : !start.data ? "Filling it in from the Explorer…"
          : <>From: <Link to={start.data.from.link}>{start.data.from.path || start.data.from.name}</Link>
            {start.data.task ? <> · {start.data.task.name}, every {start.data.task.interval} {start.data.task.unit} now</> : null}.
            {" "}A scratch version: to change the task&apos;s interval, use Optimise… on the task.</>}
    </p>
  );
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
      {fromLine}
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
        {/* "Take the tour" started here sets ?model=&planned=&unplanned= on this
            page: a new key starts the tool again from them, so the tour's costs fill in. */}
        {mode === "calendar" ? <CalendarReplacement />
          : <OptimalReplacement key={["model", "planned", "unplanned"].map((k) => params.get(k) || "").join("|")} />}
      </Card>
      <SavedOfKind kind={tool.kind} noun={tool.noun} />
    </div>
  );
}

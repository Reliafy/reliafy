import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getPositionCondition } from "../api.js";
import { positionRisk } from "../joint.js";
import { UnitCharts, UnitSummary } from "./model/RiskTable.jsx";
import { tabPlace } from "../explorerTabs.js";
import "./PositionRisk.css";

// One position's risk now, the one implementation for both places it shows in
// the Explorer: a position's Condition monitoring tab, and the member chosen
// in a class's fleet (ClassFleet). In words first (its age and readings, its
// chance of failing in the next 30, 90 and 365 days, its median life left),
// then its two charts: survival from now, and its readings with the fitted
// path. The words and the charts are the model page's own
// (model/RiskTable.jsx); the numbers come from the condition and life model
// linked to the position, and the item fitted there.
//
// A position that can't be scored says why, never a blank panel: no model
// linked (how to link one, and `onModelling` opens the Modelling tab), or a
// model with something missing (the reason the read gives). `detail`: the
// position's own tab, which also says what the numbers were worked out from
// (a class's fleet says that under its table).
export default function PositionRisk({ positionId, version, onModelling = null, detail = false, label = "This position's risk now" }) {
  const [read, setRead] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let live = true;
    setError(null);
    getPositionCondition(positionId)
      .then((d) => live && setRead(d))
      .catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [positionId, version]);

  if (error) {
    return <div className="card error" role="alert">This position's risk didn't load: {error} Choose the position again to retry.</div>;
  }
  const mine = read && read.position?.id === positionId ? read : null;
  if (!mine) return <p className="hint">Working out this position's risk…</p>;

  const say = positionRisk(mine);
  const model = mine.model ? <Link to={mine.model.path}>{mine.model.name}</Link> : null;
  if (say.state === "scored") {
    const { member } = mine;
    const results = { ...mine.model, horizons: member.unit.horizons };
    const item = `${member.item.name || "(no name)"}${member.item.serial ? ` (${member.item.serial})` : ""}`;
    return (
      <section className="pr" aria-label={label}>
        <UnitSummary view={member.unit} results={results} what="Position" />
        <UnitCharts view={member.unit} results={results} name={mine.position.name} />
        {detail && (
          <p className="hint pr-note">
            Worked out from the item fitted here, {item}: its age since {member.in_service} and its readings
            {member.point?.name ? <> of {member.point.name}</> : ""}, with the condition and life model {model}.
            {" "}The bands on the charts are 90%; “at least” on the median life left is a 90% lower bound
            (one-sided), from the model's uncertainty. “&gt; 99.9%” means very likely, not certain.
          </p>
        )}
      </section>
    );
  }
  return (
    <section className="pr pr-none card" aria-label={label}>
      <p className="pr-lead">
        {say.state === "no-model"
          ? "No risk to show yet: no condition and life model is linked to this position."
          : <>No risk to show yet: the condition and life model linked here ({model}) can't score this position.</>}
      </p>
      {say.why && <p className="pr-why">{say.why}</p>}
      {say.state === "no-model" && (
        <p className="pr-why">
          A condition and life model gives the chance of failing from an item's age and its condition readings.
          To link one, open this position's {tabPlace("models")} and choose Life model, then “Assign a saved model…”.
        </p>
      )}
      {say.facts && <p className="hint pr-facts">{say.facts}</p>}
      {onModelling && say.state === "no-model" && (
        <p className="pr-go">
          <button type="button" className="link" onClick={onModelling} title="Show the life models on this position, and link one">
            Open {tabPlace("models")}
          </button>
        </p>
      )}
    </section>
  );
}

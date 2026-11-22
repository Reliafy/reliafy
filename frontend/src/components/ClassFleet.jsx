import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { getClassFleet, getConditionBelow } from "../api.js";
import { formatNumber } from "../format.js";
import { belowAnswer, fleetAnswer } from "../joint.js";
import WhereItLives from "./ui/WhereItLives.jsx";
import { tabPlace } from "../explorerTabs.js";
import { RiskTable, rankColumn, riskOrder } from "./model/RiskTable.jsx";
import PositionRisk from "./PositionRisk.jsx";
import "./ClassFleet.css";

// A class's fleet, beside the Explorer's tree arranged by Classes: every
// position whose fitted item is of the class (or a class inside it) as one
// table, with its duty (the position class), item, age, last reading and risk
// now, highest risk first. Each member is scored with the condition and life
// model linked to its own position (the Modelling tab), so one fleet can mix
// members with a model, members without one (a dash) and members that can't
// be scored yet (the reason, in words). The table is the model page's own
// (model/RiskTable.jsx); the member chosen is shown as a position shows its
// own risk on its Condition monitoring tab (PositionRisk: its summary line
// and two charts). `within` (a position id: the Explorer opened on one
// asset): the server reads only the members inside that asset, so the answer
// line, the table and the charts are that asset's alone.
//
// The same table on a node with positions below it (`below`: a position or a
// place, any arrangement; the Explorer aggregates downwards): every position
// there and below with condition monitoring (a condition and life model, or a
// condition point), each saying where it lives (WhereItLives), the node's own
// position first, then highest risk first over the stretch that tells them
// apart (named over the table). Risks are never added up: chances of failing
// don't sum across positions.

const n3 = (v) => formatNumber(v);

function readingText(r) {
  if (!r) return "—";
  return `${n3(r.value)}${r.unit ? ` ${r.unit}` : ""}`;
}

export default function ClassFleet({ row, version, onSelect, within = null, below = false }) {
  const classId = below ? row.key : row.ref.id;
  const [fleet, setFleet] = useState(null);
  const [error, setError] = useState(null);
  const [chosen, setChosen] = useState(null);

  useEffect(() => {
    let live = true;
    setError(null);
    (below ? getConditionBelow(classId, within) : getClassFleet(classId, within))
      .then((d) => live && setFleet({ ...d, within }))
      .catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [classId, version, within]);

  // The read for this class and this asset only (an earlier one stays hidden until it's in).
  const mine = fleet && (below ? fleet.node?.id : fleet.item_class?.id) === classId && (fleet.within ?? null) === (within ?? null)
    ? fleet : null;
  const labels = mine?.horizons.labels || [];
  const rows = useMemo(() => (mine?.members || []).map((m) => ({ ...m, id: m.position.id, risk: m.scored ? m.risk : null })), [mine]);
  // The member whose charts show: the one chosen, else the one at highest risk.
  const own = below ? rows.find((r) => r.here)?.id ?? null : null;
  const first = riskOrder(rows, labels, null, own).find((r) => r.risk)?.id || null;
  const unitId = chosen && rows.some((r) => r.id === chosen && r.risk) ? chosen : first;

  if (error) {
    return <div className="card error" role="alert">{below ? "The risk here didn't load" : "The fleet didn't load"}: {error} Choose the {below ? "row" : "class"} again to retry.</div>;
  }
  if (!mine) return <p className="hint">{below ? "Working out the risk here and below…" : "Working out the fleet's risk…"}</p>;

  const lead = below ? [
    { id: "position", label: "Position", cell: (r) => (
      <button type="button" className="link cf-pos cf-where" title="Show this position in the tree"
              onClick={(e) => { e.stopPropagation(); onSelect?.(r.id); }}>
        <WhereItLives rec={r} here={row.type === "pos" ? row.key : null} />
      </button>
    ) },
    { id: "item", label: "Item", cell: (r) => (r.item
      ? <>{r.item.name || "(no name)"}{r.item.serial && <span className="cf-under">{r.item.serial}</span>}</>
      : <span className="cf-under">Nothing fitted</span>) },
    { id: "age", label: "Age (days)", num: true, cell: (r) => (r.age == null ? "—" : n3(r.age)) },
    { id: "reading", label: "Last reading", num: true, cell: (r) => (
      <span title={r.last_reading ? `${r.point?.name || "Reading"}, ${r.last_reading.on}` : r.point ? `No readings on ${r.point.name} yet` : "No condition measurement here"}>
        {readingText(r.last_reading)}{r.last_reading && <span className="cf-under">{r.last_reading.on}</span>}
      </span>
    ) },
  ] : [
    { id: "position", label: "Position", cell: (r) => (
      <>
        <button type="button" className="link cf-pos" title="Show this position in the tree"
                onClick={(e) => { e.stopPropagation(); onSelect?.(r.id); }}>{r.position.name || "(no name)"}</button>
        {r.position.tag && <code className="cf-under">{r.position.tag}</code>}
      </>
    ) },
    { id: "duty", label: "Position class", cell: (r) => r.position.position_class || "—" },
    { id: "item", label: "Item", cell: (r) => (
      <>{r.item.name || "(no name)"}{r.item.serial && <span className="cf-under">{r.item.serial}</span>}</>
    ) },
    { id: "age", label: "Age (days)", num: true, cell: (r) => n3(r.age) },
    { id: "reading", label: "Last reading", num: true, cell: (r) => (
      <span title={r.last_reading ? `${r.point?.name || "Reading"}, ${r.last_reading.on}` : r.point ? `No readings on ${r.point.name} yet` : "No condition measurement here"}>
        {readingText(r.last_reading)}{r.last_reading && <span className="cf-under">{r.last_reading.on}</span>}
      </span>
    ) },
  ];
  return (
    <div className="cf">
      <p className="cf-answer">{below ? belowAnswer(mine) : fleetAnswer(mine)}</p>
      <section className="card cf-card" aria-label="Risk now">
        <div className="cf-head">
          <h2 className="cf-title">Risk now</h2>
          {mine.scored > 0 && (
            <span className="cf-sub">
              {own ? "this position first, then the " : ""}highest chance of failing in the next {labels[rankColumn(rows, labels)]} first
            </span>
          )}
        </div>
        <div className="maint-scroll">
          <RiskTable rows={rows} labels={labels} unit={mine.age_unit} lead={lead} selected={unitId} onPick={setChosen}
                     whyNot={(r) => (r.model || !r.item ? r.why : null)} first={own}
                     empty={below
                       ? `No position here or below has condition monitoring yet (of ${(mine.below || 0).toLocaleString("en-AU")} below). Add a condition measurement point and link a condition and life model in ${tabPlace("models")}.`
                       : "No position has an item of this class fitted."} />
        </div>
        {mine.note && <p className="hint cf-note">{mine.note}</p>}
        {mine.scored > 0 && (
          <p className="hint cf-note">
            Each position's chance of failing over the next stretch, from its own item's age and readings and the
            condition and life model linked to the position
            {mine.models.length === 1 ? <> (<Link to={mine.models[0].path}>{mine.models[0].name}</Link>)</> : ""}.
            {below ? " Each chance is that position's own: they aren't added up, because chances of failing don't sum." : ""}
            {" "}“At least” on the median life left is a 90% lower bound (one-sided). “&gt; 99.9%” means very likely, not certain.
          </p>
        )}
      </section>
      {unitId && <PositionRisk positionId={unitId} version={version} label="The chosen position's prediction" />}
    </div>
  );
}

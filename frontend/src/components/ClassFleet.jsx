import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { getClassFleet } from "../api.js";
import { formatNumber } from "../format.js";
import { fleetAnswer, fleetWithin } from "../joint.js";
import { RiskTable, UnitCharts, UnitSummary, riskOrder, sortColumn } from "./model/RiskTable.jsx";
import "./ClassFleet.css";

// A class's fleet, beside the Explorer's tree arranged by Classes: every
// position whose fitted item is of the class (or a class inside it) as one
// table, with its duty (the position class), item, age, last reading and risk
// now, highest risk first. Each member is scored with the condition and life
// model linked to its own position (the Modelling tab), so one fleet can mix
// members with a model, members without one (a dash) and members that can't
// be scored yet (the reason, in words). The table and a chosen member's two
// charts are the model page's own (model/RiskTable.jsx). `within` (a Set of
// position ids: the Explorer opened on one asset): only the members inside
// that asset, in the answer line, the table and the charts alike.

const n3 = (v) => formatNumber(v);

function readingText(r) {
  if (!r) return "—";
  return `${n3(r.value)}${r.unit ? ` ${r.unit}` : ""}`;
}

export default function ClassFleet({ row, version, onSelect, within = null }) {
  const classId = row.ref.id;
  const [fleet, setFleet] = useState(null);
  const [error, setError] = useState(null);
  const [chosen, setChosen] = useState(null);
  const [view, setView] = useState(null);
  const [viewError, setViewError] = useState(null);

  useEffect(() => {
    let live = true;
    setError(null);
    getClassFleet(classId)
      .then((d) => live && setFleet(d))
      .catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [classId, version]);

  const mine = useMemo(() => (fleet && fleet.item_class.id === classId ? fleetWithin(fleet, within) : null), [fleet, classId, within]);
  const labels = mine?.horizons.labels || [];
  const rows = useMemo(() => (mine?.members || []).map((m) => ({ ...m, id: m.position.id, risk: m.scored ? m.risk : null })), [mine]);
  // The member whose charts show: the one chosen, else the one at highest risk.
  const first = riskOrder(rows, labels).find((r) => r.risk)?.id || null;
  const unitId = chosen && rows.some((r) => r.id === chosen && r.risk) ? chosen : first;

  useEffect(() => {
    if (!unitId) return undefined;
    let live = true;
    setViewError(null);
    getClassFleet(classId, unitId)
      .then((d) => live && setView(d))
      .catch((e) => live && setViewError(e.message));
    return () => { live = false; };
  }, [classId, unitId, version]);

  if (error) {
    return <div className="card error" role="alert">The fleet didn't load: {error} Choose the class again to retry.</div>;
  }
  if (!mine) return <p className="hint">Working out the fleet's risk…</p>;

  const shown = view && view.member?.position.id === unitId && view.member.unit ? view : null;
  const results = shown ? { ...shown.model, horizons: shown.member.unit.horizons } : null;
  const lead = [
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
      <p className="cf-answer">{fleetAnswer(mine)}</p>
      <section className="card cf-card" aria-label="Risk now">
        <div className="cf-head">
          <h2 className="cf-title">Risk now</h2>
          {mine.scored > 0 && <span className="cf-sub">highest chance of failing in the next {labels[sortColumn(labels)]} first</span>}
        </div>
        <div className="maint-scroll">
          <RiskTable rows={rows} labels={labels} unit={mine.age_unit} lead={lead} selected={unitId} onPick={setChosen}
                     whyNot={(r) => (r.model ? r.why : null)}
                     empty="No position has an item of this class fitted." />
        </div>
        {mine.note && <p className="hint cf-note">{mine.note}</p>}
        {mine.scored > 0 && (
          <p className="hint cf-note">
            Each position's chance of failing over the next stretch, from its own item's age and readings and the
            condition and life model linked to the position
            {mine.models.length === 1 ? <> (<Link to={mine.models[0].path}>{mine.models[0].name}</Link>)</> : ""}.
            {" "}“&gt; 99.9%” means very likely, not certain.
          </p>
        )}
      </section>
      {viewError && <div className="card error" role="alert">That position's charts didn't load: {viewError}</div>}
      {unitId && !shown && !viewError && <p className="hint">Working…</p>}
      {shown && (
        <section className="cf-unit" aria-label="The chosen position's prediction">
          <UnitSummary view={shown.member.unit} results={results} what="Position" />
          <UnitCharts view={shown.member.unit} results={results} name={shown.member.position.name} />
        </section>
      )}
    </div>
  );
}

import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getMaintenancePart, getPartStructure, getPartWhereUsed } from "../api.js";
import PageHeader from "../components/ui/PageHeader.jsx";
import { MaintenanceTabs } from "../components/MaintenanceParts.jsx";
import {
  ComponentModal, LevelModal, PositionsFromStructureModal, RollupCard, StructureTree, WhereUsedCard, removeLine,
} from "../components/MaintenanceStructure.jsx";
import { positionsPlanSummary, qtyNumber } from "../maintenanceStructure.js";
import "./Maintenance.css";

// One catalogue part (#435): its details and indenture level, its structure (the
// parts it's made of, expand and collapse), the quantities rolled up, and where it's
// used (the parts it's in, positions, items).
export default function MaintenancePart() {
  const { id } = useParams();
  const [part, setPart] = useState(null);
  const [structure, setStructure] = useState(null);
  const [used, setUsed] = useState(null);
  const [modal, setModal] = useState(null);
  const [made, setMade] = useState(null);
  const [error, setError] = useState(null);
  const load = useCallback(() => {
    setError(null);
    Promise.all([getMaintenancePart(id), getPartStructure(id), getPartWhereUsed(id)])
      .then(([p, s, u]) => { setPart(p); setStructure(s); setUsed(u); })
      .catch((e) => setError(e.message));
  }, [id]);
  useEffect(() => { setMade(null); load(); }, [load]);

  if (error && !part) return <div className="app"><div className="card error">{error}</div></div>;
  if (!part || !structure || !used) return <div className="app"><div className="card empty">Loading…</div></div>;

  const lines = structure.tree.children || [];
  const remove = async (line) => {
    setError(null);
    try { await removeLine(line); load(); } catch (e) { setError(e.message); }
  };
  return (
    <div className="app">
      <PageHeader
        crumbs={[{ label: "Maintenance", to: "/maintenance" }, { label: "Parts", to: "/maintenance/parts" }]}
        title={`${part.part_number} ${part.name}`}
        meta={[part.level, part.manufacturer_entry?.name || part.manufacturer, `${qtyNumber(part.on_hand)} on hand`]
          .filter(Boolean).join(" · ")}
        id={part.id}
        actions={<button className="secondary" onClick={() => setModal("level")}>Indenture level</button>}
        primary={<button onClick={() => setModal({ line: null })}>Add a part to it</button>}
      />
      <MaintenanceTabs />
      {error && <div className="card error">{error}</div>}

      <section className="card">
        <div className="maint-head"><h2>Details</h2></div>
        <dl className="maint-plate">
          <dt>Indenture level</dt><dd>{part.level || <span className="lib-date">none</span>}</dd>
          {(part.manufacturer_entry?.name || part.manufacturer) && <><dt>Manufacturer</dt><dd>{part.manufacturer_entry?.name || part.manufacturer}</dd></>}
          {part.item_class && <><dt>Item class</dt><dd>{part.item_class.name}</dd></>}
          <dt>Unit</dt><dd>{part.unit}{part.unit_cost != null && <span className="lib-date"> · {part.unit_cost} each</span>}</dd>
          <dt>On hand</dt><dd>{qtyNumber(part.on_hand)}{part.stock.length > 0 && (
            <span className="lib-date"> · {part.stock.map((s) => `${s.location.name}: ${qtyNumber(s.quantity)}`).join(", ")}</span>)}</dd>
          <dt>Items of it</dt><dd>{part.items}</dd>
          {part.superseded_by && <><dt>Superseded by</dt><dd><Link to={`/maintenance/parts/${part.superseded_by.id}`}>{part.superseded_by.part_number}</Link></dd></>}
          {part.notes && <><dt>Notes</dt><dd>{part.notes}</dd></>}
        </dl>
      </section>

      <section className="card">
        <div className="maint-head">
          <h2>Structure</h2>
          <div className="maint-row" style={{ marginTop: 0 }}>
            {lines.length > 0 && <button className="secondary" onClick={() => setModal("positions")}>Create positions from it</button>}
            <button className="secondary" onClick={() => setModal({ line: null })}>Add a part</button>
          </div>
        </div>
        {lines.length === 0 ? (
          <p className="lib-date">Nothing inside it yet. Add the parts it's made of (assemblies, replaceable units, components),
            each with how many go into one, or import a BOM on the Parts page.</p>
        ) : (
          <>
            <p className="lib-date">{structure.counts.parts} part{structure.counts.parts === 1 ? "" : "s"} in {structure.counts.depth} level{structure.counts.depth === 1 ? "" : "s"} below it.
              {structure.truncated && " A large structure: some lines aren't drawn."}</p>
            <StructureTree tree={structure.tree} showTop={false}
                           onEdit={(line) => setModal({ line })} onRemove={remove} />
          </>
        )}
        {made && <p className="lib-date">{positionsPlanSummary(made)}{made.top && <> <Link to={`/maintenance/positions/${made.top}`}>Open the top one</Link>.</>}</p>}
      </section>

      {lines.length > 0 && <RollupCard structure={structure} />}
      <WhereUsedCard used={used} />

      {modal?.line !== undefined && (
        <ComponentModal part={part} line={modal.line} onClose={() => setModal(null)} onDone={() => { setModal(null); load(); }} />
      )}
      {modal === "level" && <LevelModal part={part} onClose={() => setModal(null)} onDone={() => { setModal(null); load(); }} />}
      {modal === "positions" && (
        <PositionsFromStructureModal structure={structure} onClose={() => setModal(null)}
                                     onDone={(r) => { setModal(null); setMade(r); load(); }} />
      )}
    </div>
  );
}

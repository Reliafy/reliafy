import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { addPositionPart, createMaintenancePart, listMaintenanceParts, updatePositionPart } from "../api.js";
import { Field, FormModal, PositionPicker } from "./MaintenanceParts.jsx";
import { ClassPicker } from "./MaintenanceItemClasses.jsx";
import { PART_ROLES } from "../maintenanceSpares.js";

// The parts forms, one copy each wherever they're used (Derryn, 9 Nov 2026: "use the same
// components so a change in one place appears in the other"): New part (the Parts tab; the
// prediction pane's "Add a part") and a position's parts-list entry (the position page's Parts
// card; the prediction pane's "Add an existing part…").
//
// `place` {positions: [{id, name, depth}], positionId}: the form also asks which position the
// part goes "On" (a branch's positions; default positionId) and how many, and puts the new part on
// that position's parts list as a component. onDone gets the part, with `on` (the position id) when
// placed.
export function NewPartModal({ kinds = {}, onClose, onDone, place = null }) {
  const [f, setF] = useState({ part_number: "", name: "", manufacturer: "", unit_cost: "", item_class_id: null,
    manufacturer_id: null });
  const [on, setOn] = useState(place?.positionId || place?.positions?.[0]?.id || null);
  const [quantity, setQuantity] = useState("1");
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const ready = !!f.part_number.trim() && !!f.name.trim() && (!place || (!!on && Number(quantity) > 0));
  const submit = async () => {
    const part = await createMaintenancePart({ ...f, unit_cost: f.unit_cost === "" ? null : Number(f.unit_cost) });
    if (!place) return onDone(part);
    await addPositionPart(on, { part_id: part.id, role: "component", quantity: Number(quantity) });
    return onDone({ ...part, on });
  };
  return (
    <FormModal title="New part" submitLabel="Add" canSubmit={ready} onClose={onClose} onSubmit={submit}>
      <Field label="Part number"><input autoFocus value={f.part_number} onChange={set("part_number")} /></Field>
      <Field label="Name"><input value={f.name} placeholder="e.g. Magnesium anode" onChange={set("name")} /></Field>
      {place && (
        <>
          <Field label="On (the position whose parts list it goes on)">
            <PositionPicker positions={place.positions} value={on} onChange={setOn} emptyLabel={null} aria-label="On" />
          </Field>
          <Field label="Quantity"><input type="number" inputMode="decimal" min="0" step="any" value={quantity}
                 onChange={(e) => setQuantity(e.target.value)} /></Field>
        </>
      )}
      <Field label="Manufacturer (optional)"><input value={f.manufacturer} onChange={set("manufacturer")} /></Field>
      <Field label="Cost each (optional)"><input type="number" inputMode="decimal" min="0" step="any" value={f.unit_cost} onChange={set("unit_cost")} /></Field>
      {kinds.classes?.length > 0 && (
        <Field label="Item class (optional: what kind of thing it is)">
          <ClassPicker classes={kinds.classes} value={f.item_class_id} onChange={(v) => setF({ ...f, item_class_id: v })} />
        </Field>
      )}
      {kinds.makers?.length > 0 && (
        <Field label="Manufacturer in the register (optional)">
          <select value={f.manufacturer_id || ""} onChange={(e) => setF({ ...f, manufacturer_id: e.target.value || null })}>
            <option value="">None</option>
            {kinds.makers.map((mk) => <option key={mk.id} value={mk.id}>{mk.name}</option>)}
          </select>
        </Field>
      )}
    </FormModal>
  );
}

// Add a catalogue part to a position's parts list, or change an entry on it. `p` {id, name,
// parts_list}. `positions` [{id, name, depth, parts_list}]: also ask which position it goes "On"
// (a branch's positions; `p` is the one picked first).
export function PartEntryModal({ p, entry, onClose, onDone, positions = null }) {
  const [catalogue, setCatalogue] = useState(null);
  const [onId, setOnId] = useState(p.id);
  const here = (positions && positions.find((x) => x.id === onId)) || p;
  const roleFor = (pos) => (pos.parts_list?.some((x) => x.role === "replacement") ? "component" : "replacement");
  const [f, setF] = useState({
    part_id: "", role: entry?.role || roleFor(p),
    quantity: entry?.quantity ?? 1, critical: !!entry?.critical, min: entry?.min_on_hand ?? "", notes: entry?.notes || "",
  });
  useEffect(() => {
    if (!entry) listMaintenanceParts().then((d) => setCatalogue(d.parts)).catch(() => setCatalogue([]));
  }, [entry]);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const listed = new Set((here.parts_list || []).map((x) => x.part.id));
  const body = {
    role: f.role, quantity: Number(f.quantity), critical: f.critical, notes: f.notes,
    ...(f.critical ? { min_on_hand: f.min === "" ? null : Number(f.min) } : {}),
  };
  const pickOn = (id) => {
    const next = positions.find((x) => x.id === id) || p;
    setOnId(next.id);
    setF((cur) => ({ ...cur, part_id: "", role: roleFor(next) }));
  };
  return (
    <FormModal title={entry ? `${entry.part.part_number} on ${p.name}` : `Add a part to ${positions ? "a parts list" : p.name}`}
               submitLabel={entry ? "Save" : "Add"} onClose={onClose}
               canSubmit={!!(entry || f.part_id) && Number(f.quantity) > 0}
               onSubmit={async () => onDone(entry ? await updatePositionPart(entry.id, body)
                 : await addPositionPart(here.id, { ...body, part_id: f.part_id }))}>
      {!entry && positions && (
        <Field label="On (the position whose parts list it goes on)">
          <PositionPicker positions={positions} value={onId} onChange={pickOn} emptyLabel={null} aria-label="On" />
        </Field>
      )}
      {!entry && (
        <Field label="Part">
          {catalogue === null ? <span className="lib-date">Loading…</span> : catalogue.length === 0 ? (
            <span className="lib-date">The catalogue is empty: add parts on the <Link to="/asset-register/parts">Parts</Link> page first.</span>
          ) : (
            <select autoFocus value={f.part_id} onChange={set("part_id")} aria-label="Part">
              <option value="">Choose…</option>
              {catalogue.filter((pt) => !listed.has(pt.id)).map((pt) => (
                <option key={pt.id} value={pt.id}>{pt.part_number}: {pt.name}{pt.superseded_by ? " (superseded)" : ""}</option>
              ))}
            </select>
          )}
        </Field>
      )}
      <Field label="Role">
        <select value={f.role} onChange={set("role")}>
          {PART_ROLES.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
        </select>
      </Field>
      <Field label="Quantity per job"><input type="number" inputMode="decimal" min="0" step="any" value={f.quantity}
             onChange={set("quantity")} /></Field>
      <label className="maint-row" style={{ gap: "0.5rem" }}>
        <input type="checkbox" checked={f.critical} onChange={(e) => setF({ ...f, critical: e.target.checked })} />
        Critical spare: keep some in stock
      </label>
      {f.critical && (
        <Field label="Keep at least (blank: one job's worth)"><input type="number" inputMode="decimal" min="0" step="any"
               value={f.min} onChange={set("min")} /></Field>
      )}
      <Field label="Compatibility notes (optional)"><textarea rows={2} value={f.notes}
             placeholder="e.g. needs the matching button kit; fits from serial 4000 on" onChange={set("notes")} /></Field>
      <p className="lib-date">What supersedes a part, and the parts interchangeable with it, come from the catalogue.</p>
    </FormModal>
  );
}

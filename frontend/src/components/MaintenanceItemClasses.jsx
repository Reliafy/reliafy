// Item classes (what kind of thing an item is, as a tree with attributes) and the
// manufacturer register: optional. The Classes page's sections, the item page's
// card and the pickers the items and parts lists filter by.
import { Fragment, useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  assignItemClass, createItemClass, createManufacturer, downloadItemClasses, getItemClass, getItemClasses,
  importItemClasses, linkManufacturer, linkManufacturersByName, listMaintenanceParts, listManufacturers,
  loadStarterItemClasses, matchManufacturer, mergeManufacturers, retireItemClass, setItemAttributes, setItemPart,
  updateItemClass, updateManufacturer,
} from "../api.js";
import { Field, FormModal } from "./MaintenanceParts.jsx";
import {
  ATTRIBUTE_KINDS, attributeRows, attributeText, attributeValueText, attributesBody, flattenClasses, importSummary,
  subtreeIds, viaText,
} from "../maintenanceItemClasses.js";
import { DESCRIPTION_HINT, tooLong } from "../maintenanceText.js";

// ---- pickers ---------------------------------------------------------------------------

// A class from the flat list (getItemClasses().classes: each with its display path).
export function ClassPicker({ classes, value, onChange, emptyLabel = "None", exclude }) {
  return (
    <select value={value || ""} onChange={(e) => onChange(e.target.value || null)}>
      <option value="">{emptyLabel}</option>
      {(classes || []).filter((c) => !exclude?.has(c.id)).map((c) => (
        <option key={c.id} value={c.id}>{c.display}</option>
      ))}
    </select>
  );
}

function MakerPicker({ makers, value, onChange, emptyLabel = "None", exclude }) {
  return (
    <select value={value || ""} onChange={(e) => onChange(e.target.value || null)}>
      <option value="">{emptyLabel}</option>
      {(makers || []).filter((mk) => mk.id !== exclude).map((mk) => <option key={mk.id} value={mk.id}>{mk.name}</option>)}
    </select>
  );
}

// Filters for the items and parts lists: shown only once the workspace has item
// classes or manufacturers.
export function KindFilters({ classes, makers, value, onChange }) {
  if (!classes?.length && !makers?.length) return null;
  return (
    <>
      {classes?.length > 0 && (
        <select aria-label="Item class" value={value.itemClassId || ""} style={{ maxWidth: "16rem" }}
                onChange={(e) => onChange({ ...value, itemClassId: e.target.value || null })}>
          <option value="">Every class</option>
          <option value="none">No class</option>
          {classes.map((c) => <option key={c.id} value={c.id}>{c.display}</option>)}
        </select>
      )}
      {makers?.length > 0 && (
        <select aria-label="Manufacturer" value={value.manufacturerId || ""}
                onChange={(e) => onChange({ ...value, manufacturerId: e.target.value || null })}>
          <option value="">Every manufacturer</option>
          <option value="none">No manufacturer linked</option>
          {makers.map((mk) => <option key={mk.id} value={mk.id}>{mk.name}</option>)}
        </select>
      )}
    </>
  );
}

// The classes (flat) and manufacturers, for pickers and filters.
export function useKinds() {
  const [kinds, setKinds] = useState({ classes: null, makers: null });
  const load = useCallback(() => {
    Promise.all([getItemClasses(), listManufacturers()])
      .then(([c, m]) => setKinds({ classes: c.classes || [], makers: m.manufacturers || [] }))
      .catch(() => setKinds({ classes: [], makers: [] }));
  }, []);
  useEffect(() => load(), [load]);
  return [kinds, load];
}

// ---- the item page: what kind of thing it is -------------------------------------------------

export function ItemKindCard({ item, kinds, onChanged }) {
  const [modal, setModal] = useState(null);
  const used = kinds.classes?.length || kinds.makers?.length || item.item_class || item.part || item.manufacturer_entry;
  if (!used) return null;
  const other = Object.entries(item.other_attributes || {});
  return (
    <section className="card">
      <div className="maint-head">
        <h2>What it is</h2>
        <div className="maint-row" style={{ marginTop: 0 }}>
          <button className="secondary" onClick={() => setModal("kind")}>Class, model and maker</button>
          {item.item_class && item.attributes.length > 0 && <button onClick={() => setModal("values")}>Fill in attributes</button>}
        </div>
      </div>
      <dl className="maint-plate">
        <dt>Item class</dt>
        <dd>{item.item_class ? <>{item.item_class.display}
          {viaText(item.item_class.via) && <span className="lib-date"> ({viaText(item.item_class.via)})</span>}</> : "—"}</dd>
        <dt>Model (part)</dt>
        <dd>{item.part ? <Link to="/asset-register/parts">{item.part.part_number}</Link> : "—"}
          {item.part && <span className="lib-date"> · {item.part.name}</span>}</dd>
        <dt>Manufacturer</dt>
        <dd>{item.manufacturer_entry ? <>{item.manufacturer_entry.name}
          {viaText(item.manufacturer_entry.via) && <span className="lib-date"> ({viaText(item.manufacturer_entry.via)})</span>}</>
          : <span className="lib-date">{item.manufacturer ? `“${item.manufacturer}”, not linked to the register` : "—"}</span>}</dd>
        {item.attributes.map((a) => (
          <Fragment key={a.name}><dt>{a.name}</dt><dd>{attributeValueText(a)}</dd></Fragment>
        ))}
        {other.map(([k, v]) => (
          <Fragment key={k}><dt>{k}</dt><dd>{String(v)} <span className="lib-date">(not an attribute of its class now)</span></dd></Fragment>
        ))}
      </dl>
      {item.item_class && item.attributes.length === 0 && <p className="lib-date">Its class has no attributes yet.</p>}
      {modal === "kind" && <ItemKindModal item={item} kinds={kinds} onClose={() => setModal(null)}
                                          onDone={(d) => { setModal(null); onChanged(d); }} />}
      {modal === "values" && <AttributesModal item={item} onClose={() => setModal(null)}
                                              onDone={(d) => { setModal(null); onChanged(d); }} />}
    </section>
  );
}

function ItemKindModal({ item, kinds, onClose, onDone }) {
  const ownClass = item.item_class?.via === "item" ? item.item_class.id : null;
  const ownMaker = item.manufacturer_entry?.via === "item" ? item.manufacturer_entry.id : null;
  const [f, setF] = useState({ itemClassId: ownClass, partId: item.part?.id || null, makerId: ownMaker });
  const [parts, setParts] = useState(null);
  const [match, setMatch] = useState(null);
  useEffect(() => {
    listMaintenanceParts().then((d) => setParts(d.parts)).catch(() => setParts([]));
    if (item.manufacturer && !ownMaker) matchManufacturer(item.manufacturer).then(setMatch).catch(() => {});
  }, [item.manufacturer, ownMaker]);
  const submit = async () => {
    let d = item;
    if ((item.part?.id || null) !== f.partId) d = await setItemPart(item.id, f.partId);
    if (ownClass !== f.itemClassId) d = await assignItemClass(item.id, f.itemClassId);
    if (ownMaker !== f.makerId) d = await linkManufacturer(item.id, f.makerId);
    onDone(d);
  };
  return (
    <FormModal title={`What ${item.name} is`} submitLabel="Save" onClose={onClose} onSubmit={submit}>
      <Field label="Model: the catalogue part it is (its class and maker come with it)">
        <select value={f.partId || ""} onChange={(e) => setF({ ...f, partId: e.target.value || null })}>
          <option value="">{parts === null ? "Loading…" : "None"}</option>
          {(parts || []).map((pt) => <option key={pt.id} value={pt.id}>{pt.part_number} · {pt.name}</option>)}
        </select>
      </Field>
      <Field label="Its own item class (leave as None to take its part's)">
        <ClassPicker classes={kinds.classes} value={f.itemClassId} onChange={(v) => setF({ ...f, itemClassId: v })} />
      </Field>
      <Field label="Its own manufacturer link (None: its part's)">
        <MakerPicker makers={kinds.makers} value={f.makerId} onChange={(v) => setF({ ...f, makerId: v })} />
      </Field>
      {match?.match && !f.makerId && (
        <p className="lib-date">“{item.manufacturer}” matches {match.match.name} in the register.{" "}
          <button className="secondary" onClick={() => setF({ ...f, makerId: match.match.id })}>Use it</button></p>
      )}
    </FormModal>
  );
}

function AttributesModal({ item, onClose, onDone }) {
  const [values, setValues] = useState(Object.fromEntries(item.attributes.map((a) => [a.name, a.value ?? ""])));
  const submit = async () => {
    const body = {};
    for (const a of item.attributes) {
      const v = values[a.name];
      if (String(v ?? "") !== String(a.value ?? "")) body[a.name] = v === "" ? null : v;
    }
    onDone(Object.keys(body).length ? await setItemAttributes(item.id, body) : item);
  };
  return (
    <FormModal title={`${item.name}: attributes`} submitLabel="Save" onClose={onClose} onSubmit={submit}>
      <p className="lib-date">From its class, {item.item_class.display}. Numbers in the unit shown; anything else from the
        nameplate goes in its nameplate fields.</p>
      {item.attributes.map((a) => (
        <Field key={a.name} label={`${a.name}${a.unit ? ` (${a.unit})` : ""}`}>
          {a.kind === "choice" ? (
            <select value={values[a.name] ?? ""} onChange={(e) => setValues({ ...values, [a.name]: e.target.value })}>
              <option value="">—</option>
              {a.options.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          ) : (
            <input type={a.kind === "number" ? "number" : "text"} step="any" inputMode={a.kind === "number" ? "decimal" : undefined}
                   value={values[a.name] ?? ""} onChange={(e) => setValues({ ...values, [a.name]: e.target.value })} />
          )}
        </Field>
      ))}
    </FormModal>
  );
}

// A part's class and maker (the parts list's row button).
export function PartKindModal({ part, kinds, onClose, onDone }) {
  const [f, setF] = useState({ itemClassId: part.item_class?.id || null, makerId: part.manufacturer_entry?.id || null });
  return (
    <FormModal title={`What ${part.part_number} is`} submitLabel="Save" onClose={onClose}
               onSubmit={async () => {
                 if ((part.item_class?.id || null) !== f.itemClassId) await assignItemClass(part.id, f.itemClassId);
                 if ((part.manufacturer_entry?.id || null) !== f.makerId) await linkManufacturer(part.id, f.makerId);
                 onDone();
               }}>
      <p className="lib-date">Items linked to this part (its make and model) take its class and maker unless they have their own.</p>
      <Field label="Item class"><ClassPicker classes={kinds.classes} value={f.itemClassId}
                                             onChange={(v) => setF({ ...f, itemClassId: v })} /></Field>
      <Field label="Manufacturer"><MakerPicker makers={kinds.makers} value={f.makerId}
                                               onChange={(v) => setF({ ...f, makerId: v })} /></Field>
    </FormModal>
  );
}

// ---- the Classes page: item classes ----------------------------------------------------------

function ClassNode({ node, selected, onSelect }) {
  return (
    <li>
      <div className="maint-node">
        <button className="link maint-node-name" aria-current={selected === node.id ? "true" : undefined} onClick={() => onSelect(node.id)}>
          {node.name}
        </button>
        {node.code && <span className="maint-badge">{node.code}</span>}
        {node.level && <span className="lib-date">{node.level}</span>}
        <span className="maint-node-item">
          {node.all_items} item{node.all_items === 1 ? "" : "s"} · {node.all_parts} part{node.all_parts === 1 ? "" : "s"}
        </span>
      </div>
      {node.children.length > 0 && (
        <ul>{node.children.map((c) => <ClassNode key={c.id} node={c} selected={selected} onSelect={onSelect} />)}</ul>
      )}
    </li>
  );
}

export function ItemClassesSection() {
  const [data, setData] = useState(null);
  const [selected, setSelected] = useState(null);
  const [modal, setModal] = useState(null);
  const [error, setError] = useState(null);
  const load = useCallback(() => {
    getItemClasses().then(setData).catch((e) => setError(e.message));
  }, []);
  useEffect(() => load(), [load]);
  const download = (format) => downloadItemClasses(format).catch((e) => setError(e.message));
  const empty = data && data.tree.length === 0;
  return (
    <>
      <section className="card">
        <div className="maint-head">
          <h2>Item classes</h2>
          <div className="maint-row" style={{ marginTop: 0 }}>
            <button className="secondary" onClick={() => setModal("starter")}>Starter taxonomy</button>
            <button className="secondary" onClick={() => setModal("import")}>Import</button>
            {!empty && <button className="secondary" onClick={() => download("csv")}>Export CSV</button>}
            {!empty && <button className="secondary" onClick={() => download("json")}>Export JSON</button>}
            <button onClick={() => setModal({ create: null })}>New class</button>
          </div>
        </div>
        {error && <div className="card error">{error}</div>}
        {data === null ? <p className="lib-date">Loading…</p> : empty ? (
          <p className="lib-date">
            Optional. Say what kind of thing each item is (Rotating equipment › Pump › Centrifugal), with attributes to fill in
            from its nameplate. Not the same as a position's class, which is its duty. Start from Reliafy's starter
            taxonomy, import your own (CSV or JSON), or add classes one at a time.
          </p>
        ) : (
          <>
            <p className="lib-date">
              {data.counts.items_classified} of {data.counts.items} items and {data.counts.parts_classified} of{" "}
              {data.counts.parts} parts have a class. Counts include the classes inside each.
            </p>
            <ul className="maint-tree">
              {data.tree.map((n) => <ClassNode key={n.id} node={n} selected={selected} onSelect={setSelected} />)}
            </ul>
          </>
        )}
      </section>
      {selected && data && (
        <ItemClassPanel key={selected} id={selected} data={data}
                        onChanged={load} onRetired={() => { setSelected(null); load(); }}
                        onAddChild={() => setModal({ create: selected })} />
      )}
      {modal?.create !== undefined && (
        <NewClassModal parentId={modal.create} classes={data?.classes || []} onClose={() => setModal(null)}
                       onDone={(c) => { setModal(null); setSelected(c.id); load(); }} />
      )}
      {modal === "starter" && <StarterModal onClose={() => setModal(null)} onDone={() => { setModal(null); load(); }} />}
      {modal === "import" && <ImportClassesModal onClose={() => setModal(null)} onDone={() => { setModal(null); load(); }} />}
      <ManufacturersCard />
    </>
  );
}

function ItemClassPanel({ id, data, onChanged, onRetired, onAddChild }) {
  const [c, setC] = useState(null);
  const [modal, setModal] = useState(null);
  const [error, setError] = useState(null);
  const load = useCallback(() => {
    getItemClass(id).then(setC).catch((e) => setError(e.message));
  }, [id]);
  useEffect(() => load(), [load]);
  const changed = (d) => { setC(d); setModal(null); onChanged(); };
  const retire = async () => {
    setError(null);
    try { await retireItemClass(id); onRetired(); } catch (e) { setError(e.message); }
  };
  if (!c) return <section className="card">{error ? <div className="card error">{error}</div> : <p className="lib-date">Loading…</p>}</section>;
  return (
    <section className="card">
      <div className="maint-head">
        <h2>{c.display}</h2>
        <div className="maint-row" style={{ marginTop: 0 }}>
          <button className="secondary" onClick={() => setModal("edit")}>Edit</button>
          <button className="secondary" onClick={() => setModal("attributes")}>Attributes</button>
          <button className="secondary" onClick={() => setModal("move")}>Move</button>
          <button className="secondary" onClick={onAddChild}>Add a class inside</button>
          <button className="secondary" onClick={retire}>Retire</button>
        </div>
      </div>
      {error && <div className="card error">{error}</div>}
      <dl className="maint-plate">
        {c.code && <><dt>Code</dt><dd>{c.code}</dd></>}
        {c.level && <><dt>Level</dt><dd>{c.level}</dd></>}
        {c.description && <><dt>Description</dt><dd>{c.description}</dd></>}
        {c.source && <><dt>From</dt><dd>{c.source}</dd></>}
      </dl>
      <h3>Attributes</h3>
      {c.attributes.length === 0 ? <p className="lib-date">None yet: add the ratings items of this kind carry.</p> : (
        <table className="lib-table">
          <thead><tr><th>Attribute</th><th>Kind</th><th>From</th></tr></thead>
          <tbody>
            {c.attributes.map((a) => (
              <tr key={a.name}>
                <td>{attributeText(a)}</td>
                <td className="lib-date">{a.kind}</td>
                <td className="lib-date">{a.from.id === c.id ? "this class" : a.from.name}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <h3>In it ({c.counts.items} item{c.counts.items === 1 ? "" : "s"}, {c.counts.parts} part{c.counts.parts === 1 ? "" : "s"})</h3>
      {c.items.length > 0 && (
        <ul className="maint-list">
          {c.items.map((i) => (
            <li key={i.id}><Link to={`/asset-register/items/${i.id}`}>{i.name}</Link>
              <span className="lib-date"> · {[i.manufacturer, i.model, i.serial].filter(Boolean).join(" ") || "—"}
                {i.item_class && i.item_class.id !== c.id ? ` · ${i.item_class.name}` : ""}</span></li>
          ))}
        </ul>
      )}
      {c.parts.length > 0 && <p className="lib-date">Parts: {c.parts.map((pt) => pt.part_number).join(", ")}</p>}
      {modal === "edit" && <EditClassModal c={c} onClose={() => setModal(null)} onDone={changed} />}
      {modal === "attributes" && <ClassAttributesModal c={c} onClose={() => setModal(null)} onDone={changed} />}
      {modal === "move" && <MoveClassModal c={c} data={data} onClose={() => setModal(null)} onDone={changed} />}
    </section>
  );
}

function NewClassModal({ parentId, classes, onClose, onDone }) {
  const [f, setF] = useState({ name: "", parent_id: parentId, code: "", level: "", description: "" });
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  return (
    <FormModal title="New item class" submitLabel="Create" canSubmit={!!f.name.trim() && !tooLong(f.name)} onClose={onClose}
               onSubmit={async () => onDone(await createItemClass(f))}>
      <Field label="Name" text={f.name} hint={DESCRIPTION_HINT}><input autoFocus value={f.name} placeholder="e.g. Centrifugal pump" onChange={set("name")} /></Field>
      <Field label="Inside"><ClassPicker classes={classes} value={f.parent_id} emptyLabel="Nothing (top level)"
                                         onChange={(v) => setF({ ...f, parent_id: v })} /></Field>
      <Field label="Code (optional: your own, e.g. to map to a standard you hold)"><input value={f.code} onChange={set("code")} /></Field>
      <Field label="Level (optional: e.g. class, type, subunit)"><input value={f.level} onChange={set("level")} /></Field>
      <Field label="Description (optional)"><input value={f.description} onChange={set("description")} /></Field>
    </FormModal>
  );
}

function EditClassModal({ c, onClose, onDone }) {
  const [f, setF] = useState({ name: c.name, code: c.code, level: c.level, description: c.description });
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  return (
    <FormModal title={`Edit ${c.name}`} submitLabel="Save" canSubmit={!!f.name.trim() && !tooLong(f.name)} onClose={onClose}
               onSubmit={async () => onDone(await updateItemClass(c.id, f))}>
      <Field label="Name" text={f.name} hint={DESCRIPTION_HINT}><input value={f.name} onChange={set("name")} /></Field>
      <Field label="Code"><input value={f.code} onChange={set("code")} /></Field>
      <Field label="Level"><input value={f.level} onChange={set("level")} /></Field>
      <Field label="Description"><input value={f.description} onChange={set("description")} /></Field>
    </FormModal>
  );
}

function ClassAttributesModal({ c, onClose, onDone }) {
  const [rows, setRows] = useState(attributeRows(c.own_attributes));
  const setRow = (i, k) => (e) => setRows(rows.map((r, j) => (j === i ? { ...r, [k]: e.target.value } : r)));
  const inherited = c.attributes.filter((a) => a.from.id !== c.id);
  return (
    <FormModal title={`${c.name}: attributes`} submitLabel="Save" onClose={onClose}
               onSubmit={async () => onDone(await updateItemClass(c.id, { attributes: attributesBody(rows) }))}>
      {inherited.length > 0 && (
        <p className="lib-date">Inherited: {inherited.map((a) => `${attributeText(a)} (${a.from.name})`).join("; ")}.</p>
      )}
      {rows.map((r, i) => (
        <div key={i} className="maint-row" style={{ marginTop: "0.25rem" }}>
          <input placeholder="e.g. Flow" value={r.name} onChange={setRow(i, "name")} />
          <input placeholder="unit, e.g. m3/h" value={r.unit} style={{ width: "7rem" }} onChange={setRow(i, "unit")} />
          <select value={r.kind} onChange={setRow(i, "kind")}>
            {ATTRIBUTE_KINDS.map((k) => <option key={k.id} value={k.id}>{k.label}</option>)}
          </select>
          {r.kind === "choice" && <input placeholder="options: a | b | c" value={r.options} onChange={setRow(i, "options")} />}
          <button className="secondary" onClick={() => setRows(rows.filter((_, j) => j !== i))}>Remove</button>
        </div>
      ))}
      <button className="secondary" style={{ marginTop: "0.5rem" }}
              onClick={() => setRows([...rows, { name: "", unit: "", kind: "number", options: "" }])}>Add an attribute</button>
      <p className="lib-date">Classes inside it inherit these. Values items already have for one you remove stay on them.</p>
    </FormModal>
  );
}

function MoveClassModal({ c, data, onClose, onDone }) {
  const [to, setTo] = useState(c.parent?.id || null);
  const exclude = subtreeIds(data.tree, c.id);
  return (
    <FormModal title={`Move ${c.name}`} submitLabel="Move" onClose={onClose}
               onSubmit={async () => onDone(await updateItemClass(c.id, { parent_id: to }))}>
      <p className="lib-date">The classes inside it, and its items and parts, go with it.</p>
      <Field label="Inside"><ClassPicker classes={data.classes} value={to} exclude={exclude} emptyLabel="Nothing (top level)"
                                         onChange={setTo} /></Field>
    </FormModal>
  );
}

function ImportResult({ result }) {
  if (!result) return null;
  return (
    <>
      <p>{importSummary(result)}</p>
      {result.errors.length > 0 && (
        <ul className="maint-list">{result.errors.map((e, i) => <li key={i} className="maint-overdue">{e.row ? `${e.row}: ` : ""}{e.error}</li>)}</ul>
      )}
      {result.conflicts.length > 0 && (
        <ul className="maint-list">{result.conflicts.map((x, i) => (
          <li key={i} className="lib-date">{x.path}{x.attribute ? `, ${x.attribute}` : x.field ? `, ${x.field}` : ""}: {x.why}</li>
        ))}</ul>
      )}
    </>
  );
}

function StarterModal({ onClose, onDone }) {
  const [preview, setPreview] = useState(null);
  useEffect(() => { loadStarterItemClasses(true).then(setPreview).catch(() => {}); }, []);
  const adds = preview && preview.counts.create + preview.counts.update > 0;
  return (
    <FormModal title="Reliafy starter taxonomy" submitLabel="Load it" canSubmit={!!adds} onClose={onClose}
               onSubmit={async () => { await loadStarterItemClasses(false); onDone(); }}>
      <p className="lib-date">
        Reliafy's own short list of common equipment (pumps, motors, compressors, fans, valves, vessels, heat exchangers,
        conveyors, gearboxes, engines, generators, transformers, switchgear, instruments, HVAC and water heaters), with
        typical attributes. It isn't ISO 14224 or OREDA, and has no codes. Rename, extend or retire anything in it;
        loading it again adds only what's missing.
      </p>
      {preview === null ? <p className="lib-date">Checking…</p> : <ImportResult result={preview} />}
    </FormModal>
  );
}

function ImportClassesModal({ onClose, onDone }) {
  const [file, setFile] = useState(null);
  const [text, setText] = useState(null);
  const [preview, setPreview] = useState(null);
  const format = file && /\.json$/i.test(file.name) ? "json" : "csv";
  const pick = (f) => {
    setFile(f); setPreview(null); setText(null);
    if (f) f.text().then(setText);
  };
  const body = (dryRun) => ({ format, text, dryRun, source: file ? `Imported from ${file.name}` : "imported" });
  return (
    <FormModal title="Import item classes" submitLabel={preview?.ok ? "Import" : "Check it"} canSubmit={text !== null}
               onClose={onClose}
               onSubmit={async () => (preview?.ok ? (await importItemClasses(body(false)), onDone())
                 : setPreview(await importItemClasses(body(true))))}>
      <p className="lib-date">
        Your own taxonomy (your company's, or a copy of a standard you hold a licence for) as CSV or JSON. CSV columns:
        path (Rotating equipment &gt; Pump &gt; Centrifugal), and optionally code, level, description and attributes
        (“Flow (m3/h); Stages [number]; Seal [choice: mechanical | packing]”). Classes already here are matched by path
        and only gain what they lack. Every row is checked first; if any is wrong, nothing is imported.
      </p>
      <Field label="File"><input type="file" accept=".csv,.json" onChange={(e) => pick(e.target.files[0] || null)} /></Field>
      <ImportResult result={preview} />
    </FormModal>
  );
}

// ---- the Classes page: the manufacturer register ---------------------------------------------------

export function ManufacturersCard() {
  const [makers, setMakers] = useState(null);
  const [modal, setModal] = useState(null);
  const [error, setError] = useState(null);
  const load = useCallback(() => {
    listManufacturers().then((d) => setMakers(d.manufacturers)).catch((e) => setError(e.message));
  }, []);
  useEffect(() => load(), [load]);
  const done = () => { setModal(null); load(); };
  return (
    <section className="card">
      <div className="maint-head">
        <h2>Manufacturers</h2>
        <div className="maint-row" style={{ marginTop: 0 }}>
          {makers?.length > 0 && <button className="secondary" onClick={() => setModal("link")}>Link by name</button>}
          <button onClick={() => setModal("new")}>Add a manufacturer</button>
        </div>
      </div>
      {error && <div className="card error">{error}</div>}
      {makers === null ? <p className="lib-date">Loading…</p> : makers.length === 0 ? (
        <p className="lib-date">Optional. A register of makers and the names they go by (KSB, K.S.B., KSB SE &amp; Co. KGaA), so
          items and parts typed in different ways count as one maker. Their typed manufacturer stays as it is.</p>
      ) : (
        <table className="lib-table">
          <thead><tr><th>Manufacturer</th><th>Also known as</th><th>Items</th><th>Parts</th><th /></tr></thead>
          <tbody>
            {makers.map((mk) => (
              <tr key={mk.id}>
                <td>{mk.name}</td>
                <td className="lib-date">{mk.aliases.join(", ") || "—"}</td>
                <td>{mk.items}</td><td>{mk.parts}</td>
                <td>
                  <button className="secondary" onClick={() => setModal({ edit: mk })}>Edit</button>{" "}
                  {makers.length > 1 && <button className="secondary" onClick={() => setModal({ merge: mk })}>Merge into…</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {modal === "new" && <MakerModal onClose={() => setModal(null)} onDone={done} />}
      {modal?.edit && <MakerModal maker={modal.edit} onClose={() => setModal(null)} onDone={done} />}
      {modal?.merge && <MergeMakerModal maker={modal.merge} makers={makers} onClose={() => setModal(null)} onDone={done} />}
      {modal === "link" && <LinkByNameModal onClose={() => setModal(null)} onDone={done} />}
    </section>
  );
}

function MakerModal({ maker, onClose, onDone }) {
  const [name, setName] = useState(maker?.name || "");
  const [aliases, setAliases] = useState((maker?.aliases || []).join("\n"));
  const submit = async () => {
    const list = aliases.split("\n").map((a) => a.trim()).filter(Boolean);
    if (!maker) return onDone(await createManufacturer({ name, aliases: list }));
    const before = maker.aliases;
    return onDone(await updateManufacturer(maker.id, {
      name, add_aliases: list.filter((a) => !before.includes(a)), remove_aliases: before.filter((a) => !list.includes(a)),
    }));
  };
  return (
    <FormModal title={maker ? `Edit ${maker.name}` : "Add a manufacturer"} submitLabel="Save" canSubmit={!!name.trim()}
               onClose={onClose} onSubmit={submit}>
      <Field label="Name"><input autoFocus value={name} placeholder="e.g. KSB" onChange={(e) => setName(e.target.value)} /></Field>
      <Field label="Also known as (one per line; case and punctuation don't matter)">
        <textarea rows={4} value={aliases} placeholder={"KSB SE & Co. KGaA\nKSB Pumps"} onChange={(e) => setAliases(e.target.value)} />
      </Field>
    </FormModal>
  );
}

function MergeMakerModal({ maker, makers, onClose, onDone }) {
  const [into, setInto] = useState(null);
  return (
    <FormModal title={`Merge ${maker.name}`} submitLabel="Merge" canSubmit={!!into} onClose={onClose}
               onSubmit={async () => onDone(await mergeManufacturers(maker.id, into))}>
      <p className="lib-date">For two entries that are the same maker: its items and parts move to the other, and its name and
        aliases become the other's aliases.</p>
      <Field label="Into"><MakerPicker makers={makers} value={into} exclude={maker.id} emptyLabel="Choose…" onChange={setInto} /></Field>
    </FormModal>
  );
}

function LinkByNameModal({ onClose, onDone }) {
  const [preview, setPreview] = useState(null);
  useEffect(() => { linkManufacturersByName(true).then(setPreview).catch(() => {}); }, []);
  return (
    <FormModal title="Link items and parts by their manufacturer" submitLabel={`Link ${preview?.links.length || 0}`}
               canSubmit={!!preview?.links.length} onClose={onClose}
               onSubmit={async () => { await linkManufacturersByName(false); onDone(); }}>
      <p className="lib-date">Items and parts with a manufacturer typed in and no link yet, matched to the register by name or alias.</p>
      {preview === null ? <p className="lib-date">Checking…</p> : (
        <>
          {preview.links.length === 0 ? <p>Nothing to link.</p> : (
            <ul className="maint-list">{preview.links.slice(0, 50).map((l) => (
              <li key={l.target.id}>{l.target.name} <span className="lib-date">({l.target.kind}, “{l.text}”)</span> → {l.manufacturer.name}</li>
            ))}{preview.links.length > 50 && <li className="lib-date">and {preview.links.length - 50} more</li>}</ul>
          )}
          {preview.unmatched.length > 0 && (
            <p className="lib-date">Not in the register: {preview.unmatched.slice(0, 20).map((u) => `${u.text} (${u.count})`).join(", ")}.
              Add them, or as aliases, then link again.</p>
          )}
        </>
      )}
    </FormModal>
  );
}

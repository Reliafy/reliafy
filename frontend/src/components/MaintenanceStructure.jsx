// Product structure (#435): parts made of parts. The structure tree (expand and
// collapse, quantities, refs, indenture levels), the quantities rolled up, where a
// part is used, and the modals that change a structure, the indenture level list,
// import a BOM and make positions from a structure.
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  addPartComponent, getMaintenanceOverview, getPartLevels, getPartStructure, importBom, isSpreadsheetFile,
  listMaintenanceParts, positionsFromStructure, removePartComponent, setPartLevel, setPartLevels,
  updatePartComponent, SPREADSHEET_ACCEPT,
} from "../api.js";
import { Field, FormModal, PositionPicker, flatten } from "./MaintenanceParts.jsx";
import { useSpreadsheet } from "./ExcelSheetPicker.jsx";
import {
  bomFormatText, bomImportSummary, bomIsIndented, levelsIn, positionsPlanSummary, qtyNumber, qtyText, treeKeys,
} from "../maintenanceStructure.js";

const partLink = (id) => `/maintenance/parts/${id}`;

// ---- the tree ------------------------------------------------------------------------

function StructureNode({ node, path, parentId, open, toggle, onEdit, onRemove }) {
  const key = path ? `${path}/${node.id}` : node.id;
  const kids = node.children || [];
  const isOpen = open.has(key);
  const editable = parentId && (onEdit || onRemove);
  return (
    <li>
      <div className="maint-node">
        {kids.length > 0 ? (
          <button className="link maint-toggle" aria-expanded={isOpen} onClick={() => toggle(key)}
                  aria-label={`${isOpen ? "Collapse" : "Expand"} ${node.part_number}`}>{isOpen ? "▾" : "▸"}</button>
        ) : <span className="maint-toggle" aria-hidden="true" />}
        {node.qty != null && <span className="maint-qty">{qtyText(node.qty)}</span>}
        <Link className="maint-node-name" to={partLink(node.id)}>{node.part_number}</Link>
        <span>{node.name}</span>
        {node.level && <span className="maint-badge">{node.level}</span>}
        {node.ref && <span className="lib-date">{node.ref}</span>}
        {node.total != null && node.qty != null && Number(node.total) !== Number(node.qty) && (
          <span className="lib-date">{qtyNumber(node.total)} in all</span>
        )}
        {node.more && <span className="lib-date">(more not shown)</span>}
        {editable && (
          <span className="maint-chip-actions">
            {onEdit && <button className="crumb-link" onClick={() => onEdit({ parentId, node })}>edit</button>}
            {onRemove && <button className="crumb-link" onClick={() => onRemove({ parentId, node })}>remove</button>}
          </span>
        )}
      </div>
      {isOpen && kids.length > 0 && (
        <ul>{kids.map((c) => (
          <StructureNode key={`${key}/${c.id}`} node={c} path={key} parentId={node.id} open={open} toggle={toggle}
                         onEdit={onEdit} onRemove={onRemove} />
        ))}</ul>
      )}
    </li>
  );
}

// A structure tree, opened two levels down to start with. With onEdit / onRemove,
// each line (below the top) can be changed from here.
export function StructureTree({ tree, onEdit, onRemove, showTop = true }) {
  const all = useMemo(() => treeKeys(tree), [tree]);
  const [open, setOpen] = useState(() => new Set(all.filter((k) => k.split("/").length <= 2)));
  const toggle = (key) => setOpen((s) => { const n = new Set(s); n.has(key) ? n.delete(key) : n.add(key); return n; });
  const nodes = showTop ? [tree] : tree.children || [];
  const path = showTop ? "" : tree.id;
  return (
    <>
      {all.length > 2 && (
        <div className="maint-row" style={{ marginTop: 0, marginBottom: "0.5rem" }}>
          <button className="link" onClick={() => setOpen(new Set(all))}>Expand all</button>
          <button className="link" onClick={() => setOpen(new Set(showTop ? [tree.id] : []))}>Collapse all</button>
        </div>
      )}
      <ul className="maint-tree">
        {nodes.map((n) => (
          <StructureNode key={n.id} node={n} path={path} parentId={showTop ? null : tree.id} open={open}
                         toggle={toggle} onEdit={onEdit} onRemove={onRemove} />
        ))}
      </ul>
    </>
  );
}

// ---- quantities rolled up ------------------------------------------------------------------

export function RollupCard({ structure }) {
  const [every, setEvery] = useState(false);
  const rows = (structure.rollup || []).filter((r) => every || r.lowest);
  const installed = structure.items > 0;
  return (
    <section className="card">
      <div className="maint-head">
        <h2>Quantities rolled up</h2>
        <label className="maint-row lib-date" style={{ marginTop: 0, gap: "0.4rem" }}>
          <input type="checkbox" checked={every} onChange={(e) => setEvery(e.target.checked)} />
          Every level
        </label>
      </div>
      <p className="lib-date">
        How many of each part go into one {structure.part.part_number}, multiplied down the tree (an SRU inside an LRU
        counts by both quantities). {every ? "Every part below it." : "The lowest level only: tick Every level for assemblies and replaceable units too."}
      </p>
      <div className="maint-scroll"><table className="lib-table">
        <thead><tr><th>Part number</th><th>Part</th><th>Level</th><th>In one</th>
          {installed && <th>Installed ({structure.items} {structure.items === 1 ? "item" : "items"})</th>}<th>On hand</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td><Link to={partLink(r.id)}>{r.part_number}</Link></td>
              <td>{r.name}</td>
              <td className="lib-date">{r.level || "—"}</td>
              <td>{qtyNumber(r.total)} {r.unit && r.unit !== "each" ? r.unit : ""}</td>
              {installed && <td>{qtyNumber(r.installed)}</td>}
              <td className="lib-date">{qtyNumber(r.on_hand)}</td>
            </tr>
          ))}
        </tbody>
      </table></div>
    </section>
  );
}

// ---- where used --------------------------------------------------------------------------

export function WhereUsedCard({ used }) {
  const nothing = !used.parents.length && !used.positions.length && !used.items.length;
  return (
    <section className="card">
      <div className="maint-head"><h2>Where used</h2></div>
      {nothing ? <p className="lib-date">Not in any other part's structure, on any position's parts list, or fitted anywhere.</p> : (
        <>
          {used.parents.length > 0 && (
            <>
              <h3 className="maint-sub">In these parts</h3>
              <ul className="maint-list">
                {used.assemblies.map((a) => (
                  <li key={a.id}>
                    <Link to={partLink(a.id)}>{a.part_number}</Link> {a.name}
                    {a.level && <> <span className="maint-badge">{a.level}</span></>}
                    <span className="lib-date"> · {qtyNumber(a.total)} in one{a.direct ? "" : " (further up)"}
                      {a.direct && (used.parents.find((p) => p.id === a.id)?.ref) ? ` · ${used.parents.find((p) => p.id === a.id).ref}` : ""}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
          {used.positions.length > 0 && (
            <>
              <h3 className="maint-sub">Positions</h3>
              <ul className="maint-list">
                {used.positions.map((p, i) => (
                  <li key={`${p.position.id}-${p.how}-${i}`}>
                    <Link to={`/maintenance/positions/${p.position.id}`}>{p.position.name}</Link>
                    {p.position.path.length > 0 && <span className="lib-date"> · {p.position.path.join(" › ")}</span>}
                    <span className="lib-date"> · {p.how === "fitted"
                      ? <>fitted: <Link to={`/maintenance/items/${p.item.id}`}>{p.item.name}{p.item.serial ? ` ${p.item.serial}` : ""}</Link></>
                      : `on its parts list (${p.role}, ${qtyNumber(p.quantity)} a job)`}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
          {used.items.length > 0 && (
            <>
              <h3 className="maint-sub">Items ({used.counts.items})</h3>
              <ul className="maint-list">
                {used.items.map((it) => (
                  <li key={it.id}>
                    <Link to={`/maintenance/items/${it.id}`}>{it.name}</Link>
                    {it.serial && <span className="lib-date"> · {it.serial}</span>}
                    <span className="lib-date"> · {it.fitted_to ? `fitted to ${it.fitted_to.name}` : it.location || "not fitted"}
                      {!it.linked && " · its part number typed in, not linked"}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </section>
  );
}

// ---- changing a structure ---------------------------------------------------------------

// Add a line to a part's structure (line: null), or change one ({parentId, node}).
export function ComponentModal({ part, line, onClose, onDone }) {
  const [catalogue, setCatalogue] = useState(null);
  const [childId, setChildId] = useState("");
  const [qty, setQty] = useState(line ? qtyNumber(line.node.qty) : "1");
  const [ref, setRef] = useState(line?.node.ref || "");
  useEffect(() => {
    if (!line) listMaintenanceParts().then((d) => setCatalogue(d.parts)).catch(() => setCatalogue([]));
  }, [line]);
  const options = (catalogue || []).filter((p) => p.id !== part.id && !(part.components || []).some((c) => c.id === p.id));
  const submit = async () => {
    if (line) return onDone(await updatePartComponent(line.parentId, line.node.id, { quantity: qty, ref }));
    return onDone(await addPartComponent(part.id, { childId, quantity: qty, ref }));
  };
  return (
    <FormModal title={line ? `${line.node.part_number} in ${line.parentId === part.id ? part.part_number : "its assembly"}`
                             : `Add a part to ${part.part_number}`}
               submitLabel={line ? "Save" : "Add"} canSubmit={(line || childId) && Number(qty) > 0} onClose={onClose}
               onSubmit={submit}>
      {!line && (
        <Field label="Part">
          {catalogue === null ? <span className="lib-date">Loading…</span> : (
            <select autoFocus value={childId} onChange={(e) => setChildId(e.target.value)}>
              <option value="">Choose…</option>
              {options.map((p) => <option key={p.id} value={p.id}>{p.part_number} {p.name}{p.level ? ` (${p.level})` : ""}</option>)}
            </select>
          )}
        </Field>
      )}
      <Field label={`How many in one ${part.part_number}`}>
        <input type="number" inputMode="decimal" min="0" step="any" value={qty} onChange={(e) => setQty(e.target.value)} />
      </Field>
      <Field label="Reference (optional)">
        <input value={ref} placeholder="e.g. B1, B2 (a designator or position in the assembly)" onChange={(e) => setRef(e.target.value)} />
      </Field>
      {!line && <p className="lib-date">A part can't go inside one it's already inside: that would make a loop.</p>}
    </FormModal>
  );
}

export async function removeLine(line) {
  return removePartComponent(line.parentId, line.node.id);
}

// A part's indenture level, from the workspace's list.
export function LevelModal({ part, onClose, onDone }) {
  const [levels, setLevels] = useState(null);
  const [level, setLevel] = useState(part.level || "");
  useEffect(() => {
    getPartLevels().then((d) => setLevels(d.levels)).catch(() => setLevels([]));
  }, []);
  return (
    <FormModal title={`Indenture level of ${part.part_number}`} submitLabel="Save" onClose={onClose}
               onSubmit={async () => onDone(await setPartLevel(part.id, level))}>
      <Field label="Level">
        <select autoFocus value={level} onChange={(e) => setLevel(e.target.value)}>
          <option value="">None</option>
          {(levels || []).map((l) => <option key={l.name} value={l.name}>{l.name}</option>)}
        </select>
      </Field>
      <p className="lib-date">Where it sits in a structure: a system, an assembly, a line-replaceable unit… The list is the
        workspace's own: change it from the Parts page.</p>
    </FormModal>
  );
}

// The workspace's indenture level list: rename (the parts at a level follow), add,
// reorder, and remove one no part is at.
export function LevelsModal({ onClose, onDone }) {
  const [rows, setRows] = useState(null);
  useEffect(() => {
    getPartLevels().then((d) => setRows(d.levels.map((l) => ({ was: l.name, name: l.name, parts: l.parts }))))
      .catch(() => setRows([]));
  }, []);
  const set = (i, name) => setRows(rows.map((r, j) => (j === i ? { ...r, name } : r)));
  const move = (i, by) => {
    const next = [...rows];
    [next[i], next[i + by]] = [next[i + by], next[i]];
    setRows(next);
  };
  const submit = async () => {
    const kept = rows.filter((r) => r.name.trim());
    const renamed = Object.fromEntries(kept.filter((r) => r.was && r.was !== r.name.trim()).map((r) => [r.was, r.name.trim()]));
    onDone(await setPartLevels(kept.map((r) => r.name.trim()), renamed));
  };
  return (
    <FormModal title="Indenture levels" submitLabel="Save" canSubmit={!!rows?.some((r) => r.name.trim())}
               onClose={onClose} onSubmit={submit}>
      <p className="lib-date">Top first. Rename a level and the parts at it follow. A level parts are at can't be removed.</p>
      {rows === null ? <p className="lib-date">Loading…</p> : (
        <ol className="maint-levels">
          {rows.map((r, i) => (
            <li key={i}>
              <input aria-label={`Level ${i + 1}`} value={r.name} maxLength={60} onChange={(e) => set(i, e.target.value)} />
              <span className="lib-date">{r.parts ? `${r.parts} part${r.parts === 1 ? "" : "s"}` : ""}</span>
              <button className="crumb-link" disabled={i === 0} onClick={() => move(i, -1)} aria-label="Move up">↑</button>
              <button className="crumb-link" disabled={i === rows.length - 1} onClick={() => move(i, 1)} aria-label="Move down">↓</button>
              <button className="crumb-link" disabled={r.parts > 0} aria-label={`Remove ${r.name || "this level"}`}
                      title={r.parts > 0 ? "Parts are at this level" : "Remove"} onClick={() => setRows(rows.filter((_, j) => j !== i))}>×</button>
            </li>
          ))}
        </ol>
      )}
      {rows && <button className="secondary" onClick={() => setRows([...rows, { was: null, name: "", parts: 0 }])}>Add a level</button>}
    </FormModal>
  );
}

// ---- importing a BOM -----------------------------------------------------------------------

const FIELD_NAMES = {
  parent: "parent part number", part_number: "part number", quantity: "quantity", name: "nomenclature",
  level: "indenture level", bom_level: "BOM level", manufacturer: "manufacturer", ref: "reference",
};

export function ImportBomModal({ onClose, onDone }) {
  const [file, setFile] = useState(null);
  const [sheet, setSheet] = useState(null);
  const [preview, setPreview] = useState(null);
  const [byDepth, setByDepth] = useState(false);
  const { chooseSheet, modal } = useSpreadsheet();
  const pick = async (f) => {
    setPreview(null); setSheet(null); setFile(null); setByDepth(false);
    if (!f) return;
    if (isSpreadsheetFile(f)) {
      const choice = await chooseSheet(f);
      if (!choice) return;
      setSheet(choice);
    }
    setFile(f);
  };
  const send = (dryRun, levelsByDepth = byDepth) =>
    importBom(file, { dryRun, sheet: sheet?.sheet, headerRow: sheet?.headerRow, levelsByDepth });
  const nameByDepth = async (on) => {  // checked again with the names, so the preview shows them
    setByDepth(on);
    try { setPreview(await send(true, on)); } catch { setPreview(null); }
  };
  return (
    <>
      <FormModal title="Import a BOM" submitLabel={preview?.ok ? "Import" : "Check it"} canSubmit={!!file} onClose={onClose}
                 onSubmit={async () => (preview?.ok ? onDone(await send(false)) : setPreview(await send(true)))}>
        <p className="lib-date">
          A bill of materials as CSV or Excel, one row per line: the parent's part number (NHA), the part number that goes
          in it (PN), the quantity, and optionally nomenclature, indenture level, manufacturer and reference. An indented
          BOM works too: rows in tree order with a level instead of a parent (0/1/2, .1/..2, 1.1.2 or an LCN). Parts are
          matched by part number and missing ones are created. Every row is checked first; if any is wrong, nothing is
          imported. Running the same file again changes nothing.
        </p>
        <Field label="File"><input type="file" accept={`.csv,${SPREADSHEET_ACCEPT}`} onChange={(e) => pick(e.target.files[0] || null)} /></Field>
        {sheet && <p className="lib-date">Sheet {sheet.sheet}{sheet.headerRow ? `, headers in row ${sheet.headerRow}` : ""}.</p>}
        {preview && (
          <>
            <p>{bomImportSummary(preview)}</p>
            {preview.format && <p className="lib-date">Read as: {bomFormatText(preview)}</p>}
            {bomIsIndented(preview) && (
              <label className="maint-row lib-date" style={{ marginTop: 0, gap: "0.4rem" }}>
                <input type="checkbox" checked={byDepth} onChange={(e) => nameByDepth(e.target.checked)} />
                Name each part's indenture level by its depth, from this workspace's list (a part's own indenture
                level column still wins)
              </label>
            )}
            <p className="lib-date">Columns: {Object.entries(preview.columns).map(([f, c]) => `${FIELD_NAMES[f] || f} = "${c}"`).join("; ")}.</p>
            {preview.errors.length > 0 && (
              <ul className="maint-list">{preview.errors.map((e, i) => <li key={i} className="maint-overdue">{e.row ? `Row ${e.row}: ` : ""}{e.error}</li>)}</ul>
            )}
            {preview.conflicts.length > 0 && (
              <ul className="maint-list">{preview.conflicts.map((x, i) => <li key={i} className="lib-date">{x.part_number}, {x.field}: {x.why}</li>)}</ul>
            )}
          </>
        )}
      </FormModal>
      {modal}
    </>
  );
}

// ---- positions from a structure ----------------------------------------------------------

export function PositionsFromStructureModal({ structure, onClose, onDone }) {
  const [positions, setPositions] = useState(null);
  const [parentId, setParentId] = useState(null);
  const found = levelsIn(structure.tree, structure.indenture_levels);
  const [every, setEvery] = useState(found.length === 0);
  const [chosen, setChosen] = useState(new Set(found));
  const [preview, setPreview] = useState(null);
  useEffect(() => {
    getMaintenanceOverview().then((d) => setPositions(flatten(d.tree))).catch(() => setPositions([]));
  }, []);
  const opts = (dryRun) => ({ parentId, levels: every ? null : found.filter((l) => chosen.has(l)), dryRun });
  const flip = (l) => { const n = new Set(chosen); n.has(l) ? n.delete(l) : n.add(l); setChosen(n); setPreview(null); };
  return (
    <FormModal title={`Positions from ${structure.part.part_number}`} submitLabel={preview ? "Create positions" : "Check it"}
               canSubmit={every || chosen.size > 0} onClose={onClose}
               onSubmit={async () => (preview ? onDone(await positionsFromStructure(structure.part.id, opts(false)))
                 : setPreview(await positionsFromStructure(structure.part.id, opts(true))))}>
      <p className="lib-date">Turns the structure into positions: one for each part and each one of its quantity (Pump unit 1,
        Pump unit 2), tagged with the line's references, each with its part as the replacement part. Positions already there
        with the same name are used again.</p>
      <Field label="Under">
        {positions === null ? <span className="lib-date">Loading…</span>
          : <PositionPicker positions={positions} value={parentId} onChange={(v) => { setParentId(v); setPreview(null); }} />}
      </Field>
      <fieldset className="maint-fieldset">
        <legend>Which levels become positions</legend>
        <label className="maint-row" style={{ marginTop: 0, gap: "0.4rem" }}>
          <input type="radio" checked={every} onChange={() => { setEvery(true); setPreview(null); }} /> Every part
        </label>
        {found.length > 0 && (
          <label className="maint-row" style={{ marginTop: "0.25rem", gap: "0.4rem" }}>
            <input type="radio" checked={!every} onChange={() => { setEvery(false); setPreview(null); }} /> Only these levels:
          </label>
        )}
        {!every && (
          <div className="maint-row" style={{ marginTop: "0.25rem" }}>
            {found.map((l) => (
              <label key={l} style={{ display: "inline-flex", gap: "0.3rem", alignItems: "center" }}>
                <input type="checkbox" checked={chosen.has(l)} onChange={() => flip(l)} /> {l}
              </label>
            ))}
          </div>
        )}
        {!every && <p className="lib-date">A part at another level (or none) is passed through: what's inside it comes in under the position above.</p>}
      </fieldset>
      {preview && (
        <>
          <p>{positionsPlanSummary(preview)}</p>
          <ul className="maint-list">
            {preview.positions.slice(0, 40).map((r, i) => (
              <li key={i} className={r.new ? undefined : "lib-date"}>{r.path}{r.tag && <span className="lib-date"> · {r.tag}</span>}
                {!r.new && " (already there)"}</li>
            ))}
          </ul>
          {preview.positions.length > 40 && <p className="lib-date">and {preview.positions.length - 40} more.</p>}
        </>
      )}
    </FormModal>
  );
}

// ---- an item's part, read-only -------------------------------------------------------------

// On an item's page: its part's structure, when the part has one.
export function ItemPartStructureCard({ part }) {
  const [structure, setStructure] = useState(null);
  useEffect(() => {
    if (part?.id) getPartStructure(part.id).then(setStructure).catch(() => setStructure(null));
  }, [part?.id]);
  if (!structure || !(structure.tree.children || []).length) return null;
  return (
    <section className="card">
      <div className="maint-head">
        <h2>What it's made of</h2>
        <Link to={partLink(part.id)}>{part.part_number}'s structure</Link>
      </div>
      <p className="lib-date">As designed: the structure of its part, {part.part_number}. Change it on the part's page.</p>
      <StructureTree tree={structure.tree} showTop={false} />
    </section>
  );
}

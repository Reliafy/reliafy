// Conditions (optional): what locations, positions, items and connections are
// exposed to (Outdoor, Seawater, Zone 1, Ambient temperature). The Classes page's
// register, and the card on location, position and item pages: the conditions that
// apply, set there or inherited from above, with add, remove and exclude.
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  createCondition, downloadConditions, getCondition, getConditions, importConditions, retireCondition,
  setTargetCondition, updateCondition,
} from "../api.js";
import { Field, FormModal } from "./MaintenanceParts.jsx";
import { subtreeIds } from "../maintenanceItemClasses.js";
import {
  conditionImportSummary, conditionKindText, conditionText, pickable, sourcePath, sourceText,
} from "../maintenanceConditions.js";

// ---- on a location, position or item ----------------------------------------------------------

function SourceLink({ entry }) {
  const to = sourcePath(entry.source);
  if (entry.own || !to) return <>{sourceText(entry)}</>;
  return <>{entry.excluded ? "excluded at" : "from"} <Link to={to}>{entry.source.name}</Link></>;
}

// view: {conditions, excluded_conditions} as the page's record carries them.
export function ConditionsCard({ target, view, onChanged, emptyText }) {
  const [modal, setModal] = useState(null);
  const [error, setError] = useState(null);
  const applied = view.conditions || [];
  const excluded = view.excluded_conditions || [];
  const act = async (body) => {
    setError(null);
    try { await setTargetCondition(target.id, body); onChanged(); } catch (e) { setError(e.message); }
  };
  return (
    <section className="card">
      <div className="maint-head">
        <h2>Conditions</h2>
        <button className="secondary" onClick={() => setModal({})}>Add a condition</button>
      </div>
      {error && <div className="card error">{error}</div>}
      {applied.length + excluded.length === 0 ? (
        <p className="lib-date">{emptyText || `Nothing recorded. Say what ${target.name} is exposed to (outdoors, seawater, a hazardous area, heat): what's inside it takes it too.`}</p>
      ) : (
        <ul className="maint-chips">
          {applied.map((e) => (
            <li key={e.condition.id} className={`maint-chip${e.own ? "" : " maint-chip-inherited"}`}>
              <span className="maint-chip-name">{conditionText(e)}</span>
              {e.note && <span className="lib-date">{e.note}</span>}
              <span className="lib-date"><SourceLink entry={e} /></span>
              <span className="maint-chip-actions">
                {e.own ? (
                  <>
                    <button className="crumb-link" onClick={() => setModal({ entry: e })}>edit</button>
                    <button className="crumb-link" onClick={() => act({ conditionId: e.condition.id, action: "remove" })}>remove</button>
                  </>
                ) : (
                  <>
                    {e.condition.kind === "value" && (
                      <button className="crumb-link" onClick={() => setModal({ entry: { ...e, own: false } })}>own value</button>
                    )}
                    {target.kind !== "Interface" && (
                      <button className="crumb-link" onClick={() => act({ conditionId: e.condition.id, action: "exclude" })}>exclude</button>
                    )}
                  </>
                )}
              </span>
            </li>
          ))}
          {excluded.map((e) => (
            <li key={e.condition.id} className="maint-chip maint-chip-excluded">
              <span className="maint-chip-name"><s>{e.condition.display}</s></span>
              <span className="lib-date"><SourceLink entry={e} /></span>
              {e.own && (
                <span className="maint-chip-actions">
                  <button className="crumb-link" onClick={() => act({ conditionId: e.condition.id, action: "remove" })}>undo</button>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      {modal && <ConditionModal target={target} view={view} entry={modal.entry} onClose={() => setModal(null)}
                                onDone={() => { setModal(null); onChanged(); }} />}
    </section>
  );
}

// A connection's own conditions (it inherits none), in its line on the position page.
export function ConnectionConditions({ connection, name, onChanged }) {
  const [modal, setModal] = useState(false);
  const own = connection.conditions || [];
  const target = { id: connection.id, name, kind: "Interface" };
  return (
    <>
      {own.map((e) => (
        <span key={e.condition.id} className="maint-chip maint-chip-small">
          {conditionText(e)}
          <button className="crumb-link" aria-label={`Remove ${e.condition.name}`}
                  onClick={() => setTargetCondition(connection.id, { conditionId: e.condition.id, action: "remove" })
                    .then(onChanged).catch(() => onChanged())}>×</button>
        </span>
      ))}
      <button className="crumb-link" onClick={() => setModal(true)}>add condition</button>
      {modal && <ConditionModal target={target} view={{ conditions: own }} onClose={() => setModal(false)}
                                onDone={() => { setModal(false); onChanged(); }} />}
    </>
  );
}

function ConditionModal({ target, view, entry, onClose, onDone }) {
  const [register, setRegister] = useState(null);
  const [conditionId, setConditionId] = useState(entry?.condition.id || "");
  const [value, setValue] = useState(entry?.own ? entry.value ?? "" : "");
  const [note, setNote] = useState(entry?.own ? entry.note || "" : "");
  useEffect(() => {
    getConditions().then((d) => setRegister(d.conditions || [])).catch(() => setRegister([]));
  }, []);
  const chosen = entry?.condition || (register || []).find((c) => c.id === conditionId);
  const options = pickable(register || [], view);
  return (
    <FormModal title={entry ? `${entry.condition.display} on ${target.name}` : `What ${target.name} is exposed to`}
               submitLabel="Save" canSubmit={!!chosen} onClose={onClose}
               onSubmit={async () => onDone(await setTargetCondition(target.id, {
                 conditionId: chosen.id, action: "apply", value: value === "" ? null : value, note,
               }))}>
      {!entry && (
        <Field label="Condition">
          {register === null ? <span className="lib-date">Loading…</span> : register.length === 0 ? (
            <span className="lib-date">The register is empty: add conditions on the <Link to="/maintenance/classes">Classes</Link> page first.</span>
          ) : (
            <select autoFocus value={conditionId} onChange={(e) => setConditionId(e.target.value)}>
              <option value="">Choose…</option>
              {options.map((c) => <option key={c.id} value={c.id}>{c.display}{c.unit ? ` (${c.unit})` : ""}</option>)}
            </select>
          )}
        </Field>
      )}
      {chosen?.kind === "value" && (
        <Field label={`Value${chosen.unit ? ` (${chosen.unit})` : ""}, if known`}>
          <input type="number" inputMode="decimal" step="any" value={value} onChange={(e) => setValue(e.target.value)} />
        </Field>
      )}
      <Field label="Note (optional)">
        <input value={note} placeholder="e.g. salt spray, severe" onChange={(e) => setNote(e.target.value)} />
      </Field>
      {target.kind === "Interface" ? (
        <p className="lib-date">A connection has only its own conditions: none come from the positions at either end.</p>
      ) : (
        <p className="lib-date">Set here, it applies to everything inside or under {target.name} too, unless one of them excludes it.
          A value set lower down wins over one from above.</p>
      )}
    </FormModal>
  );
}

// ---- the Classes page: the register ---------------------------------------------------------

function ConditionNode({ node, selected, onSelect }) {
  return (
    <li>
      <div className="maint-node">
        <button className="link maint-node-name" aria-current={selected === node.id ? "true" : undefined} onClick={() => onSelect(node.id)}>
          {node.name}
        </button>
        {node.unit && <span className="maint-badge">{node.unit}</span>}
        {node.code && <span className="lib-date">{node.code}</span>}
        <span className="maint-node-item">
          {node.applied ? `set on ${node.applied}` : "not used yet"}{node.excluded ? ` · excluded on ${node.excluded}` : ""}
        </span>
      </div>
      {node.children.length > 0 && (
        <ul>{node.children.map((c) => <ConditionNode key={c.id} node={c} selected={selected} onSelect={onSelect} />)}</ul>
      )}
    </li>
  );
}

export function ConditionsSection() {
  const [data, setData] = useState(null);
  const [selected, setSelected] = useState(null);
  const [modal, setModal] = useState(null);
  const [error, setError] = useState(null);
  const load = useCallback(() => {
    getConditions().then(setData).catch((e) => setError(e.message));
  }, []);
  useEffect(() => load(), [load]);
  const download = (format) => downloadConditions(format).catch((e) => setError(e.message));
  const empty = data && data.tree.length === 0;
  return (
    <>
      <section className="card">
        <div className="maint-head">
          <h2>Conditions</h2>
          <div className="maint-row" style={{ marginTop: 0 }}>
            <button className="secondary" onClick={() => setModal("import")}>Import</button>
            {!empty && <button className="secondary" onClick={() => download("csv")}>Export CSV</button>}
            {!empty && <button className="secondary" onClick={() => download("json")}>Export JSON</button>}
            <button onClick={() => setModal({ create: null })}>New condition</button>
          </div>
        </div>
        {error && <div className="card error">{error}</div>}
        {data === null ? <p className="lib-date">Loading…</p> : empty ? (
          <p className="lib-date">
            Optional. Your own list of what places and equipment are exposed to: Outdoor, Coastal, Seawater, Hazardous
            area › Zone 1, or a value such as Ambient temperature in °C. Set them on locations, positions and items: what's
            inside or under them takes them too. Add them one at a time or import your list (CSV or JSON).
          </p>
        ) : (
          <ul className="maint-tree">
            {data.tree.map((n) => <ConditionNode key={n.id} node={n} selected={selected} onSelect={setSelected} />)}
          </ul>
        )}
      </section>
      {selected && data && (
        <ConditionPanel key={selected} id={selected} data={data}
                        onChanged={load} onRetired={() => { setSelected(null); load(); }}
                        onAddChild={() => setModal({ create: selected })} />
      )}
      {modal?.create !== undefined && (
        <NewConditionModal parentId={modal.create} conditions={data?.conditions || []} onClose={() => setModal(null)}
                           onDone={(c) => { setModal(null); setSelected(c.id); load(); }} />
      )}
      {modal === "import" && <ImportConditionsModal onClose={() => setModal(null)} onDone={() => { setModal(null); load(); }} />}
    </>
  );
}

function TargetRows({ rows, condition }) {
  return (
    <ul className="maint-list">
      {rows.map((r) => {
        const to = sourcePath({ kind: r.kind, id: r.id });
        return (
          <li key={r.id}>{to ? <Link to={to}>{r.name}</Link> : r.name}
            <span className="lib-date">
              {" · "}{r.kind === "Interface" ? "connection" : r.kind.toLowerCase()}
              {r.value !== null && r.value !== undefined && ` · ${conditionText({ condition, value: r.value }).split(": ").pop()}`}
              {r.note && ` · ${r.note}`}
            </span></li>
        );
      })}
    </ul>
  );
}

function ConditionPanel({ id, data, onChanged, onRetired, onAddChild }) {
  const [c, setC] = useState(null);
  const [modal, setModal] = useState(null);
  const [error, setError] = useState(null);
  const load = useCallback(() => {
    getCondition(id).then(setC).catch((e) => setError(e.message));
  }, [id]);
  useEffect(() => load(), [load]);
  const changed = (d) => { setC(d); setModal(null); onChanged(); };
  const retire = async () => {
    setError(null);
    try { await retireCondition(id); onRetired(); } catch (e) { setError(e.message); }
  };
  if (!c) return <section className="card">{error ? <div className="card error">{error}</div> : <p className="lib-date">Loading…</p>}</section>;
  return (
    <section className="card">
      <div className="maint-head">
        <h2>{c.display}</h2>
        <div className="maint-row" style={{ marginTop: 0 }}>
          <button className="secondary" onClick={() => setModal("edit")}>Edit</button>
          <button className="secondary" onClick={() => setModal("move")}>Move</button>
          <button className="secondary" onClick={onAddChild}>Add a condition inside</button>
          <button className="secondary" onClick={retire}>Retire</button>
        </div>
      </div>
      {error && <div className="card error">{error}</div>}
      <dl className="maint-plate">
        <dt>Kind</dt><dd>{conditionKindText(c)}</dd>
        {c.code && <><dt>Code</dt><dd>{c.code}</dd></>}
        {c.description && <><dt>Description</dt><dd>{c.description}</dd></>}
        {c.source && <><dt>From</dt><dd>{c.source}</dd></>}
      </dl>
      <h3>Set on ({c.applied_to.length})</h3>
      {c.applied_to.length === 0 ? (
        <p className="lib-date">Nowhere yet. Add it on a location's, position's or item's page; what's inside or under it takes it too.</p>
      ) : <TargetRows rows={c.applied_to} condition={c} />}
      {c.excluded_on.length > 0 && (
        <>
          <h3>Excluded on ({c.excluded_on.length})</h3>
          <TargetRows rows={c.excluded_on} condition={c} />
        </>
      )}
      {modal === "edit" && <EditConditionModal c={c} onClose={() => setModal(null)} onDone={changed} />}
      {modal === "move" && <MoveConditionModal c={c} data={data} onClose={() => setModal(null)} onDone={changed} />}
    </section>
  );
}

function ConditionPicker({ conditions, value, onChange, emptyLabel = "None", exclude }) {
  return (
    <select value={value || ""} onChange={(e) => onChange(e.target.value || null)}>
      <option value="">{emptyLabel}</option>
      {(conditions || []).filter((c) => !exclude?.has(c.id)).map((c) => <option key={c.id} value={c.id}>{c.display}</option>)}
    </select>
  );
}

function KindFields({ f, setF }) {
  return (
    <>
      <Field label="Kind">
        <select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value, unit: e.target.value === "value" ? f.unit : "" })}>
          <option value="presence">Applies or not (e.g. Outdoor)</option>
          <option value="value">A value (e.g. Ambient temperature)</option>
        </select>
      </Field>
      {f.kind === "value" && (
        <Field label="Unit (optional)"><input value={f.unit} placeholder="e.g. °C, %RH, ppt" maxLength={20}
                                              onChange={(e) => setF({ ...f, unit: e.target.value })} /></Field>
      )}
    </>
  );
}

function NewConditionModal({ parentId, conditions, onClose, onDone }) {
  const [f, setF] = useState({ name: "", parent_id: parentId, kind: "presence", unit: "", code: "", description: "" });
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  return (
    <FormModal title="New condition" submitLabel="Create" canSubmit={!!f.name.trim()} onClose={onClose}
               onSubmit={async () => onDone(await createCondition(f))}>
      <Field label="Name"><input autoFocus value={f.name} placeholder="e.g. Outdoor, Seawater, Zone 1" onChange={set("name")} /></Field>
      <Field label="Inside"><ConditionPicker conditions={conditions} value={f.parent_id} emptyLabel="Nothing (top level)"
                                             onChange={(v) => setF({ ...f, parent_id: v })} /></Field>
      <KindFields f={f} setF={setF} />
      <Field label="Code (optional: your own)"><input value={f.code} onChange={set("code")} /></Field>
      <Field label="Description (optional)"><input value={f.description} onChange={set("description")} /></Field>
    </FormModal>
  );
}

function EditConditionModal({ c, onClose, onDone }) {
  const [f, setF] = useState({ name: c.name, kind: c.kind, unit: c.unit, code: c.code, description: c.description });
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  return (
    <FormModal title={`Edit ${c.name}`} submitLabel="Save" canSubmit={!!f.name.trim()} onClose={onClose}
               onSubmit={async () => onDone(await updateCondition(c.id, f))}>
      <Field label="Name"><input value={f.name} onChange={set("name")} /></Field>
      <KindFields f={f} setF={setF} />
      <Field label="Code"><input value={f.code} onChange={set("code")} /></Field>
      <Field label="Description"><input value={f.description} onChange={set("description")} /></Field>
    </FormModal>
  );
}

function MoveConditionModal({ c, data, onClose, onDone }) {
  const [to, setTo] = useState(c.parent?.id || null);
  const exclude = subtreeIds(data.tree, c.id);
  return (
    <FormModal title={`Move ${c.name}`} submitLabel="Move" onClose={onClose}
               onSubmit={async () => onDone(await updateCondition(c.id, { parent_id: to }))}>
      <p className="lib-date">The conditions inside it go with it; where it's set doesn't change.</p>
      <Field label="Inside"><ConditionPicker conditions={data.conditions} value={to} exclude={exclude}
                                             emptyLabel="Nothing (top level)" onChange={setTo} /></Field>
    </FormModal>
  );
}

function ImportConditionsModal({ onClose, onDone }) {
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
    <FormModal title="Import conditions" submitLabel={preview?.ok ? "Import" : "Check it"} canSubmit={text !== null}
               onClose={onClose}
               onSubmit={async () => (preview?.ok ? (await importConditions(body(false)), onDone())
                 : setPreview(await importConditions(body(true))))}>
      <p className="lib-date">
        Your site's list as CSV or JSON. CSV columns: path (Hazardous area &gt; Zone 1), and optionally kind (presence or
        value), unit, code and description. Conditions already here are matched by path and only gain what they lack.
        Every row is checked first; if any is wrong, nothing is imported.
      </p>
      <Field label="File"><input type="file" accept=".csv,.json" onChange={(e) => pick(e.target.files[0] || null)} /></Field>
      {preview && (
        <>
          <p>{conditionImportSummary(preview)}</p>
          {preview.errors.length > 0 && (
            <ul className="maint-list">{preview.errors.map((e, i) => <li key={i} className="maint-overdue">{e.row ? `${e.row}: ` : ""}{e.error}</li>)}</ul>
          )}
          {preview.conflicts.length > 0 && (
            <ul className="maint-list">{preview.conflicts.map((x, i) => <li key={i} className="lib-date">{x.path}, {x.field}: {x.why}</li>)}</ul>
          )}
        </>
      )}
    </FormModal>
  );
}

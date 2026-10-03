import { useState } from "react";
import Select from "./Select.jsx";

// Map a spreadsheet's columns onto an importer's fields. ``fields`` come from
// the server with the table (/api/excel/table?target=…): { id, label, help?,
// required?, group? }; ``mapping`` is { fieldId: columnName } (the server's
// guess from header names and synonyms to start with). Required fields are
// starred, a column used twice is flagged, and ``rows`` (sample rows as
// strings, in ``columns`` order) preview the mapped result.
//
// (The life-data ColumnMapper maps CSV columns to SurPyval's x/c/n/…; this is
// its general-purpose sibling for spreadsheet imports.)
export default function SheetColumnMapper({
  fields, columns, mapping, onChange, rows = [], previewRows = 4, requireOneOf, collapsed = [],
}) {
  // Optional groups (``collapsed`` titles) stay folded until opened or mapped.
  const [opened, setOpened] = useState([]);
  const set = (id, col) => onChange({ ...mapping, [id]: col });
  const groups = [];
  for (const f of fields) {
    const g = f.group || "";
    let entry = groups.find((x) => x.title === g);
    if (!entry) groups.push((entry = { title: g, fields: [] }));
    entry.fields.push(f);
  }
  const counts = {};
  for (const col of Object.values(mapping)) if (col) counts[col] = (counts[col] || 0) + 1;
  const missing = fields.filter((f) => f.required && !mapping[f.id]);
  const oneOfMissing = requireOneOf && !requireOneOf.some((id) => mapping[id]);
  const dupes = Object.entries(counts).filter(([, n]) => n > 1).map(([c]) => c);
  const mapped = fields.filter((f) => mapping[f.id] && columns.includes(mapping[f.id]));
  const colIndex = Object.fromEntries(columns.map((c, i) => [c, i]));

  return (
    <div className="xl-mapper">
      {groups.map((g) => {
        const folded = collapsed.includes(g.title) && !opened.includes(g.title)
          && !g.fields.some((f) => mapping[f.id]);
        if (folded) {
          return (
            <button key={g.title} type="button" className="xl-map-more"
                    onClick={() => setOpened((o) => [...o, g.title])}>
              + {g.title} · {g.fields.length} optional column{g.fields.length === 1 ? "" : "s"}
            </button>
          );
        }
        return (
        <div key={g.title || "_"} className="xl-map-group">
          {g.title && <div className="map-group-title"><span>{g.title}</span></div>}
          <div className="xl-map-fields">
            {g.fields.map((f) => {
              const col = mapping[f.id] || "";
              const required = f.required || requireOneOf?.includes(f.id);
              return (
                <label
                  key={f.id}
                  className={"xl-map-field" + (col ? " selected" : "") + (col && counts[col] > 1 ? " dupe" : "")}
                  title={f.help || f.label}
                >
                  <span className="xl-map-label">
                    {f.label}
                    {required && <i className="req" title={f.required ? "Required" : "One of these is required"}>*</i>}
                  </span>
                  <Select
                    className="sel-embedded"
                    value={col}
                    onChange={(v) => set(f.id, v)}
                    options={[{ value: "", label: "— none —" }, ...columns]}
                  />
                  {f.help && <span className="xl-map-help">{f.help}</span>}
                </label>
              );
            })}
          </div>
        </div>
        );
      })}

      {(missing.length > 0 || oneOfMissing || dupes.length > 0) && (
        <ul className="xl-issues">
          {missing.map((f) => (
            <li key={f.id}>Map a column to <b>{f.label}</b> — it's required.</li>
          ))}
          {oneOfMissing && (
            <li>
              Map a column to{" "}
              {requireOneOf.map((id, i) => (
                <span key={id}>{i > 0 && " or "}<b>{fields.find((f) => f.id === id)?.label}</b></span>
              ))}
              .
            </li>
          )}
          {dupes.map((c) => (
            <li key={c} className="warn">“{c}” is mapped to more than one field.</li>
          ))}
        </ul>
      )}

      {mapped.length > 0 && rows.length > 0 && (
        <div>
          <div className="ds-section-h">Mapped preview · first {Math.min(previewRows, rows.length)} rows</div>
          <div className="preview-wrap" style={{ marginBottom: 0 }}>
            <table className="preview-table">
              <thead>
                <tr>{mapped.map((f) => <th key={f.id}>{f.label}</th>)}</tr>
              </thead>
              <tbody>
                {rows.slice(0, previewRows).map((r, i) => (
                  <tr key={i}>
                    {mapped.map((f) => <td key={f.id}>{r[colIndex[mapping[f.id]]]}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// Whether the mapping satisfies the fields' requirements.
export function mappingComplete(fields, mapping, requireOneOf) {
  if (fields.some((f) => f.required && !mapping[f.id])) return false;
  if (requireOneOf && !requireOneOf.some((id) => mapping[id])) return false;
  return true;
}

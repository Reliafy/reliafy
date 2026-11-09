import { useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { getLibrarySources, searchLibrary } from "../api.js";
import Modal from "./Modal.jsx";
import { Select, TextInput } from "./ui/Controls.jsx";
import { KIND_LABEL, leftOutWords, rangeText, recordPath, sig } from "../libraryModels.js";
import {
  defaultLibrary, facetOptions, lastLibrary, libraryOptions, moveHighlight, rememberLibrary, rowDetail, showsKind, valueText,
} from "../libraryPicker.js";
import "./LibraryRecordPicker.css";

// "Pick a library record": a wide modal search over the data library, opened over a dialog with
// little room (the Fit dialog's Prior, Life model › From the data library…). A search box, the
// library, Equipment type and Failure mode (and Kind where there's a choice), then the records as a
// table (as on a library's own page); on a phone each row is a card: the name, one grey line.
// Only the records usable for ``use`` ("prior" or "model") are listed; a grey line says what was
// left out and why. Arrow keys move the highlight, Enter or a click picks; picking closes it and
// hands the record (a search row) to ``onPick``. Escape closes only this, and focus goes back to
// the button that opened it (Modal).

const PAGE = 100; // the search's most a page

export default function LibraryRecordPicker({ use = "prior", selectedId = null, onPick, onClose }) {
  const listId = useId();
  const [sources, setSources] = useState(null);
  const [labels, setLabels] = useState({});
  const [source, setSource] = useState(null); // null until the sources say which to open on
  const [q, setQ] = useState("");
  const [equipment, setEquipment] = useState("");
  const [mode, setMode] = useState("");
  const [kind, setKind] = useState("");
  const [found, setFound] = useState(null); // {rows, total, facets, leftOut} | {failed}
  const [hi, setHi] = useState(0);
  const listRef = useRef(null);

  useEffect(() => {
    let live = true;
    getLibrarySources().then((d) => {
      if (!live) return;
      setSources(d.sources || []);
      setLabels(d.equipment_types || {});
      setSource(defaultLibrary(d.sources || [], lastLibrary()));
    }, () => { if (live) { setSources([]); setSource(""); } });
    return () => { live = false; };
  }, []);

  useEffect(() => {
    if (source === null) return undefined;
    let live = true;
    const t = setTimeout(() => {
      searchLibrary({ q: q.trim() || undefined, source: source || undefined, equipmentType: equipment || undefined,
        failureMode: mode || undefined, kind: kind || undefined, use, facets: true, pageSize: PAGE })
        .then((d) => {
          if (!live) return;
          const rows = d.results || [];
          setFound({ rows, total: d.total ?? rows.length, facets: d.facets || {}, leftOut: d.left_out || null });
          const at = rows.findIndex((r) => r.id === selectedId);
          setHi(at >= 0 ? at : 0);
        }, (e) => live && setFound({ rows: [], total: 0, facets: {}, failed: e.message }));
    }, 200);
    return () => { live = false; clearTimeout(t); };
  }, [q, source, equipment, mode, kind, use, selectedId]);

  // Keep the highlighted row in view as the arrow keys move it.
  useEffect(() => {
    const el = listRef.current?.querySelector(`[data-index="${hi}"]`);
    if (el && typeof el.scrollIntoView === "function") el.scrollIntoView({ block: "nearest" });
  }, [hi, found]);

  const rows = found?.rows || [];
  const pick = (r) => {
    if (!r) return;
    rememberLibrary(source || "");
    onPick(r);
  };
  const onKeyDown = (e) => {
    const tag = e.target.tagName;
    if (tag === "SELECT" || tag === "BUTTON" || tag === "A") return; // their own keys
    if (e.key === "Enter") {
      if (rows[hi]) { e.preventDefault(); pick(rows[hi]); }
      return;
    }
    // Home and End stay with the search box's text.
    if (tag === "INPUT" && (e.key === "Home" || e.key === "End")) return;
    const next = moveHighlight(hi, e.key, rows.length);
    if (next !== null) { e.preventDefault(); setHi(next); }
  };
  const changeLibrary = (id) => {
    setSource(id);
    setEquipment("");
    setMode("");
    setKind("");
  };
  const clear = () => { setQ(""); setEquipment(""); setMode(""); setKind(""); };
  const filtered = !!(q.trim() || equipment || mode || kind);
  const facets = found?.facets || {};
  const hidden = leftOutWords(found?.leftOut);
  const rowId = (i) => `${listId}-r${i}`;

  return (
    <Modal title="Pick a library record" onClose={onClose} trapFocus className="lib-pick" overlayClassName="lib-pick-overlay"
           footer={<button type="button" className="secondary" onClick={onClose}>Cancel</button>}>
      <div className="lib-pick-body" onKeyDown={onKeyDown}>
        <div className="lib-pick-filters">
          <TextInput type="search" role="combobox" aria-expanded="true" aria-controls={listId} aria-autocomplete="list"
                     aria-activedescendant={rows[hi] ? rowId(hi) : undefined} autoFocus value={q} onChange={(e) => setQ(e.target.value)}
                     placeholder="Name, equipment, failure mode" aria-label="Search the data library" className="lib-pick-q" />
          <Select aria-label="Library" value={source ?? ""} onChange={(e) => changeLibrary(e.target.value)} disabled={sources === null}>
            {libraryOptions(sources).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            <option value="">Every library</option>
          </Select>
          <Select aria-label="Equipment type" value={equipment} onChange={(e) => setEquipment(e.target.value)}>
            <option value="">Every equipment type</option>
            {facetOptions(facets.equipment_type, equipment, labels).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </Select>
          <Select aria-label="Failure mode" value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="">Every failure mode</option>
            {facetOptions(facets.failure_mode, mode).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </Select>
          {showsKind(facets.kind, kind) && (
            <Select aria-label="Kind" value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="">Every kind</option>
              {facetOptions(facets.kind, kind, KIND_LABEL).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </Select>
          )}
        </div>
        <p className="lib-pick-status" role="status">
          {found === null ? "Searching…" : found.failed ? `The library didn't answer: ${found.failed}`
            : found.total > rows.length ? `The first ${rows.length} of ${found.total} records: search or filter to narrow them.`
              : `${found.total} ${found.total === 1 ? "record" : "records"}.`}
          {hidden ? ` ${hidden}` : ""}
          {rows.length > 0 && <span className="lib-pick-keys"> Arrow keys move, Enter picks.</span>}
        </p>
        <div className="lib-pick-list" ref={listRef}>
          {found && !found.failed && rows.length === 0 ? (
            <div className="lib-pick-empty">
              <p>No records match.</p>
              {filtered && <button type="button" className="secondary sm" onClick={clear}>Clear the filters</button>}
            </div>
          ) : (
            <>
              <div className="lib-pick-row lib-pick-head" aria-hidden="true">
                <span>Record</span><span>Equipment</span><span>Failure mode</span><span>Kind</span>
                <span className="num">Mean</span><span className="num">5–95%</span><span>Source</span><span />
              </div>
              <div id={listId} role="listbox" aria-label="Library records">
                {rows.map((r, i) => (
                  <div key={r.id} id={rowId(i)} data-index={i} role="option" aria-selected={i === hi}
                       className={"lib-pick-row" + (i === hi ? " hi" : "") + (r.id === selectedId ? " chosen" : "")}
                       onClick={() => pick(r)} onMouseMove={() => i !== hi && setHi(i)}>
                    <span className="lib-pick-name">{r.label}{r.id === selectedId ? <span className="lib-pick-now"> (chosen)</span> : null}</span>
                    <span className="lib-pick-detail">{rowDetail(r, labels)}</span>
                    <span className="lib-pick-col">{labels[r.equipment_type] || r.equipment_type}</span>
                    <span className="lib-pick-col">{r.failure_mode}</span>
                    <span className="lib-pick-col">{KIND_LABEL[r.kind] || r.kind}</span>
                    <span className="lib-pick-col num">{r.mean == null ? "—" : `${sig(r.mean)} ${r.units || ""}`.trim()}</span>
                    <span className="lib-pick-col num">{rangeText(r)}</span>
                    <span className="lib-pick-col">{r.source}</span>
                    <span className="lib-pick-link">
                      <Link to={recordPath(r.id)} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}
                            aria-label={`Details of ${r.label} (opens in a new tab)`}>Details</Link>
                    </span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </Modal>
  );
}

// What a dialog shows in place of a list once a record is picked: one line, "<name> · <value with
// unit> · <short source>", with Change… (the picker again) and Details (the record's page, in a new
// tab); before a pick, one Pick a library record… button. ``record``: a search row, or {id} while
// it's being read. When the pick replaces the button that opened the picker, focus goes to Change….
export function PickedRecord({ record, onPick }) {
  const change = useRef(null);
  const id = record?.id || null;
  useEffect(() => {
    const at = document.activeElement;
    if (id && change.current && (!at || at === document.body)) change.current.focus({ preventScroll: true });
  }, [id]);
  if (!record) {
    return <button type="button" className="secondary lib-picked-pick" onClick={onPick}>Pick a library record…</button>;
  }
  return (
    <div className="lib-picked" role="group" aria-label="The library record">
      <p className="lib-picked-line">
        {record.label ? <><strong>{record.label}</strong>{[valueText(record), record.source].filter(Boolean).map((x) => ` · ${x}`).join("")}</>
          : "Reading the record…"}
      </p>
      <span className="lib-picked-acts">
        <button ref={change} type="button" className="secondary sm" onClick={onPick} aria-label="Change the library record">Change…</button>
        <Link to={recordPath(record.id)} target="_blank" rel="noreferrer" aria-label="Details of the library record (opens in a new tab)">Details</Link>
      </span>
    </div>
  );
}

// The pieces of a product's page (MaintenanceProducts.jsx) that the Explorer
// uses too: the design's failure reports rolled up across the items built from
// it, the Build an item dialog, and the New product dialog.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { buildProductItem, createProduct, getDesignRollup } from "../api.js";
import { Field, FormModal, fmtDate } from "./MaintenanceParts.jsx";
import { consequenceShort, isOpen, statusLabel } from "../failureReports.js";
import { buildProblem, itemPagePath, itemTreePath, revText } from "../products.js";

// Where one report is: its item's tree, on the Failure reports tab, opened on it.
export function reportPath(r) {
  const top = r.unit?.top_position_id;
  if (!top) return null;
  const q = new URLSearchParams({ arrange: "positions", root: top, tab: "reports", sel: r.position?.id || top, report: r.id });
  return `/asset-register/explorer?${q}`;
}

// A design position's (or the whole product's) failure reports across every item
// built from it: which item, which design node, the status. Read-only: a report
// is filed on an item, so this says how and links to them.
export function DesignReports({ positionId, heading = false }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let live = true;
    setData(null);
    setError(null);
    getDesignRollup(positionId).then((d) => live && setData(d)).catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [positionId]);
  if (error) return <p className="lib-date">Couldn't load the failure reports: {error}</p>;
  if (!data) return <p className="lib-date">Loading…</p>;
  const reports = data.reports || [];
  const items = data.items || [];
  return (
    <div className="fr-panel pp-rollup">
      {heading && <h2>Failure reports across the items</h2>}
      <p className="fr-counts">
        {data.reports_total === 0 ? "No failure reports on the items built from this product here yet."
          : `${data.reports_total} ${data.reports_total === 1 ? "report" : "reports"} across the items, ${data.open_reports} open.`}
      </p>
      <p className="lib-date">
        A report is about an item: pick one of the items built from this product to add one.
        {items.length > 0 && <>{" "}{items.map((it, i) => (
          <span key={it.top_position_id}>{i > 0 && " · "}
            <Link to={itemTreePath(it.top_position_id, it.position?.id)}>{it.serial || "(no serial)"}</Link>
          </span>
        ))}</>}
      </p>
      {reports.length > 0 && (
        <div className="maint-scroll">
          <table className="lib-table pp-table">
            <thead><tr><th>Report</th><th>Item</th><th>Where in the design</th><th>Status</th><th>Occurred</th></tr></thead>
            <tbody>
              {reports.map((r) => {
                const to = reportPath(r);
                return (
                  <tr key={r.id}>
                    <td>{to ? <Link to={to} state={{ treeDetail: r.position?.id || r.unit?.top_position_id }}>{r.label}</Link> : r.label}
                      <div className="lib-date">{[r.title, r.consequence && consequenceShort(r.consequence)].filter(Boolean).join(" · ")}</div></td>
                    <td data-label="Item">{r.unit?.item_id ? <Link to={itemPagePath(r.unit.item_id)}>{r.unit.serial || "(no serial)"}</Link> : (r.unit?.serial || "—")}</td>
                    <td data-label="Where in the design">{[...(r.level || [])].join(" › ") || data.design_position?.name}</td>
                    <td data-label="Status"><span className={isOpen(r.status) ? "maint-badge" : "lib-date"}>{statusLabel(r.status)}</span></td>
                    <td data-label="Occurred" className="lib-date">{fmtDate(r.occurred_on)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// New product: its name, part number (a new part in the catalogue) and revision,
// made together; then the page opens on it to add its functional structure.
export function NewProductModal({ onClose, onDone }) {
  const [name, setName] = useState("");
  const [number, setNumber] = useState("");
  const [rev, setRev] = useState("A");
  return (
    <FormModal title="New product" submitLabel="Create" canSubmit={!!name.trim()} onClose={onClose}
               onSubmit={async () => onDone(await createProduct({ name: name.trim(), part_number: number.trim(), rev: rev.trim() }))}>
      <Field label="Name" text={name}><input value={name} onChange={(e) => setName(e.target.value)} autoFocus /></Field>
      <Field label="Part number (optional)" hint="A new part in the catalogue: its bill of materials is the product's parts list.">
        <input value={number} onChange={(e) => setNumber(e.target.value)} placeholder="e.g. PS-200" />
      </Field>
      <Field label="Revision"><input value={rev} onChange={(e) => setRev(e.target.value)} placeholder="e.g. A" /></Field>
      <p className="lib-date">Then add its functional structure (what each part of it does) on its page, and build items from it.</p>
    </FormModal>
  );
}

// Build an item from a product: its serial and revision, then a dry run that
// lists the positions it will make, then Build. A serial already used is
// refused in the server's words.
export function BuildItemModal({ product, onClose, onDone }) {
  const [serial, setSerial] = useState("");
  const [rev, setRev] = useState(product.rev || "");
  const [preview, setPreview] = useState(null);
  const change = (set) => (e) => { set(e.target.value); setPreview(null); };
  const problem = buildProblem(serial);
  const submit = async () => {
    const body = { serial: serial.trim(), rev: rev.trim() };
    if (!preview) {
      setPreview(await buildProductItem(product.id, { ...body, dry_run: true }));
      return;
    }
    onDone(await buildProductItem(product.id, { ...body, dry_run: false }));
  };
  const c = preview?.counts;
  return (
    <FormModal title={`Build an item: ${product.name}`} submitLabel={preview ? "Build item" : "Check"}
               pendingLabel={preview ? "Building…" : "Checking…"} canSubmit={!problem} onClose={onClose} onSubmit={submit}>
      <Field label="Serial number" text={serial}><input value={serial} onChange={change(setSerial)} autoFocus placeholder="e.g. 0010" /></Field>
      <Field label="Revision"><input value={rev} onChange={change(setRev)} /></Field>
      {preview ? (
        <div className="pp-preview" aria-live="polite">
          <p><strong>{preview.name}</strong>{preview.rev ? ` · ${revText(preview.rev)}` : ""}: {c.positions} {c.positions === 1 ? "position" : "positions"},
            {" "}{c.failure_modes} failure {c.failure_modes === 1 ? "mode" : "modes"} and {c.tasks} {c.tasks === 1 ? "task" : "tasks"} copied from the design,
            and the item (serial {preview.serial}{preview.item?.part ? `, part ${preview.item.part.part_number}` : ""}) fitted at the top.</p>
          <ul className="pp-paths">
            {preview.positions.map((p) => <li key={p.design_position_id}>{p.path}</li>)}
          </ul>
          {c.positions > preview.positions.length && <p className="lib-date">and {c.positions - preview.positions.length} more.</p>}
        </div>
      ) : (
        <p className="lib-date">Check first: it lists the positions it will make. Nothing is built until you press Build item.</p>
      )}
    </FormModal>
  );
}

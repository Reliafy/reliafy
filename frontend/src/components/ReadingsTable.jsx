import { Fragment, useState } from "react";
import { correctMeasurementReading, voidMeasurementReading } from "../api.js";
import { Field, today } from "./MaintenanceParts.jsx";
import Chip from "./ui/Chip.jsx";
import RowMenu from "./RowMenu.jsx";
import { readingClock } from "../maintenanceReadings.js";
import { workspaceMoment, workspaceZoneName } from "../workspaceDate.js";
import { canEditReadings, readingMenu, readingRows, valueHeading } from "../measuringPoint.js";
import "./ReadingsTable.css";

// A measuring point's readings, newest first (the point's page and the
// Explorer's Readings dialog share it): the date on one line, the value (its
// unit in the column heading), the note in a column of its own that takes the
// room, and a ⋯ menu per reading with Correct… and Void. A voided or
// corrected reading stays listed, struck out, with a chip saying so and what
// happened under its note. Correcting or voiding opens a small form under the
// row, which needs a reason; `onChanged(point)` gets the point back from the
// server. A feed's readings have no menu (the feed sends them). Where the
// table is narrow (a phone) each reading becomes a block: date, value and ⋯
// on top, the note under them.

const MoreIcon = () => (
  <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true">
    <circle cx="5" cy="12" r="1.8" /><circle cx="12" cy="12" r="1.8" /><circle cx="19" cy="12" r="1.8" />
  </svg>
);

export default function ReadingsTable({ point, onChanged, idPrefix = "rd" }) {
  const [menu, setMenu] = useState(null); // {row, at}
  const [edit, setEdit] = useState(null); // {id, mode: "void" | "correct", value, on, time, reason}
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const rows = readingRows(point);
  const editable = canEditReadings(point) && !point.retired;
  const unit = point.unit || "";
  const rowId = (r) => `${idPrefix}-${r.id}`;

  const start = (row, mode) => {
    const r = row.reading;
    setError(null);
    setEdit({ id: row.id, mode, value: String(r.value), on: r.on || (r.at || "").slice(0, 10), time: readingClock(r), reason: "" });
  };
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const next = edit.mode === "void"
        ? await voidMeasurementReading(edit.id, edit.reason)
        : await correctMeasurementReading(edit.id, {
          value: Number(edit.value), on: edit.on, at: edit.time ? workspaceMoment(edit.on, edit.time) : undefined, reason: edit.reason,
        });
      setEdit(null);
      onChanged?.(next);
    } catch (e) {
      setError(e.message);
    }
    setBusy(false);
  };
  const set = (k) => (e) => setEdit({ ...edit, [k]: e.target.value });
  const openMenu = (e, row) => {
    e.stopPropagation();
    const b = e.currentTarget.getBoundingClientRect();
    setMenu({ row, at: { x: b.right, y: b.bottom + 2 } });
  };

  if (!rows.length) return null;
  return (
    <div className="rt-list">
      <table className={"lib-table rt-table" + (editable ? "" : " rt-no-menu")}>
        <colgroup>
          <col className="rt-c-date" /><col className="rt-c-value" /><col />{editable && <col className="rt-c-menu" />}
        </colgroup>
        <thead>
          <tr>
            <th>Date</th><th className="rt-num">{valueHeading(point)}</th><th>Note</th>
            {editable && <th><span className="sr-only">Actions</span></th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <Fragment key={row.id}>
              <tr id={rowId(row)} className={"rt-row" + (row.struck ? " rt-struck" : "") + (edit?.id === row.id || menu?.row.id === row.id ? " rt-picked" : "")}>
                <td className="rt-date">{row.date}</td>
                <td className="rt-value">
                  <span className="rt-value-text">{row.value}</span>
                  {/* The unit is in the heading; a phone hides the heading, so it shows here instead. */}
                  {unit && <span className="rt-unit"> {unit}</span>}
                </td>
                <td className="rt-note">
                  {row.chip && <Chip tone={row.chip.tone} className="rt-chip">{row.chip.label}</Chip>}
                  {row.note && <span className="rt-note-text">{row.note}</span>}
                  {row.detail && <span className="lib-date rt-detail">{row.detail}</span>}
                  {!row.note && !row.detail && !row.chip && <span className="lib-date rt-none" aria-label="No note">—</span>}
                </td>
                {editable && (
                  <td className="rt-menu-cell">
                    <button type="button" className={"rt-more" + (menu?.row.id === row.id ? " open" : "")} aria-haspopup="menu"
                            aria-expanded={menu?.row.id === row.id} aria-label={`Actions for the reading on ${row.date}`} title="Actions"
                            onClick={(e) => openMenu(e, row)}>
                      <MoreIcon />
                    </button>
                  </td>
                )}
              </tr>
              {edit?.id === row.id && (
                <tr className="rt-edit-row">
                  <td colSpan={editable ? 4 : 3}>
                    <div className="maint-action rt-edit">
                      <p className="rt-edit-title">
                        {edit.mode === "void" ? `Void the reading on ${row.date}` : `Correct the reading on ${row.date}`}
                      </p>
                      {error && <div className="card error">{error}</div>}
                      <div className="rcm-form">
                        {edit.mode === "correct" && <>
                          <Field label={`Right value${unit ? ` (${unit})` : ""}`}>
                            <input type="number" inputMode="decimal" step="any" value={edit.value} onChange={set("value")} />
                          </Field>
                          <Field label="Really read on"><input type="date" value={edit.on} max={today()} onChange={set("on")} /></Field>
                          <Field label={`At, ${workspaceZoneName()} time (optional)`}><input type="time" value={edit.time} onChange={set("time")} /></Field>
                        </>}
                        <Field label={edit.mode === "void" ? "Why it's voided" : "Why it's corrected"}>
                          <input autoFocus value={edit.reason} placeholder={edit.mode === "void" ? "e.g. entered twice" : "e.g. an old reading entered as today"}
                                 onChange={set("reason")} />
                        </Field>
                      </div>
                      <p className="lib-date rt-edit-hint">
                        {edit.mode === "void"
                          ? "It stays listed, struck out, and is left out of rates, due dates and alarms."
                          : "The original stays listed, struck out, beside the corrected one."}
                      </p>
                      <div className="maint-row">
                        <button onClick={save} disabled={busy || !edit.reason.trim() || (edit.mode === "correct" && edit.value === "")}>
                          {busy ? "Saving…" : edit.mode === "void" ? "Void the reading" : "Save the correction"}
                        </button>
                        <button className="secondary" onClick={() => { setEdit(null); setError(null); }} disabled={busy}>Cancel</button>
                      </div>
                    </div>
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
      {menu && (
        <RowMenu items={readingMenu(menu.row.reading)} at={menu.at} label={`Actions for the reading on ${menu.row.date}`}
                 anchorId={rowId(menu.row)}
                 onChoose={(id) => start(menu.row, id)}
                 onClose={() => {
                   const id = rowId(menu.row);
                   setMenu(null);
                   document.getElementById(id)?.querySelector(".rt-more")?.focus({ preventScroll: true });
                 }} />
      )}
    </div>
  );
}

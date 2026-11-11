// Pieces Maintenance's pages share: the time-zone line, what a row is on, and
// the New position and Import from a spreadsheet forms. (Maintenance's own page
// is now its sub-pages: Orders, MaintenanceOrders.jsx, and Packages.)
import { useState } from "react";
import { Link } from "react-router-dom";
import { createMaintenancePosition, importMaintenanceSheet, setTeamTimeZone } from "../api.js";
import { Field, FormModal, PositionPicker } from "../components/MaintenanceParts.jsx";
import { useWorkspace } from "../WorkspaceProvider.jsx";
import { browserTimeZone, shouldSuggestTimeZone } from "../workspaceDate.js";
import { itemAtText, subjectBadge, subjectPath } from "../maintenanceSubjects.js";
import "./Maintenance.css";
import { DESCRIPTION_HINT, tooLong } from "../maintenanceText.js";

// One quiet line when the workspace has no time zone and this device isn't on
// UTC: the dates here follow UTC until it's set. One button sets this device's
// zone (the same call as Settings, or Team settings for a team's owner).
export function TimeZoneNudge({ zone, onSet }) {
  const { workspace, activeTeam, savePersonalTimeZone, refreshTeams } = useWorkspace();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(null);
  const browser = browserTimeZone();
  if (!shouldSuggestTimeZone(zone, browser)) return null;
  const team = workspace !== "personal";
  if (team && activeTeam?.role !== "owner") return null;
  const place = browser.replaceAll("_", " ");
  const use = async () => {
    setBusy(true);
    setFailed(null);
    try {
      if (team) {
        await setTeamTimeZone(activeTeam.id, browser);
        refreshTeams();
      } else {
        await savePersonalTimeZone(browser);
      }
      onSet?.();
    } catch (e) {
      setFailed(e.message);
      setBusy(false);
    }
  };
  return (
    <div className="muted-line maint-tz">
      <span>Dates here follow UTC: today ends at midnight UTC, not where you are.</span>{" "}
      <button type="button" className="secondary sm" onClick={use} disabled={busy}>
        {busy ? "Saving…" : `Use ${place}`}
      </button>{" "}
      <Link to={team ? "/team" : "/settings"}>Choose another time zone</Link>
      {failed && <span className="field-error" role="alert"> {failed}</span>}
    </div>
  );
}

// What a due task or open work order is on: its position, or an item (and where
// it is now) or a location, marked.
export function SubjectCell({ subject, at, link = true }) {
  if (!subject) return null;
  const name = link ? <Link to={subjectPath(subject)}>{subject.name}</Link> : subject.name;
  const badge = subjectBadge(subject);
  return (
    <>
      {name}{badge && <> <span className="maint-badge">{badge}</span></>}
      {at && <div className="lib-date">{itemAtText(at)}</div>}
    </>
  );
}

export function NewPositionModal({ positions, parentId = null, onClose, onCreated }) {
  const [name, setName] = useState("");
  const [tag, setTag] = useState("");
  const [positionClass, setPositionClass] = useState("");
  const [parent, setParent] = useState(parentId);
  return (
    <FormModal
      title="New position"
      submitLabel="Create position"
      pendingLabel="Adding…"
      canSubmit={!!name.trim() && !tooLong(name)}
      onClose={onClose}
      onSubmit={async () => onCreated(await createMaintenancePosition({
        name, tag, position_class: positionClass, parent_id: parent,
      }))}
    >
      <Field label="Name" text={name} hint={DESCRIPTION_HINT}>
        <input autoFocus value={name} placeholder="e.g. Hot water system" onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label="Inside">
        <PositionPicker positions={positions} value={parent} onChange={setParent} />
      </Field>
      <Field label="Tag (optional)">
        <input value={tag} placeholder="e.g. =HOUSE.HWS" onChange={(e) => setTag(e.target.value)} />
      </Field>
      <Field label="Class (optional, to compare like positions)">
        <input value={positionClass} placeholder="e.g. Electric storage water heater" onChange={(e) => setPositionClass(e.target.value)} />
      </Field>
    </FormModal>
  );
}

export function ImportModal({ onClose, onDone }) {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const check = async () => setPreview(await importMaintenanceSheet(file, true));
  return (
    <FormModal title="Import from a spreadsheet" submitLabel={preview ? "Import" : "Check it"} canSubmit={!!file}
               onClose={onClose} onSubmit={async () => (preview ? onDone(await importMaintenanceSheet(file, false)) : check())}>
      <p className="lib-date">
        A CSV or Excel sheet, one row per item per position. Columns: position (a path like House &gt; Pool &gt; Pump),
        and optionally class, item, serial, manufacturer, model, fitted, removed, failed (yes/no) and failure mode.
        Every row is checked first; if any is wrong, nothing is imported.
      </p>
      <Field label="File"><input type="file" accept=".csv,.xlsx,.xlsm" onChange={(e) => { setFile(e.target.files[0] || null); setPreview(null); }} /></Field>
      {preview && (
        <p>It will make {preview.positions_created} position{preview.positions_created === 1 ? "" : "s"},{" "}
          {preview.items_created} item{preview.items_created === 1 ? "" : "s"} and {preview.fitments} fitments,
          {" "}{preview.failures} of them ending in a failure.</p>
      )}
    </FormModal>
  );
}

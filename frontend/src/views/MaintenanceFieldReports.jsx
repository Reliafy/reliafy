import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  deleteFieldReport, getFieldReport, getFieldReportMediaBlob, keepFieldReport, listFieldReports, setFieldReportStatus,
} from "../api.js";
import { SectionHeader } from "../components/SectionPage.jsx";
import ListSearch from "../components/ListSearch.jsx";
import Select from "../components/Select.jsx";
import { useConfirm } from "../components/ConfirmProvider.jsx";
import { today } from "../components/MaintenanceParts.jsx";
import {
  STATUS_CHIP, STATUS_LABEL, arrivingText, clockLength, contentsText, keepText, matches, takenText,
} from "../fieldReports.js";
import { workOrderPath } from "../maintenanceOrders.js";
import "./Maintenance.css";

const STATUSES = [
  { value: "", label: "All" },
  { value: "new", label: "New" },
  { value: "parsed", label: "Read" },
  { value: "done", label: "Done" },
];
const KIND = { Position: "Position", Location: "Location", Item: "Item", WorkOrder: "Work order" };

// Maintenance › Field reports: what people in the field recorded (notes, photos,
// sound), newest first. A report changes nothing by itself: read it, make the
// changes with the ordinary pages, then mark it read and done.
export default function MaintenanceFieldReports() {
  const [status, setStatus] = useState("");
  const [query, setQuery] = useState("");
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [openId, setOpenId] = useState(null);
  const load = useCallback(() => listFieldReports(status ? { status } : {}).then(setData).catch((e) => setError(e.message)), [status]);
  useEffect(() => {
    setData(null);
    load();
  }, [load]);
  const rows = data?.reports;
  const shown = (rows || []).filter((r) => matches(r, query));
  const day = today();
  const opened = shown.find((r) => r.id === openId) || null;
  return (
    <div className="app">
      <SectionHeader
        section="maintenance"
        title="Field reports"
        purpose="What people saw in the field: notes, photos and sound, as they recorded them."
      />
      {error && <div className="card error">{error}</div>}
      {data && (
        <p className="maint-answer">
          {data.total === 0 ? "No field reports here."
            : `${data.counts.new} new, ${data.counts.parsed} read, ${data.counts.done} done.`}
          {" "}A report's content is deleted {data.keep_days} days after it was made, or {data.keep_days_done} days
          after it is marked done, unless you keep it.
        </p>
      )}
      <section className="card">
        <div className="tablebar section-tablebar maint-filters">
          <span className="count">
            {rows == null ? "Loading…" : shown.length === rows.length
              ? `${rows.length} ${rows.length === 1 ? "report" : "reports"}` : `${shown.length} of ${rows.length} reports`}
          </span>
          <span className="grow" />
          <Select className="section-type-filter" ariaLabel="Status" value={status} onChange={setStatus} options={STATUSES} />
          <ListSearch value={query} onChange={setQuery} placeholder="Search reports…" />
        </div>
        {rows == null ? null : rows.length === 0 ? (
          <div className="empty">
            <p className="lib-date">
              {status ? "No reports with that status." : "No field reports yet. They arrive from the field app, or from the API "
                + "(reliafy capture new)."}
            </p>
          </div>
        ) : shown.length === 0 ? (
          <p className="lib-date">No report matches.</p>
        ) : (
          <div className="maint-scroll"><table className="lib-table">
            <thead><tr><th>Report</th><th>Made</th><th>By</th><th>About</th><th>Holds</th><th>Status</th></tr></thead>
            <tbody>
              {shown.map((r) => (
                <ReportRows key={r.id} report={r} day={day} open={openId === r.id}
                  onToggle={() => setOpenId(openId === r.id ? null : r.id)} />
              ))}
            </tbody>
          </table></div>
        )}
        {/* The open report sits under the table, not inside it, so it wraps on a phone. */}
        {opened && (
          <div className="field-report-panel">
            <h3>{opened.title}</h3>
            <ReportDetail key={opened.id} id={opened.id} day={day} onChanged={load} />
          </div>
        )}
      </section>
    </div>
  );
}

function ReportRows({ report, day, open, onToggle }) {
  const holds = contentsText(report);
  return (
    <>
      <tr className={`lib-row${open ? " field-report-open" : ""}`} onClick={onToggle}>
        <td className="field-report-name">
          <button type="button" className="link" aria-expanded={open} onClick={(e) => { e.stopPropagation(); onToggle(); }}>
            {report.title}
          </button>
          <div className="lib-date">{report.notes_preview || "No notes"}</div>
        </td>
        <td className="maint-nowrap lib-date">{takenText(report.taken_at)}</td>
        <td className="lib-date">{report.by_name || "—"}</td>
        <td className="lib-date">{report.about.map((a) => a.name || KIND[a.kind]).join(", ") || "—"}</td>
        <td className="lib-date">{holds || "Notes only"}{!report.complete && <> <span className="chip chip-warning">arriving</span></>}</td>
        <td className="maint-nowrap">
          <span className={`chip ${STATUS_CHIP[report.status]}`}>{STATUS_LABEL[report.status]}</span>
          <div className="lib-date">{keepText(report, day)}</div>
        </td>
      </tr>
    </>
  );
}

function ReportDetail({ id, day, onChanged }) {
  const confirm = useConfirm();
  const [report, setReport] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let live = true;
    getFieldReport(id).then((r) => live && setReport(r)).catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [id]);

  const act = async (work) => {
    setBusy(true);
    setError(null);
    try {
      const next = await work();
      if (next && next.id) setReport(next);
      await onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    const ok = await confirm({
      title: "Delete this report's content?",
      body: "Its notes, photos, sound and files are deleted for good. A photo you have linked to a position, item, "
        + "location or work order stays there. The record that the report existed stays.",
      confirmLabel: "Delete content",
    });
    if (ok) await act(async () => { await deleteFieldReport(id); return getFieldReport(id); });
  };

  if (error && !report) return <div className="card error">{error}</div>;
  if (!report) return <p className="lib-date">Loading…</p>;
  const photos = report.media.filter((m) => m.kind === "photo");
  const sounds = report.media.filter((m) => m.kind === "audio");
  const files = report.media.filter((m) => m.kind === "file");
  const arriving = arrivingText(report);
  return (
    <div className="field-report">
      {error && <div className="card error">{error}</div>}
      {report.expired ? (
        <p className="lib-date">This report's content was deleted on {report.expired_on}. Only the record that it existed is kept.</p>
      ) : (
        <>
          {report.clock_suspect && (
            <p className="lib-date">The phone's clock was ahead of the server's when this arrived, so the time it shows may be wrong.</p>
          )}
          {arriving && <p className="lib-date">{arriving}</p>}
          <p className="field-report-notes">{report.notes || <span className="lib-date">No notes.</span>}</p>
          {report.about.length > 0 && (
            <p className="lib-date">
              About:{" "}
              {report.about.map((a, i) => (
                <span key={a.id}>
                  {i > 0 && ", "}
                  {a.kind === "WorkOrder"
                    ? <Link to={workOrderPath(a.id)}>{a.number != null ? `#${a.number} ` : ""}{a.name}</Link>
                    : <>{a.name} ({KIND[a.kind].toLowerCase()})</>}
                </span>
              ))}
            </p>
          )}
          {report.about_missing > 0 && (
            <p className="lib-date">It also pointed at {report.about_missing} thing{report.about_missing === 1 ? "" : "s"} that
              {report.about_missing === 1 ? " is" : " are"} no longer in the workspace.</p>
          )}
          {report.location && (
            <p className="lib-date">
              Location (added by its author): {report.location.lat}, {report.location.lon}
              {report.location.accuracy_m != null && ` (within ${Math.round(report.location.accuracy_m)} m)`}
            </p>
          )}
          {photos.length > 0 && (
            <div className="maint-photos">
              {photos.map((m) => (
                <figure key={m.id}>
                  <Media reportId={id} media={m} size="full" />
                  {(m.caption || m.also_on?.length > 0) && (
                    <figcaption className="lib-date">
                      {m.caption}{m.also_on?.length > 0 && ` Also on ${m.also_on.map((t) => t.name).join(", ")}.`}
                    </figcaption>
                  )}
                </figure>
              ))}
            </div>
          )}
          {sounds.map((m, i) => (
            <div key={m.id} className="field-report-sound">
              <span className="lib-date">Recording {i + 1}{m.duration_s ? ` (${clockLength(m.duration_s)})` : ""}</span>
              <Media reportId={id} media={m} />
            </div>
          ))}
          {files.map((m) => (
            <div key={m.id} className="field-report-sound">
              <span className="lib-date">{m.name}</span>
              <Media reportId={id} media={m} />
            </div>
          ))}
        </>
      )}
      <div className="field-report-actions">
        {report.status_note && <span className="lib-date">Note: {report.status_note}</span>}
        <span className="lib-date">{keepText(report, day)}</span>
        <span className="grow" />
        {report.status !== "new" && <button className="secondary" disabled={busy} onClick={() => act(() => setFieldReportStatus(id, "new"))}>Mark new</button>}
        {report.status === "new" && <button className="secondary" disabled={busy} onClick={() => act(() => setFieldReportStatus(id, "parsed"))}>Mark read</button>}
        {report.status !== "done" && <button disabled={busy} onClick={() => act(() => setFieldReportStatus(id, "done"))}>Mark done</button>}
        {!report.expired && (
          <button className="secondary" disabled={busy} onClick={() => act(() => keepFieldReport(id, !report.keep))}>
            {report.keep ? "Stop keeping" : "Keep"}
          </button>
        )}
        {!report.expired && <button className="secondary danger" disabled={busy} onClick={remove}>Delete content</button>}
      </div>
    </div>
  );
}

// One attachment from the signed-in endpoint, through an object URL: a photo
// shown, a recording with the browser's player, a file as a link that opens it.
function Media({ reportId, media, size = "full" }) {
  const [src, setSrc] = useState(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let url = null;
    let alive = true;
    getFieldReportMediaBlob(reportId, media.id, size)
      .then((blob) => {
        url = URL.createObjectURL(blob);
        if (alive) setSrc(url);
      })
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [reportId, media.id, size]);
  if (failed) return <span className="lib-date">Could not be loaded.</span>;
  if (media.kind === "photo") {
    return src ? <a href={src} target="_blank" rel="noreferrer"><img src={src} alt={media.caption || "Photo from the report"} className="maint-photo" /></a>
      : <div className="maint-photo maint-photo-blank" />;
  }
  if (!src) return <span className="lib-date">Loading…</span>;
  if (media.kind === "audio") return <audio controls preload="metadata" src={src} aria-label="Recording from the report" />;
  return <a href={src} target="_blank" rel="noreferrer">Open {media.name}</a>;
}

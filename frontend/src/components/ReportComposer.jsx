import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import Modal from "./Modal.jsx";
import { PublicLinks } from "./ShareDialog.jsx";
import { useAppConfig } from "../ConfigProvider.jsx";
import {
  createReport, deleteReport, draftReportNotes, listReportItems, listReports, updateReport,
} from "../api.js";
import {
  MAX_SECTIONS, addSection, applyDraft, moveSection, pickerGroups, removeSection, reportBody, setNote,
} from "../reportComposer.js";
import "./ReportComposer.css";

// The report composer (#30), opened from an item's Share dialog ("Add to a
// report…"): pick saved items, give the report a title, an author line and
// notes, save it, then publish it with a public link like any other share.
// "Draft notes" (#41) asks the assistant to word the items' saved figures;
// the draft only fills the boxes, for the owner to edit. Saving publishes
// nothing: the link is a separate step below the form.

const ArrowIcon = ({ up }) => (
  <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.6"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {up ? <path d="M8 13V3M4 7l4-4 4 4" /> : <path d="M8 3v10M4 9l4 4 4-4" />}
  </svg>
);
const CloseIcon = () => (
  <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.6"
    strokeLinecap="round" aria-hidden="true">
    <path d="M4 4l8 8M12 4l-8 8" />
  </svg>
);

const EMPTY = { title: "", author: "", introduction: "", sections: [] };

function fromReport(r) {
  return {
    title: r.title || "",
    author: r.author || "",
    introduction: r.introduction || "",
    sections: (r.sections || []).map((s) => ({ ...s, name: s.name || "Unavailable item" })),
  };
}

// `initial`: the item it was opened from (none from Reports); `openId`: a
// report of the user's to open (Reports' Edit).
export default function ReportComposer({ initial = null, openId = "", onClose }) {
  const { ai } = useAppConfig();
  const [reports, setReports] = useState(null);
  const [items, setItems] = useState(null);
  const [reportId, setReportId] = useState(""); // "" = a new report
  const [form, setForm] = useState(() => ({ ...EMPTY, sections: addSection([], initial) }));
  const [dirty, setDirty] = useState(true);
  const [busy, setBusy] = useState(null); // "save" | "draft" | "delete"
  const [error, setError] = useState(null);
  const [draft, setDraft] = useState(null); // { unverified, undo: form }
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    listReports().then((d) => setReports(d.reports || [])).catch(() => setReports([]));
    listReportItems().then((d) => setItems(d.items || [])).catch((e) => setError(e.message));
  }, []);

  const change = (patch) => {
    setForm((f) => ({ ...f, ...patch }));
    setDirty(true);
  };
  const setSections = (fn) => {
    setForm((f) => ({ ...f, sections: fn(f.sections) }));
    setDirty(true);
  };

  // Switch between a new report and one of the user's reports; the item the
  // composer was opened from joins whichever is chosen.
  const choose = (id) => {
    setReportId(id);
    setDraft(null);
    setError(null);
    const base = id ? fromReport(reports.find((r) => r.id === id)) : EMPTY;
    const sections = addSection(base.sections, initial);
    setForm({ ...base, sections });
    setDirty(!id || sections.length !== base.sections.length);
  };

  // Opened on one of the user's reports: choose it once the list is in.
  useEffect(() => {
    if (openId && reports?.some((r) => r.id === openId)) choose(openId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openId, reports === null]);

  const groups = useMemo(() => pickerGroups(items, form.sections), [items, form.sections]);
  const byKey = useMemo(
    () => new Map((items || []).map((it) => [`${it.collection}:${it.artifact_id}`, it])),
    [items]
  );
  const full = form.sections.length >= MAX_SECTIONS;

  const onSave = async () => {
    setBusy("save");
    setError(null);
    try {
      const body = reportBody(form);
      const saved = reportId ? await updateReport(reportId, body) : await createReport(body);
      setReportId(saved.id);
      setReports((rs) => [saved, ...(rs || []).filter((r) => r.id !== saved.id)]);
      setDirty(false);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  const onDraft = async () => {
    setBusy("draft");
    setError(null);
    try {
      const out = await draftReportNotes(form.title, reportBody(form).sections);
      const next = applyDraft(form.introduction, form.sections, out);
      setDraft({ unverified: out.unverified || [], undo: form });
      change(next);
    } catch (e) {
      setError(e.code === "no_credits" || e.status === 402 ? { credits: e.message } : e.message);
    } finally {
      setBusy(null);
    }
  };

  const onUndoDraft = () => {
    change(draft.undo);
    setDraft(null);
  };

  const onDelete = async () => {
    setBusy("delete");
    try {
      await deleteReport(reportId);
      onClose();
    } catch (e) {
      setError(e.message);
      setBusy(null);
    }
  };

  const canSave = form.title.trim() && form.sections.length > 0 && dirty && !busy;
  const saved = reportId && !dirty;

  return (
    <Modal
      title="Report"
      className="report-modal"
      locked={!!busy}
      onClose={onClose}
      footer={
        <>
          <div>
            {reportId && !confirmDelete && (
              <button type="button" className="secondary danger sm" onClick={() => setConfirmDelete(true)}
                disabled={!!busy}>
                Delete report
              </button>
            )}
            {confirmDelete && (
              <span className="rc-confirm">
                Delete this report and its links?{" "}
                <button type="button" className="secondary danger sm" onClick={onDelete} disabled={!!busy}>
                  {busy === "delete" ? "Deleting…" : "Delete"}
                </button>{" "}
                <button type="button" className="ghost sm" onClick={() => setConfirmDelete(false)}>Keep</button>
              </span>
            )}
          </div>
          <div className="rc-foot-actions">
            <button type="button" className="secondary" onClick={onClose} disabled={!!busy}>
              {saved ? "Done" : "Cancel"}
            </button>
            <button type="button" onClick={onSave} disabled={!canSave}>
              {busy === "save" ? "Saving…" : reportId ? (dirty ? "Save changes" : "Saved") : "Save report"}
            </button>
          </div>
        </>
      }
    >
      <p className="muted-line rc-lede">
        Put several items on one page with a title and notes, ready to print. Nothing is
        public until you create a link.
      </p>

      {reports?.length > 0 && (
        <label className="login-field">
          <span>Report</span>
          <select value={reportId} onChange={(e) => choose(e.target.value)} disabled={!!busy}>
            <option value="">New report</option>
            {reports.map((r) => <option key={r.id} value={r.id}>{r.title}</option>)}
          </select>
        </label>
      )}

      <div className="rc-row">
        <label className="login-field rc-title">
          <span>Title</span>
          <input type="text" value={form.title} maxLength={160} placeholder="e.g. Pump station review, Q3"
            onChange={(e) => change({ title: e.target.value })} />
        </label>
        <label className="login-field rc-author">
          <span>Author or organisation</span>
          <input type="text" value={form.author} maxLength={160} placeholder="e.g. Jane Doe, Acme Mining"
            onChange={(e) => change({ author: e.target.value })} />
        </label>
      </div>

      <div className="login-field">
        <div className="rc-label-row">
          <span id="rc-intro-label">Introduction</span>
          {ai && (
            <button type="button" className="secondary sm" onClick={onDraft}
              disabled={!!busy || form.sections.length === 0}
              title="The assistant words the items' saved figures. Uses AI credits.">
              {busy === "draft" ? "Drafting…" : "Draft notes"}
            </button>
          )}
        </div>
        <textarea rows={4} value={form.introduction} maxLength={5000} aria-labelledby="rc-intro-label"
          placeholder="What the report covers and what it found (optional)"
          onChange={(e) => change({ introduction: e.target.value })} />
      </div>

      {draft && (
        <div className={"rc-draft" + (draft.unverified.length ? " rc-draft-warn" : "")} role="status">
          {draft.unverified.length > 0 ? (
            <>
              Check {draft.unverified.length === 1 ? "this figure" : "these figures"} before
              publishing — {draft.unverified.length === 1 ? "it isn't" : "they aren't"} in the
              items' saved results: <b>{draft.unverified.join(", ")}</b>.
            </>
          ) : (
            <>Drafted from the items' saved results. Read it through and edit it before publishing.</>
          )}{" "}
          <button type="button" className="link" onClick={onUndoDraft}>Undo draft</button>
        </div>
      )}

      <div className="rc-sections">
        <span className="field-label">Sections</span>
        {form.sections.length === 0 && <p className="muted-line rc-empty">Add an item below.</p>}
        <ol>
          {form.sections.map((s, i) => {
            const known = byKey.get(`${s.collection}:${s.artifact_id}`);
            return (
              <li key={`${s.collection}:${s.artifact_id}`} className="rc-section">
                <div className="rc-section-head">
                  <span className="rc-section-name">
                    {s.name || known?.name}
                    <span className="rc-section-kind">{s.kind || known?.kind}</span>
                  </span>
                  <span className="rc-section-acts">
                    <button type="button" className="ghost sm" aria-label={`Move ${s.name} up`}
                      disabled={i === 0} onClick={() => setSections((x) => moveSection(x, i, -1))}>
                      <ArrowIcon up />
                    </button>
                    <button type="button" className="ghost sm" aria-label={`Move ${s.name} down`}
                      disabled={i === form.sections.length - 1}
                      onClick={() => setSections((x) => moveSection(x, i, 1))}>
                      <ArrowIcon />
                    </button>
                    <button type="button" className="ghost sm" aria-label={`Remove ${s.name}`}
                      onClick={() => setSections((x) => removeSection(x, i))}>
                      <CloseIcon />
                    </button>
                  </span>
                </div>
                <textarea rows={2} value={s.note} maxLength={3000} aria-label={`Note for ${s.name}`}
                  placeholder="Note (optional)"
                  onChange={(e) => setSections((x) => setNote(x, i, e.target.value))} />
              </li>
            );
          })}
        </ol>
        <label className="login-field">
          <span className="sr-only">Add an item</span>
          <select value="" disabled={!items || full}
            onChange={(e) => {
              const it = byKey.get(e.target.value);
              if (it) setSections((x) => addSection(x, it));
            }}>
            <option value="">
              {full ? `A report holds up to ${MAX_SECTIONS} items` : items ? "Add an item…" : "Loading items…"}
            </option>
            {groups.map(([label, list]) => (
              <optgroup key={label} label={label}>
                {list.map((it) => (
                  <option key={`${it.collection}:${it.artifact_id}`} value={`${it.collection}:${it.artifact_id}`}>
                    {it.is_sample ? `${it.name} · ${it.kind}` : it.name}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </label>
      </div>

      {error && (
        <div className="error rc-error" role="alert">
          {error.credits ? (
            <>{error.credits} <Link to="/billing" onClick={onClose}>Top up credits</Link></>
          ) : error}
        </div>
      )}

      {reportId && (
        <div className="rc-publish">
          {dirty && <p className="muted-line rc-hint">Save your changes to update the published page.</p>}
          <PublicLinks collection="reports" artifactId={reportId} onError={setError} openable />
        </div>
      )}
    </Modal>
  );
}

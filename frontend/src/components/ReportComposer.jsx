import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import Chip from "./ui/Chip.jsx";
import { PublicLinks } from "./ShareDialog.jsx";
import { useAskText, useConfirm } from "./ConfirmProvider.jsx";
import { useAppConfig } from "../ConfigProvider.jsx";
import { useWorkspace } from "../WorkspaceProvider.jsx";
import {
  createReport, deleteReport, draftReportNotes, listReportItems, listReports, renameAltModel, renameDataset,
  renameDegradationModel, renameFaultTree, renameFleet, renameModel, renameRbd, renameRecurrentModel,
  renameStrategyAnalysis, updatePrediction, updateReport,
} from "../api.js";
import { changedText, renamePrompt } from "../confirm.js";
import { formatDate, formatDateTime } from "../dates.js";
import { relativeTime } from "../instrument.js";
import {
  MAX_SECTIONS, RENAMABLE, addSection, applyDraft, duplicateNames, isDuplicate, moveSection, pickerKinds,
  pickerRows, removeSection, renameItem, reportBody, setNote,
} from "../reportComposer.js";
import "./ReportComposer.css";

// How each kind of item is renamed (the picker's Rename).
const RENAME = {
  models: renameModel,
  recurrent_models: renameRecurrentModel,
  alt_models: renameAltModel,
  degradation_models: renameDegradationModel,
  rbds: renameRbd,
  fault_trees: renameFaultTree,
  reliability_predictions: (id, name) => updatePrediction(id, { name }),
  strategy_analyses: renameStrategyAnalysis,
  fleets: renameFleet,
  datasets: renameDataset,
};

// When an item was saved: "3 days ago", with the date itself on hover; to
// the minute ("12 Nov 2026, 14:05") when another item has the same name.
function Saved({ iso, exact = false }) {
  if (!iso) return null;
  const d = new Date(iso);
  if (exact) return <span>saved {formatDateTime(d)}</span>;
  return <span title={formatDate(d, { long: true })}>saved {relativeTime(iso)}</span>;
}

// The items to add: a search box and a kind filter over one short list, each
// row with its kind and when it was saved (so two items with one name can be
// told apart), Add, and Rename for the workspace's own items.
function ItemPicker({ items, sections, full, onAdd, onRename, disabled }) {
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("");
  const kinds = useMemo(() => pickerKinds(items), [items]);
  const rows = useMemo(() => pickerRows(items, sections, { query, kind }), [items, sections, query, kind]);
  const dupes = useMemo(() => duplicateNames(items), [items]);
  if (!items) return <p className="muted-line rc-empty">Loading items…</p>;
  if (full) return <p className="muted-line rc-empty">A report holds up to {MAX_SECTIONS} items.</p>;
  return (
    <div className="rc-picker">
      <div className="rc-picker-tools">
        <label className="rc-picker-search">
          <span className="sr-only">Find an item</span>
          <input type="search" value={query} placeholder="Find an item by name or kind"
            onChange={(e) => setQuery(e.target.value)} />
        </label>
        <label className="rc-picker-kind">
          <span className="sr-only">Kind</span>
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">All kinds</option>
            {kinds.map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
        </label>
      </div>
      {rows.length === 0 ? (
        <p className="muted-line rc-empty">{query || kind ? "Nothing matches. Try other words or All kinds." : "Nothing left to add."}</p>
      ) : (
        <ul className="rc-picker-list" aria-label="Items you can add">
          {rows.map((it) => (
            <li key={`${it.collection}:${it.artifact_id}`} className="rc-pick">
              <div className="rc-pick-text">
                <span className="rc-pick-name">
                  {it.name}
                  {it.is_sample && <Chip>Sample</Chip>}
                </span>
                <span className="rc-pick-meta">
                  {it.kind}
                  {(isDuplicate(dupes, it) || !it.is_sample) && (
                    <> · <Saved iso={it.created_at || it.updated_at} exact={isDuplicate(dupes, it)} /></>
                  )}
                </span>
              </div>
              <span className="rc-pick-acts">
                {!it.is_sample && RENAMABLE.has(it.collection) && (
                  <button type="button" className="ghost sm" disabled={disabled}
                    aria-label={`Rename ${it.name}`} onClick={() => onRename(it)}>Rename</button>
                )}
                <button type="button" className="secondary sm" disabled={disabled}
                  aria-label={`Add ${it.name}`} onClick={() => onAdd(it)}>Add</button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// The report composer (#30): a section of the Reports page (not a dialog),
// opened by New report, a report's Edit, or an item's Share › "Add to a
// report…": pick saved items, give the report a title, an author line and
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

// `initial`: the item it was opened from (Share › Add to a report…); `openId`:
// a report of the workspace's to edit. `onClose` goes back (asking first if
// there are unsaved changes), `onSaved(id)` hears each save and `onDeleted`
// the delete.
export default function ReportComposer({ initial = null, openId = "", onClose, onSaved = null, onDeleted = null }) {
  const { ai } = useAppConfig();
  const { workspace, activeTeam } = useWorkspace() || {};
  const inTeam = Boolean(workspace && workspace !== "personal");
  const askText = useAskText();
  const confirm = useConfirm();
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
      onSaved?.(saved.id);
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
      (onDeleted || onClose)();
    } catch (e) {
      setError(e.message);
      setBusy(null);
    }
  };

  // Rename an item of the workspace's own, from the picker or a section.
  const onRename = async (it) => {
    const name = changedText(await askText(renamePrompt({ kind: "item", name: it.name })), it.name);
    if (!name) return;
    setError(null);
    try {
      await RENAME[it.collection](it.artifact_id, name);
      setItems((list) => renameItem(list, it, name));
      setForm((f) => ({ ...f, sections: renameItem(f.sections, it, name) }));
    } catch (e) {
      setError(e.message);
    }
  };

  // A team member without edit rights (or a frozen team) reads the team's reports.
  const current = reportId ? (reports || []).find((r) => r.id === reportId) : null;
  const readOnly = Boolean(current?.read_only);
  const canSave = form.title.trim() && form.sections.length > 0 && dirty && !busy && !readOnly;
  const saved = reportId && !dirty;
  // Nothing typed yet is nothing to lose.
  const blankNew = !reportId && !form.title.trim() && !form.introduction.trim() && form.sections.length <= (initial ? 1 : 0);
  const leave = async () => {
    if (busy) return;
    if (dirty && !blankNew && !readOnly && !(await confirm({
      title: "Leave without saving?",
      body: "Your changes to this report aren't saved yet.",
      confirmLabel: "Leave without saving",
      destructive: true,
    }))) return;
    onClose();
  };

  const footer = (
        <>
          <div>
            {reportId && !readOnly && !confirmDelete && (
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
            <button type="button" className="secondary" onClick={leave} disabled={!!busy}>
              {saved || readOnly ? "Done" : "Cancel"}
            </button>
            {!readOnly && (
              <button type="button" onClick={onSave} disabled={!canSave}>
                {busy === "save" ? "Saving…" : reportId ? (dirty ? "Save changes" : "Saved") : "Save report"}
              </button>
            )}
          </div>
        </>
  );

  return (
    <section className="card report-composer" aria-labelledby="rc-heading">
      <h2 id="rc-heading" className="sr-only">{reportId ? "Edit the report" : "New report"}</h2>
      <p className="muted-line rc-lede">
        Put several items on one page with a title and notes, ready to print.{" "}
        {inTeam
          ? <>This report belongs to {activeTeam?.name ? <b>{activeTeam.name}</b> : "this team"}: every member sees it.</>
          : "Nothing is public until you create a link."}
      </p>
      {readOnly && (
        <p className="rc-draft rc-draft-warn" role="status">
          You can read this team's reports; editing them needs a Pro plan (or the team owner's plan to be active).
        </p>
      )}

      {initial && reports?.length > 0 && (
        <label className="login-field">
          <span>Add it to</span>
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
        {!readOnly && (
          <>
            <span className="field-label rc-add-label">Add an item</span>
            <ItemPicker items={items} sections={form.sections} full={full} disabled={!!busy}
              onAdd={(it) => setSections((x) => addSection(x, it))} onRename={onRename} />
          </>
        )}
      </div>

      {error && (
        <div className="error rc-error" role="alert">
          {error.credits ? (
            <>{error.credits} <Link to="/billing">Top up credits</Link></>
          ) : error}
        </div>
      )}

      {reportId && !inTeam && (
        <div className="rc-publish">
          {dirty && <p className="muted-line rc-hint">Save your changes to update the published page.</p>}
          <PublicLinks collection="reports" artifactId={reportId} onError={setError} openable />
        </div>
      )}
      {reportId && inTeam && (
        <p className="muted-line rc-hint">
          Public links are for Personal-workspace items for now, so a team report is read here in
          Reliafy by the team's members.
        </p>
      )}
      <div className="rc-foot">{footer}</div>
    </section>
  );
}

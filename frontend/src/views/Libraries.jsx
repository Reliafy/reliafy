import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  deleteLibrary, getLibrary, listLibraries, listLibraryEntries, setLibraryVisibility,
} from "../api.js";
import PageHeader from "../components/ui/PageHeader.jsx";
import Field from "../components/ui/Field.jsx";
import { Select, TextInput } from "../components/ui/Controls.jsx";
import { SectionHeader, ShowMe } from "../components/SectionPage.jsx";
import { StorageCapNotice } from "../components/StorageCap.jsx";
import { useConfirm } from "../components/ConfirmProvider.jsx";
import { LibraryFormDialog } from "../components/LibraryParts.jsx";
import NewDatasetModal from "../components/NewDatasetModal.jsx";
import useMenuDismiss from "../components/useMenuDismiss.js";
import { AddedToLibrary } from "../components/DatasetSplit.jsx";
import "../components/Datasets.css";
import { EntryList, LibraryAbout, LibraryCard, LibraryChips, useRobots } from "../components/LibraryEntries.jsx";
import { PageTitle } from "../components/usePageTitle.js";
import { LibrarySource } from "./LibraryPages.jsx";
import {
  LIBRARIES_PATH, VISIBILITY_WORDS, addWorkspaceId, countsText, groupLibraries, libraryMatches, libraryPath, sharingProblems,
  visibilityBody,
} from "../libraries.js";
import "./LibraryPages.css";

// Libraries (Derryn, 13 Nov 2026): your own libraries of datasets and models (copies, kept as they
// were when added), shared with other workspaces by their IDs or published, beside the built-in
// handbooks. All libraries (/libraries), every entry of a kind (/libraries/data, /libraries/models)
// and one library (/libraries/:id; a handbook's page is LibraryPages.jsx's LibrarySource).

const HELP = { guide: "build-and-share-a-library" };
const CRUMBS = [{ label: "Libraries", to: LIBRARIES_PATH }];
const SECTIONS = [
  { key: "yours", title: "Yours" },
  { key: "shared", title: "Shared with you" },
  { key: "public", title: "Public" },
];

// "Your workspace ID: X [Copy]": what someone gives a library's owner to have it shared with them.
function WorkspaceIdLine({ id, children }) {
  const [copied, setCopied] = useState(false);
  if (!id) return null;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(id);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };
  return (
    <p className="libs-row lib-quiet">
      <span>Your workspace ID: <code>{id}</code></span>
      <button type="button" className="secondary sm" onClick={copy}>{copied ? "Copied" : "Copy"}</button>
      {children && <span>{children}</span>}
    </p>
  );
}

// /libraries: one card per library you can see, in three sections, with a search.
export default function LibrariesHome() {
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  const [q, setQ] = useState("");
  const [making, setMaking] = useState(false);
  const navigate = useNavigate();
  useEffect(() => {
    let live = true;
    listLibraries().then((x) => live && setD(x), (e) => live && setError(e.message));
    return () => { live = false; };
  }, []);
  const groups = useMemo(() => groupLibraries((d?.libraries || []).filter((l) => libraryMatches(l, q))), [d, q]);
  const newButton = <button type="button" onClick={() => setMaking(true)}>New library…</button>;
  const anyYours = (d?.libraries || []).some((l) => l.relation === "yours");
  return (
    <div className="app">
      <PageTitle name="All libraries" />
      <SectionHeader title="All libraries" help={HELP} primary={newButton}
                     purpose="Collections of data and models to keep, share with other workspaces or publish, and the built-in handbooks." />
      {error && <div className="card error" role="alert">{error}</div>}
      <StorageCapNotice kind="libraries" one="library" many="libraries" refreshKey={d} />
      {d === null && !error && <div className="card empty">Loading…</div>}
      {d && (
        <>
          <div className="lib-filters">
            <TextInput type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name, purpose, source or citation"
                       aria-label="Search the libraries" />
          </div>
          {SECTIONS.map(({ key, title }) => {
            const cards = groups[key];
            if (key === "yours" && !anyYours && !q) {
              return (
                <section key={key} aria-labelledby={`lib-${key}`}>
                  <h2 id={`lib-${key}`} className="lib-section">{title}</h2>
                  <div className="card empty section-empty">
                    <h3 className="lib-h">No libraries of your own yet</h3>
                    <p>A library keeps copies of your datasets and models together, to share with your team or publish.</p>
                    <div className="section-empty-action">{newButton}</div>
                    <p className="section-empty-more"><ShowMe help={HELP} /></p>
                  </div>
                </section>
              );
            }
            if (!cards.length) return null;
            return (
              <section key={key} aria-labelledby={`lib-${key}`}>
                <h2 id={`lib-${key}`} className="lib-section">{title}</h2>
                <div className="lib-sources">
                  {cards.map((l) => <LibraryCard key={l.id} lib={l} to={l.url || libraryPath(l.id)} />)}
                </div>
              </section>
            );
          })}
          <WorkspaceIdLine id={d.workspace_id}>Give it to a library’s owner to have it shared with you.</WorkspaceIdLine>
          {q && !groups.yours.length && !groups.shared.length && !groups.public.length && (
            <p className="lib-quiet">No library matches “{q}”.</p>
          )}
        </>
      )}
      {making && (
        <LibraryFormDialog onClose={() => setMaking(false)}
                           onDone={(lib) => { setMaking(false); navigate(libraryPath(lib.id)); }} />
      )}
    </div>
  );
}

// /libraries/data and /libraries/models: every entry of that kind in any library you can see.
export function LibraryEntriesPage({ type }) {
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let live = true;
    setD(null);
    listLibraryEntries(type).then((x) => live && setD(x), (e) => live && setError(e.message));
    return () => { live = false; };
  }, [type]);
  const isModel = type === "model";
  const title = isModel ? "Models" : "Data";
  return (
    <div className="app">
      <PageTitle name={`${title} in libraries`} />
      <SectionHeader section="libraries" title={title} help={HELP}
                     purpose={isModel
                       ? "Every model in the libraries you can see: yours, shared with you and public."
                       : "Every dataset in the libraries you can see: yours, shared with you and public."} />
      {error && <div className="card error" role="alert">{error}</div>}
      <section className="card">
        {isModel && d?.builtin?.length > 0 && (
          <p className="lib-builtin-links">
            Plus the published handbooks’ rates:{" "}
            {d.builtin.map((b, i) => (
              <span key={b.id}>{i > 0 && " · "}<Link to={b.url || libraryPath(b.id)}>{b.name}</Link></span>
            ))}
          </p>
        )}
        {d === null && !error ? <p className="lib-quiet">Loading…</p> : d && (
          <EntryList entries={d.entries || []} showLibrary showKind={false}
                     emptyText={isModel
                       ? "No models in any library you can see yet. Add one with Add to library… in a model’s ⋯ menu."
                       : "No data in any library you can see yet. Add one with Add to library… in a dataset’s ⋯ menu."} />
        )}
      </section>
    </div>
  );
}

// The owner's Sharing panel, in the page: Private, Shared with workspaces (their IDs), or Public
// (a licence, a citation and the right to publish).
function SharingPanel({ lib, onSaved, onClose }) {
  const [meta, setMeta] = useState(null);
  const [visibility, setVisibility] = useState(lib.visibility || "private");
  const [workspaces, setWorkspaces] = useState(lib.shared_with || []);
  const [adding, setAdding] = useState("");
  const [licence, setLicence] = useState(lib.licence?.id || "");
  const [source, setSource] = useState(lib.source || "");
  const [citation, setCitation] = useState(lib.citation || "");
  const [rights, setRights] = useState(!!lib.rights_confirmed);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(null);
  const [tried, setTried] = useState(false);
  useEffect(() => {
    let live = true;
    listLibraries().then((x) => live && setMeta(x), () => live && setMeta({ licences: [], workspace_id: null }));
    return () => { live = false; };
  }, []);
  const state = { visibility, workspaces, licence, source, citation, rights };
  const problems = sharingProblems(state);
  const add = () => { setWorkspaces((w) => addWorkspaceId(w, adding)); setAdding(""); };
  const save = async () => {
    setTried(true);
    if (problems.length) return;
    setBusy(true);
    setFailed(null);
    try {
      onSaved(await setLibraryVisibility(lib.id, visibilityBody(state)));
    } catch (e) {
      setFailed(e.message);
    } finally {
      setBusy(false);
    }
  };
  const choice = (value, label, words) => (
    <label className="lib-share-choice">
      <input type="radio" name="lib-visibility" value={value} checked={visibility === value} onChange={() => setVisibility(value)} />
      <span><strong>{label}</strong><br /><span className="lib-quiet">{words}</span></span>
    </label>
  );
  return (
    <section className="card lib-share" aria-labelledby="lib-share-h">
      <h2 id="lib-share-h" className="lib-h">Sharing</h2>
      <fieldset>
        <legend className="sr-only">Who can see this library</legend>
        {choice("private", "Private", VISIBILITY_WORDS.private)}
        {choice("workspaces", "Shared with workspaces", VISIBILITY_WORDS.workspaces)}
        {choice("public", "Public", VISIBILITY_WORDS.public)}
      </fieldset>
      {visibility === "workspaces" && <WorkspaceIdLine id={meta?.workspace_id}>Others find theirs on their All libraries page.</WorkspaceIdLine>}
      {visibility === "workspaces" && (
        <div className="lib-share">
          <p className="lib-preview-note">Ask each workspace for its ID: it shows on their All libraries page.</p>
          <div className="libs-row">
            <TextInput value={adding} onChange={(e) => setAdding(e.target.value)} placeholder="A workspace ID" aria-label="Workspace ID to add"
                       onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }} />
            <button type="button" className="secondary" onClick={add} disabled={!adding.trim()}>Add</button>
          </div>
          {workspaces.length > 0 ? (
            <ul className="lib-ws" aria-label="Shared with">
              {workspaces.map((w) => (
                <li key={w}>
                  <code>{w}</code>
                  <button type="button" className="link sm" aria-label={`Remove ${w}`} onClick={() => setWorkspaces((xs) => xs.filter((x) => x !== w))}>Remove</button>
                </li>
              ))}
            </ul>
          ) : <p className="lib-quiet">No workspaces yet.</p>}
        </div>
      )}
      {visibility === "public" && (
        <div className="lib-share">
          <p className="lib-preview-note">Only public-domain, open or CC BY data may be published, each cited.</p>
          <Field label="Licence">
            <Select value={licence} onChange={(e) => setLicence(e.target.value)}>
              <option value="">Choose a licence</option>
              {(meta?.licences || []).map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
            </Select>
          </Field>
          <Field label="Source" optional help="Where the data comes from, e.g. a site, a test programme or a report.">
            <TextInput value={source} onChange={(e) => setSource(e.target.value)} maxLength={300} />
          </Field>
          <Field label="Citation" help="How people should cite it.">
            <TextInput value={citation} onChange={(e) => setCitation(e.target.value)} maxLength={1000} />
          </Field>
          <label className="lib-share-choice">
            <input type="checkbox" checked={rights} onChange={(e) => setRights(e.target.checked)} />
            <span>I have the right to publish this</span>
          </label>
        </div>
      )}
      {tried && problems.length > 0 && <ul className="field-error" role="alert">{problems.map((p) => <li key={p}>{p}</li>)}</ul>}
      {failed && <p className="field-error" role="alert">{failed}</p>}
      <div className="libs-row">
        <button type="button" onClick={save} disabled={busy} aria-busy={busy || undefined}>{busy ? "Saving…" : "Save"}</button>
        <button type="button" className="secondary" onClick={onClose} disabled={busy}>Close</button>
      </div>
    </section>
  );
}

// /libraries/:id: one library. A built-in handbook shows its records (LibrarySource); any other
// shows what it is, its entries, and the owner's Edit…, Sharing… and Delete….
// The owner's Add…: upload data straight into the library (New dataset, this library chosen), or the
// way to add something already saved.
function AddMenu({ onUpload, onOpen }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const close = useCallback(() => setOpen(false), []);
  // It holds a line to read and links: it stays open until a choice, a click outside or Escape,
  // not closing as the mouse moves off it.
  useMenuDismiss(open, close, ref, { leavePx: Infinity });
  return (
    <div className="lib-add" ref={ref}>
      <button type="button" aria-haspopup="menu" aria-expanded={open} onClick={() => { onOpen?.(); setOpen((o) => !o); }}>
        Add…
      </button>
      {open && (
        <div className="ds-menu" role="menu">
          <button type="button" role="menuitem" onClick={() => { setOpen(false); onUpload(); }}>Upload data…</button>
          <div className="ds-menu-sep" />
          <div className="ds-menu-h">Already saved? Open the dataset or model and choose Add to library…</div>
          <Link role="menuitem" className="lib-add-link" to="/data" onClick={close}>Your data</Link>
          <Link role="menuitem" className="lib-add-link" to="/models" onClick={close}>Your models</Link>
        </div>
      )}
    </div>
  );
}

export function LibraryPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const confirm = useConfirm();
  const [lib, setLib] = useState(null);
  const [error, setError] = useState(null);
  const [missing, setMissing] = useState(false);
  const [editing, setEditing] = useState(false);
  const [sharing, setSharing] = useState(false);
  // Upload data…: New dataset over the page, this library chosen; then the page shows the new entries.
  const [uploading, setUploading] = useState(false);
  // "Added all 3 to …" after an upload: shown until the next thing the user does here.
  const [added, setAdded] = useState(null);
  const clearAdded = () => setAdded(null);
  const [tick, setTick] = useState(0);
  const uploaded = (library) => {
    setUploading(false);
    if (library) setAdded(library);
    setTick((t) => t + 1);
  };
  useEffect(() => {
    let live = true;
    if (tick) {
      getLibrary(id).then((x) => live && setLib(x), () => {});
      return () => { live = false; };
    }
    setLib(null);
    setError(null);
    setMissing(false);
    getLibrary(id).then((x) => live && setLib(x), (e) => {
      if (!live) return;
      if (e.status === 404) setMissing(true); else setError(e.message);
    });
    return () => { live = false; };
  }, [id, tick]);
  useEffect(() => setAdded(null), [id]);
  useEffect(() => {
    if (!added) return undefined;
    const next = (e) => { if (!e.target.closest?.(".ds-added-lib")) setAdded(null); };
    document.addEventListener("pointerdown", next);
    return () => document.removeEventListener("pointerdown", next);
  }, [added]);
  useRobots(!!lib?.indexable);
  if (lib?.builtin) return <LibrarySource sourceId={lib.id} />;
  if (missing) {
    return (
      <div className="app">
        <PageHeader crumbs={CRUMBS} title="Library not found" />
        <div className="card" role="alert">
          <p style={{ marginTop: 0 }}>We couldn’t find this library. It may have been deleted or made private, or the link may be mistyped.</p>
          <p style={{ marginBottom: 0 }}><Link to={LIBRARIES_PATH}>All libraries</Link></p>
        </div>
      </div>
    );
  }
  const canEdit = !!lib?.can_edit;
  const onDelete = async () => {
    const n = lib.counts?.total || 0;
    const ok = await confirm({
      title: `Delete ${lib.name}?`,
      body: `${n === 1 ? "Its 1 entry goes" : `Its ${n} entries go`} with it. The datasets and models in your workspace stay, and so do copies others made.`,
      confirmLabel: "Delete the library", destructive: true,
    });
    if (!ok) return;
    try {
      await deleteLibrary(lib.id);
      navigate(LIBRARIES_PATH);
    } catch (e) {
      setError(e.message);
    }
  };
  const setEntries = (fn) => setLib((l) => {
    const entries = fn(l.entries || []);
    const data = entries.filter((e) => e.type === "data").length;
    return { ...l, entries, counts: { data, model: entries.length - data, total: entries.length } };
  });
  return (
    <div className="app">
      <PageTitle name={lib?.name} />
      <PageHeader crumbs={CRUMBS} title={lib?.name || "Library"} badges={<LibraryChips lib={lib} />}
                  meta={lib && [lib.description, countsText(lib)].filter(Boolean).join(" · ")}
                  primary={canEdit && <AddMenu onOpen={clearAdded} onUpload={() => setUploading(true)} />}
                  actions={lib && (
                    <>
                      {canEdit && lib.visibility === "public" && (
                        <Link className="lib-signin" to={`${libraryPath(lib.id)}?as=public`}>Preview as public</Link>
                      )}
                      {canEdit && <button type="button" className="secondary" onClick={() => { clearAdded(); setEditing(true); }}>Edit…</button>}
                      {canEdit && (
                        <button type="button" className="secondary" onClick={() => { clearAdded(); setSharing((s) => !s); }}
                                aria-expanded={sharing}>Sharing…</button>
                      )}
                    </>
                  )}
                  menu={canEdit && <button type="button" className="ovm-item danger" onClick={onDelete}>Delete…</button>}
                  id={lib?.id} />
      {error && <div className="card error" role="alert">{error}</div>}
      {!lib && !error && <div className="card empty">Loading…</div>}
      {lib && (
        <>
          {sharing && canEdit && (
            <SharingPanel lib={lib} onClose={() => setSharing(false)}
                          onSaved={(x) => { setLib((l) => ({ ...l, ...x, entries: x.entries || l.entries })); setSharing(false); }} />
          )}
          {added && <AddedToLibrary library={added} />}
          <LibraryAbout lib={lib} />
          <section className="card" aria-labelledby="lib-entries-h">
            <h2 id="lib-entries-h" className="lib-h">Entries</h2>
            {canEdit && !(lib.entries || []).length ? (
              <p className="lib-quiet">
                Nothing in this library yet. Choose <strong>Add…</strong> › <strong>Upload data…</strong>, or open a{" "}
                <Link to="/data">dataset</Link> or a <Link to="/models">model</Link> and choose <strong>Add to library…</strong> from
                its ⋯ menu. The library keeps a copy as it is then.
              </p>
            ) : (
              <EntryList libraryId={lib.id} entries={lib.entries || []} canEdit={canEdit}
                         onChanged={(entry) => entry && setEntries((xs) => xs.map((e) => (e.id === entry.id ? { ...e, ...entry } : e)))}
                         onRemoved={(entryId) => setEntries((xs) => xs.filter((e) => e.id !== entryId))} />
            )}
          </section>
        </>
      )}
      {uploading && lib && (
        <NewDatasetModal title={`Upload data to ${lib.name}`} libraryChoice libraryId={lib.id} withMeasurements={false}
                         onClose={() => setUploading(false)}
                         onCreated={(ds) => uploaded(ds.library || null)}
                         onSplit={(out) => uploaded(out?.library || null)} />
      )}
      {editing && lib && (
        <LibraryFormDialog library={lib} onClose={() => setEditing(false)}
                           onDone={(x) => { setEditing(false); setLib((l) => ({ ...l, ...x, entries: x.entries || l.entries })); }} />
      )}
    </div>
  );
}

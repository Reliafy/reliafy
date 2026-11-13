import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { getLibraryEntry, refreshLibraryEntry, removeLibraryEntry, copyLibraryEntry } from "../api.js";
import { useConfirm } from "./ConfirmProvider.jsx";
import Chip from "./ui/Chip.jsx";
import { Select, TextInput } from "./ui/Controls.jsx";
import PreviewTable from "./PreviewTable.jsx";
import { ErrorNotice } from "./StorageCap.jsx";
import { isCapRefusal } from "../plan.js";
import { sig } from "../libraryModels.js";
import {
  VISIBILITY_LABEL, countsText, dataLine, entryAnchor, entryTags, filterEntries, modelBasis, modelHeadline, previewRowsText,
  usedLinks,
} from "../libraries.js";
import "../views/LibraryPages.css";

// A library's shared pieces, in the app (views/Libraries.jsx) and on the public page
// (views/PublicLibraryPage.jsx): what the library is (purpose, source, licence, citation) and its
// entries, each opening in place to its detail, with Use this data / Use this model and, for the
// owner, Update from the original and Remove.

// The library's visibility and licence, as chips.
export function LibraryChips({ lib }) {
  if (!lib) return null;
  return (
    <>
      {lib.builtin ? <Chip>Built-in</Chip> : <Chip>{VISIBILITY_LABEL[lib.visibility] || lib.visibility}</Chip>}
      {lib.licence?.name && <Chip>{lib.licence.name}</Chip>}
    </>
  );
}

// A library's card on the lists: name, purpose, counts, visibility and licence.
export function LibraryCard({ lib, to }) {
  return (
    <Link to={to} className="card lib-source">
      <h3 className="lib-h">{lib.name}</h3>
      {lib.description && <p className="lib-card-purpose">{lib.description}</p>}
      <p className="lib-facts">
        <Chip>{countsText(lib)}</Chip>
        <LibraryChips lib={lib} />
      </p>
    </Link>
  );
}

// Purpose, source, licence and citation; notes when there are any.
export function LibraryAbout({ lib }) {
  const rows = [
    ["Source", lib.source],
    ["Licence", lib.licence?.name],
    ["Citation", lib.citation],
  ].filter(([, v]) => v);
  if (!rows.length && !lib.notes) return null;
  return (
    <section className="card lib-about" aria-label="About this library">
      {rows.length > 0 && (
        <dl className="lib-dl">
          {rows.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
        </dl>
      )}
      {lib.notes && <p className="lib-notes">{lib.notes}</p>}
    </section>
  );
}

// A model's parameters, rounded, each with its bounds when it has them.
function ParamsTable({ params }) {
  if (!params?.length) return null;
  return (
    <div className="maint-scroll lib-scroll">
      <table className="lib-table">
        <thead><tr><th>Parameter</th><th className="num">Value</th><th className="num">90% bounds</th></tr></thead>
        <tbody>
          {params.map((p) => (
            <tr key={p.name}>
              <td>{p.name}</td>
              <td className="num">{sig(p.value)}</td>
              <td className="num">{Array.isArray(p.ci) && p.ci.length === 2 ? `${sig(p.ci[0])} – ${sig(p.ci[1])}` : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// An entry's detail, opened in place: a data preview (first rows) or a model's parameters.
function EntryDetail({ libraryId, entry }) {
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let live = true;
    getLibraryEntry(libraryId, entry.id).then((x) => live && setD(x), (e) => live && setError(e.message));
    return () => { live = false; };
  }, [libraryId, entry.id, entry.version]);
  if (error) return <p className="field-error" role="alert">{error}</p>;
  if (!d) return <p className="lib-quiet">Loading…</p>;
  if (d.type === "data") {
    const preview = d.data?.preview;
    return (
      <div className="lib-detail">
        {preview?.rows?.length ? (
          <>
            <div className="maint-scroll lib-scroll"><PreviewTable columns={preview.columns} rows={preview.rows} /></div>
            <p className="lib-quiet">
              {previewRowsText(preview.rows.length, d.data.n_rows)}
            </p>
          </>
        ) : <p className="lib-quiet">No rows to show.</p>}
      </div>
    );
  }
  const m = d.model || {};
  return (
    <div className="lib-detail">
      <p className="lib-detail-line">
        {[m.kind_label, m.distribution, m.unit && `times in ${m.unit}`].filter(Boolean).join(" · ")}
      </p>
      {m.params?.length ? <ParamsTable params={m.params} /> : <p className="lib-quiet">No parameters to show.</p>}
    </div>
  );
}

// Use this data / Use this model: a copy in your workspace, with links to it. A model fitted on a
// dataset in the library offers to copy that dataset too.
function UseEntry({ libraryId, entry, signedIn }) {
  const [withData, setWithData] = useState(true);
  const [busy, setBusy] = useState(false);
  const [made, setMade] = useState(null);
  const [failed, setFailed] = useState(null);
  const label = entry.type === "data" ? "Use this data" : "Use this model";
  if (!signedIn) {
    const next = typeof window === "undefined" ? "" : `?next=${encodeURIComponent(window.location.pathname)}`;
    return <Link className="lib-signin" to={`/login${next}`}>Sign in to use</Link>;
  }
  const fittedOn = entry.model?.fitted_on;
  const go = async () => {
    setBusy(true);
    setFailed(null);
    try {
      const body = entry.type === "model" && fittedOn ? { with_dataset: withData } : {};
      setMade(await copyLibraryEntry(libraryId, entry.id, body));
    } catch (e) {
      setFailed(isCapRefusal(e) ? e : e.message);
    } finally {
      setBusy(false);
    }
  };
  const links = usedLinks(made);
  return (
    <div className="lib-use">
      <button type="button" className="sm" onClick={go} disabled={busy} aria-busy={busy || undefined}>
        {busy ? "Copying…" : label}
      </button>
      {fittedOn && !made && (
        <label className="lib-tick">
          <input type="checkbox" checked={withData} onChange={(e) => setWithData(e.target.checked)} />
          Also copy the dataset it was fitted on
        </label>
      )}
      {links.length > 0 && (
        <p className="lib-made" role="status">
          Copied to your workspace:{" "}
          {links.map((l, i) => (
            <span key={l.what}>
              {i > 0 && " and "}
              <Link to={l.to}>{l.label}</Link>{l.reused ? " (you already had it)" : ""}
            </span>
          ))}.
        </p>
      )}
      <ErrorNotice error={failed} className="field-error" role="alert" />
    </div>
  );
}

// The owner's actions on an entry: where its original is, Update from the original, Remove.
function OwnerActions({ libraryId, entry, onChanged, onRemoved }) {
  const confirm = useConfirm();
  const [busy, setBusy] = useState(null);
  const [failed, setFailed] = useState(null);
  const [note, setNote] = useState(null);
  const origin = entry.origin;
  const refresh = async () => {
    setBusy("refresh");
    setFailed(null);
    try {
      const out = await refreshLibraryEntry(libraryId, entry.id);
      setNote(`Updated: now version ${out.entry?.version ?? entry.version + 1}.`);
      onChanged(out.entry);
    } catch (e) {
      setFailed(e.message);
    } finally {
      setBusy(null);
    }
  };
  const remove = async () => {
    const ok = await confirm({
      title: `Remove ${entry.name}?`,
      body: "It comes out of this library. The original stays in your workspace, and copies people made stay theirs.",
      confirmLabel: "Remove from library", destructive: true,
    });
    if (!ok) return;
    setBusy("remove");
    setFailed(null);
    try {
      await removeLibraryEntry(libraryId, entry.id);
      onRemoved(entry.id);
    } catch (e) {
      setFailed(e.message);
      setBusy(null);
    }
  };
  return (
    <div className="lib-owner">
      <span className="lib-quiet">
        {origin?.exists && origin.url ? <>Original: <Link to={origin.url}>open it</Link></> : origin ? "The original was deleted." : null}
        {origin && " · "}Version {entry.version}
      </span>
      <span className="lib-actions">
        {origin?.exists && (
          <button type="button" className="secondary sm" onClick={refresh} disabled={!!busy} aria-busy={busy === "refresh" || undefined}>
            {busy === "refresh" ? "Updating…" : "Update from the original"}
          </button>
        )}
        <button type="button" className="secondary sm danger" onClick={remove} disabled={!!busy}>Remove…</button>
      </span>
      {note && <p className="lib-made" role="status">{note}</p>}
      {failed && <p className="field-error" role="alert">{failed}</p>}
    </div>
  );
}

// One entry's row: name, kind and tags, its headline or reading, where a model came from, and
// its actions; opens in place to its detail.
function EntryRow({ libraryId, entry, open, onToggle, onJump, signedIn, canEdit, onChanged, onRemoved, showLibrary }) {
  const isModel = entry.type === "model";
  const basis = isModel ? modelBasis(entry.model) : null;
  const detailId = `${entryAnchor(entry.id)}-detail`;
  return (
    <li id={entryAnchor(entry.id)} className={"lib-entry" + (open ? " open" : "")}>
      <div className="lib-entry-head">
        <button type="button" className="link lib-entry-name" aria-expanded={open} aria-controls={detailId} onClick={onToggle}>
          <span aria-hidden="true" className="lib-caret">{open ? "▾" : "▸"}</span> {entry.name}
        </button>
        <span className="lib-facts">
          <Chip>{isModel ? "Model" : "Data"}</Chip>
          {(entry.tags || []).map((t) => <Chip key={t}>{t}</Chip>)}
        </span>
      </div>
      {showLibrary && entry.library && (
        <p className="lib-entry-line">In <Link to={`/libraries/${encodeURIComponent(entry.library.id)}#${entryAnchor(entry.id)}`}>{entry.library.name}</Link></p>
      )}
      {isModel ? (
        <>
          <p className="lib-entry-line lib-headline">{modelHeadline(entry.model)}</p>
          {basis?.fittedOn ? (
            <p className="lib-entry-line lib-quiet">
              Fitted on{" "}
              <a href={`#${entryAnchor(basis.fittedOn.entry_id)}`} onClick={(e) => { if (onJump) { e.preventDefault(); onJump(basis.fittedOn.entry_id); } }}>
                <span aria-hidden="true">↑ </span>{basis.fittedOn.name}
              </a>
            </p>
          ) : basis?.text ? <p className="lib-entry-line lib-quiet">{basis.text}</p> : null}
        </>
      ) : (
        <p className="lib-entry-line">{dataLine(entry.data)}</p>
      )}
      <div className="lib-entry-actions">
        <UseEntry libraryId={entry.library_id || libraryId} entry={entry} signedIn={signedIn} />
      </div>
      {canEdit && <OwnerActions libraryId={libraryId} entry={entry} onChanged={onChanged} onRemoved={onRemoved} />}
      {open && <div id={detailId}><EntryDetail libraryId={entry.library_id || libraryId} entry={entry} /></div>}
    </li>
  );
}

// The entries with their filters: Kind (All, Data, Model), a tag, and search. ``showLibrary``: each
// row names its library (the Data and Models views across libraries).
export function EntryList({
  libraryId = null, entries, signedIn = true, canEdit = false, onChanged, onRemoved, showLibrary = false, showKind = true,
  emptyText = "Nothing in this library yet.",
}) {
  const [kind, setKind] = useState("");
  const [tag, setTag] = useState("");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(() => new Set());
  const tags = useMemo(() => entryTags(entries), [entries]);
  const shown = useMemo(() => filterEntries(entries, { kind, tag, q }), [entries, kind, tag, q]);
  const toggle = (id) => setOpen((s) => {
    const n = new Set(s);
    if (n.has(id)) n.delete(id); else n.add(id);
    return n;
  });
  // "Fitted on ↑ <dataset>": open that entry and bring it into view (filters cleared so it shows).
  const jump = (id) => {
    setKind("");
    setTag("");
    setQ("");
    setOpen((s) => new Set(s).add(id));
    setTimeout(() => {
      const el = document.getElementById(entryAnchor(id));
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "start" });
        el.querySelector(".lib-entry-name")?.focus({ preventScroll: true });
      }
    }, 0);
  };
  // Arriving at #entry-…: that entry opens.
  useEffect(() => {
    if (typeof window === "undefined" || !entries?.length) return;
    const hash = window.location.hash.slice(1);
    const hit = hash && entries.find((e) => entryAnchor(e.id) === hash);
    if (hit) jump(hit.id);
  }, [entries?.length]);
  if (!entries?.length) return <p className="lib-quiet">{emptyText}</p>;
  return (
    <>
      <div className="lib-filters">
        <TextInput type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name, tag or column" aria-label="Search the entries" />
        {showKind && (
          <Select aria-label="Kind" value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">All</option><option value="data">Data</option><option value="model">Models</option>
          </Select>
        )}
        {tags.length > 0 && (
          <Select aria-label="Tag" value={tag} onChange={(e) => setTag(e.target.value)}>
            <option value="">Every tag</option>{tags.map((t) => <option key={t} value={t}>{t}</option>)}
          </Select>
        )}
      </div>
      {shown.length === 0 ? <p className="lib-quiet">Nothing matches.</p> : (
        <ul className="lib-entries" aria-label="Entries">
          {shown.map((e) => (
            <EntryRow key={e.id} libraryId={e.library_id || libraryId} entry={e} open={open.has(e.id)} onToggle={() => toggle(e.id)}
                      onJump={jump} signedIn={signedIn} canEdit={canEdit} onChanged={onChanged} onRemoved={onRemoved}
                      showLibrary={showLibrary} />
          ))}
        </ul>
      )}
      <p className="lib-quiet">{shown.length} of {entries.length}.</p>
    </>
  );
}

// Keeps a page out of search engines unless ``indexable`` (a public library may be indexed).
export function useRobots(indexable) {
  useEffect(() => {
    if (indexable) return undefined;
    const meta = document.createElement("meta");
    meta.name = "robots";
    meta.content = "noindex";
    document.head.appendChild(meta);
    return () => meta.remove();
  }, [indexable]);
}

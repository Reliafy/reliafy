import { useEffect, useMemo, useRef, useState } from "react";
import { getMaintenanceDocumentBlob } from "../api.js";
import { renderBasisMarkdown } from "../basisMarkdown.js";
import { BASIS_FILE_ACCEPT, BASIS_MAX, joinBasis, readBasisFile, tidyBasis } from "../basisUpload.js";
import { MAX_DOCUMENT_MB, documentFileProblem, fileSizeText } from "../maintenanceFields.js";
import { charCount } from "../maintenanceText.js";
import { DocumentViewer, fmtDate } from "./MaintenanceParts.jsx";
import OverflowMenu from "./OverflowMenu.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";

// The working behind a function's performance standard, in the details panel
// of the Explorer's RCM tab: how the standard was calculated from the
// operating context. Optional: Markdown text (typed, or from a .md file) and
// up to five PDFs. Collapsed it is a two-line preview; Read more shows the
// text; Edit gives Write and Preview. The panel's own frame never changes
// size in the table or its headings: this lives inside the panel's scroll.
//
//   r         the function's row (r.ref: id, has_basis, basis_preview, basis_on, documents)
//   basis     the writes and the read (useTreeRcm ops.basis); null where there are none
//   context   { name, to, has, go } where the operating context is (or isn't yet)
//   openToken changes when the table's (i) is clicked: open the working in full
//   readOnly  no Edit, Upload or Attach
export const MAX_PDFS = 5;

async function saveBlob(doc) {
  const blob = await getMaintenanceDocumentBlob(doc.id);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = doc.file_name || `${doc.title || "working"}.pdf`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

function Rendered({ text }) {
  const html = useMemo(() => renderBasisMarkdown(text), [text]);
  return <div className="rw-md" dangerouslySetInnerHTML={{ __html: html }} />;
}

function PdfChip({ doc, readOnly, onView, onReplace, onRemove, confirming, setConfirming, busy }) {
  return (
    <li className="rw-pdf">
      <span className="rw-pdf-mark" aria-hidden="true">PDF</span>
      <button type="button" className="link rw-pdf-title" onClick={() => onView(doc)} title={doc.title}>{doc.title}</button>
      <span className="rw-fhelp">{fileSizeText(doc.size)}</span>
      {confirming === doc.id ? (
        <span className="rw-pdf-confirm" role="group" aria-label={`Remove ${doc.title}?`}>
          <span>Remove it? The PDF is deleted.</span>
          <button type="button" className="sm danger secondary" autoFocus disabled={busy} onClick={() => onRemove(doc)}>Remove</button>
          <button type="button" className="sm secondary" onClick={() => setConfirming(null)}>Keep</button>
        </span>
      ) : (
        <OverflowMenu>
          <button type="button" className="ovm-item" onClick={() => onView(doc)}>Open</button>
          <button type="button" className="ovm-item" onClick={() => saveBlob(doc).catch(() => {})}>Download</button>
          {!readOnly && <button type="button" className="ovm-item" onClick={() => onReplace(doc)}>Replace…</button>}
          {!readOnly && <button type="button" className="ovm-item" onClick={() => setConfirming(doc.id)}>Remove…</button>}
        </OverflowMenu>
      )}
    </li>
  );
}

export default function RcmBasis({ r, basis, context = null, openToken = null, readOnly = false }) {
  const f = r.ref;
  const has = !!f.has_basis;
  const docs = f.documents || [];
  const stamp = `${f.id}:${f.basis_on || ""}:${has}`;
  const [full, setFull] = useState({ stamp: null, text: "" });
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState(null); // null | "write" | "preview"
  const [draft, setDraft] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [asking, setAsking] = useState(null); // { name, text } a .md file chosen over text already there
  const [attach, setAttach] = useState(null); // { file, title, replacing }
  const [viewing, setViewing] = useState(null);
  const [confirming, setConfirming] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const editBtn = useRef(null);
  const area = useRef(null);
  const mdInput = useRef(null);
  const pdfInput = useRef(null);

  // A different function: everything starts again.
  useEffect(() => {
    setOpen(false); setMode(null); setDraft(""); setError(null); setAsking(null); setAttach(null); setConfirming(null); setLoadError(null);
  }, [f.id]);
  useEffect(() => { if (openToken != null) setOpen(true); }, [openToken]);

  // The whole text, read once when it's wanted (the table has only a preview).
  const wanted = has && (open || mode != null);
  useEffect(() => {
    if (!wanted || !basis || full.stamp === stamp) return undefined;
    let alive = true;
    setLoadError(null);
    basis.read(f.id).then(
      (d) => alive && setFull({ stamp, text: d.standard_basis || "" }),
      (e) => alive && setLoadError(e.message),
    );
    return () => { alive = false; };
  }, [wanted, basis, stamp, f.id, full.stamp]);
  const text = full.stamp === stamp ? full.text : null;

  if (!basis) return null;
  if (readOnly && !has && !docs.length) return null;

  const count = charCount(draft, { max: BASIS_MAX, before: text ?? "" });
  const editing = mode != null;
  const back = () => setTimeout(() => editBtn.current?.focus(), 0);
  const start = async () => {
    let current = text;
    if (current == null && has) {
      // The whole text first: editing the preview would lose the rest.
      setBusy(true);
      try {
        const d = await basis.read(f.id);
        current = d.standard_basis || "";
        setFull({ stamp, text: current });
      } catch (e) { return setError(e.message); } finally { setBusy(false); }
    }
    setDraft(current ?? "");
    setError(null); setAsking(null);
    setMode("write");
    setTimeout(() => area.current?.focus(), 0);
  };
  const stop = () => { setMode(null); setError(null); setAsking(null); back(); };
  const save = async () => {
    if (busy) return;
    const next = tidyBasis(draft);
    if (next === (text ?? "")) return stop();
    if (count.over) return setError(count.message);
    setBusy(true); setError(null);
    try {
      await basis.save(f.id, next);
      setFull({ stamp: null, text: "" });
      setMode(null); setAsking(null);
      if (!next) setOpen(false);
      back();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  const keys = (e) => {
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); stop(); }
    else if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); save(); }
  };
  const chooseMd = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    const got = await readBasisFile(file);
    if (got.error) return setError(got.error);
    setError(null);
    if (!draft.trim()) setDraft(got.text);
    else setAsking({ name: file.name, text: got.text });
  };
  const applyMd = (how) => {
    const joined = joinBasis(draft, asking.text, how);
    setAsking(null);
    if (Array.from(joined.trim()).length > BASIS_MAX) {
      return setError(`Together that is ${Array.from(joined.trim()).length.toLocaleString("en-AU")} characters; a working is at most ${BASIS_MAX.toLocaleString("en-AU")}. Replace the text, or attach the file as a PDF.`);
    }
    setError(null);
    setDraft(joined);
  };

  const choosePdf = (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (file) setAttach((a) => ({ ...(a || {}), file, title: a?.title || "" }));
  };
  const startAttach = (replacing = null) => { setAttach({ file: null, title: "", replacing }); setError(null); setTimeout(() => pdfInput.current?.click(), 0); };
  const problem = attach?.file ? documentFileProblem(attach.file) : null;
  const upload = async () => {
    setBusy(true); setError(null);
    try {
      await basis.attach(f.id, attach.file, attach.title.trim());
      if (attach.replacing) await basis.detach(attach.replacing.id);
      setAttach(null);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  const removePdf = async (doc) => {
    setBusy(true); setError(null);
    try { await basis.detach(doc.id); setConfirming(null); } catch (e) { setError(e.message); } finally { setBusy(false); }
  };

  // To the Summary tab on that position (a click with a modifier keeps the link's own behaviour).
  const goContext = (e) => {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button) return;
    e.preventDefault();
    context.go();
  };
  const when = f.basis_on ? `updated ${fmtDate(f.basis_on)}` : "";
  const ctx = context && (
    context.has
      ? <>Worked out from the <a href={context.to} onClick={goContext}>operating context of {context.name}</a></>
      : <>{context.name} has no operating context yet · <a href={context.to} onClick={goContext}>add one</a></>
  );
  const empty = !has && !docs.length && !editing && !attach;

  return (
    <section className="rw-basis" aria-label="Working behind the performance standard">
      <div className="rw-basis-head">
        <h3>Working behind the performance standard</h3>
        {!readOnly && !editing && has && (
          <button type="button" className="secondary sm" ref={editBtn} onClick={start}>
            Edit<span className="sr-only"> the working</span>
          </button>
        )}
        {editing && (
          <SegmentedControl size="sm" label="Write or preview" value={mode} onChange={setMode}
                            options={[{ value: "write", label: "Write" }, { value: "preview", label: "Preview" }]} />
        )}
      </div>

      {empty && (
        <>
          <p className="rw-fhelp">
            Optional. Say how the performance standard was worked out from the operating context: the demand, the capacity, the margin.
            Markdown text, a .md file, or a PDF.
          </p>
          {!readOnly && (
            <p className="rw-basis-links">
              <button type="button" className="link" ref={editBtn} onClick={start}>Add a working…</button>
              <button type="button" className="link" onClick={() => startAttach()}>Attach a PDF…</button>
            </p>
          )}
        </>
      )}

      {!empty && !editing && has && (
        <>
          {(ctx || when) && <p className="rw-fhelp rw-basis-meta">{ctx}{ctx && when ? " · " : ""}{when}</p>}
          {open ? (
            text == null
              ? <p className="rw-fhelp" role="status">{loadError ? `Couldn't load it: ${loadError}` : "Loading…"}</p>
              : <Rendered text={text} />
          ) : <p className="rw-basis-preview">{f.basis_preview}</p>}
          <button type="button" className="link sm rw-basis-more" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
            {open ? "Show less" : "Read more"}<span className="sr-only"> of the working</span>
          </button>
        </>
      )}

      {editing && (
        <div className="rw-basis-edit">
          {mode === "write" ? (
            <span className="rw-fin">
              <textarea ref={area} className="rw-basis-area" rows={9} value={draft} disabled={busy} spellCheck="true"
                        aria-label="The working behind the performance standard, in Markdown" aria-invalid={count.over || error ? "true" : undefined}
                        placeholder={"## Chlorine demand\n\n150 g ÷ 35,000 L = 4.3 ppm/day"}
                        onChange={(e) => setDraft(e.target.value)} onKeyDown={keys} />
            </span>
          ) : draft.trim() ? <Rendered text={draft} /> : <p className="rw-fhelp">Nothing to preview yet.</p>}
          <p className="rw-fhelp">Markdown: headings, lists, tables, bold, code, links. No images or HTML.</p>
          <p className={"rw-basis-count char-count" + (count.tone ? ` ${count.tone}` : "")} aria-live="polite">{count.text}</p>
          {asking && (
            <p className="rw-basis-ask" role="group" aria-label="There is text here already">
              <span>{asking.name} ({Array.from(asking.text).length.toLocaleString("en-AU")} characters). There is text here already:</span>
              <button type="button" className="sm" onClick={() => applyMd("replace")}>Replace it</button>
              <button type="button" className="sm secondary" onClick={() => applyMd("add")}>Add below</button>
              <button type="button" className="sm secondary" onClick={() => setAsking(null)}>Cancel</button>
            </p>
          )}
          <div className="rw-basis-acts">
            <button type="button" className="secondary sm" disabled={busy} onClick={() => mdInput.current?.click()}>Upload .md</button>
            <button type="button" className="secondary sm" disabled={busy || docs.length >= MAX_PDFS}
                    title={docs.length >= MAX_PDFS ? `At most ${MAX_PDFS} PDFs on a function` : undefined} onClick={() => startAttach()}>Attach PDF</button>
            <span className="rw-basis-spacer" />
            <button type="button" className="secondary sm" disabled={busy} onClick={stop}>Cancel</button>
            <button type="button" className="sm" disabled={busy || count.blocked} onClick={save}>{busy ? "Saving…" : "Save"}</button>
          </div>
          <p className="rw-fhelp rw-basis-keys">Ctrl+Enter saves · Esc cancels</p>
        </div>
      )}

      <input ref={mdInput} type="file" hidden accept={BASIS_FILE_ACCEPT} aria-label="Choose a .md file" onChange={chooseMd} data-testid="basis-md" />
      <input ref={pdfInput} type="file" hidden accept="application/pdf,.pdf" aria-label="Choose a PDF" onChange={choosePdf} data-testid="basis-pdf" />

      {attach && (
        <div className="rw-basis-attach">
          <p className="rw-fhelp">
            {attach.replacing ? `Replace “${attach.replacing.title}”. ` : ""}PDF, at most {MAX_DOCUMENT_MB} MB; up to {MAX_PDFS} on a function.
          </p>
          <div className="rw-basis-file">
            <button type="button" className="secondary sm" onClick={() => pdfInput.current?.click()}>{attach.file ? "Choose another…" : "Choose a PDF…"}</button>
            <span className="rw-fhelp rw-basis-filename">{attach.file ? `${attach.file.name} (${fileSizeText(attach.file.size)})` : "No file chosen"}</span>
          </div>
          <label className="rw-field">
            <span className="rw-flabel">Title (optional)</span>
            <span className="rw-fin"><input value={attach.title} placeholder="Default: the file name" disabled={busy}
                                            onChange={(e) => setAttach({ ...attach, title: e.target.value })} /></span>
          </label>
          {problem && <p className="rw-ferr" role="alert">{problem}</p>}
          <div className="rw-basis-acts">
            <button type="button" className="sm" disabled={!attach.file || !!problem || busy} onClick={upload}>{busy ? "Uploading…" : attach.replacing ? "Replace" : "Upload"}</button>
            <button type="button" className="secondary sm" disabled={busy} onClick={() => setAttach(null)}>Cancel</button>
          </div>
        </div>
      )}

      {error && <p className="rw-ferr" role="alert">{error}</p>}

      {docs.length > 0 && (
        <ul className="rw-pdfs" aria-label="PDFs of the working">
          {docs.map((d) => (
            <PdfChip key={d.id} doc={d} readOnly={readOnly} busy={busy} onView={setViewing}
                     onReplace={startAttach} onRemove={removePdf} confirming={confirming} setConfirming={setConfirming} />
          ))}
        </ul>
      )}
      {!empty && !readOnly && !editing && !attach && has === false && docs.length > 0 && (
        <p className="rw-basis-links">
          <button type="button" className="link" ref={editBtn} onClick={start}>Add a working…</button>
          {docs.length < MAX_PDFS && <button type="button" className="link" onClick={() => startAttach()}>Attach another PDF…</button>}
        </p>
      )}
      {!empty && !readOnly && !editing && !attach && has && docs.length < MAX_PDFS && (
        <p className="rw-basis-links"><button type="button" className="link" onClick={() => startAttach()}>Attach a PDF…</button></p>
      )}
      {viewing && <DocumentViewer doc={viewing} onClose={() => setViewing(null)} />}
    </section>
  );
}

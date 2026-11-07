import { useEffect, useRef, useState } from "react";
import { getMaintenanceDocumentBlob } from "../api.js";
import { MAX_DOCUMENT_MB, documentFileProblem, fileSizeText } from "../maintenanceFields.js";
import { DocumentViewer } from "./MaintenanceParts.jsx";
import OverflowMenu from "./OverflowMenu.jsx";

// PDFs on a function, at the end of its "Notes and rationale" (RcmNotes.jsx):
// the working behind its performance standard as files (a calculation sheet,
// a vendor's data), up to five, each opened, downloaded, replaced or removed.
// The text of the working is in the notes themselves.
//
//   r         the function's row (r.ref: id, documents [{id, title, size}])
//   files     { attach(functionId, file, title), detach(documentId) } (useTreeRcm ops.functionPdfs)
//   readOnly  no Attach, Replace or Remove
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

export default function RcmFunctionPdfs({ r, files, readOnly = false }) {
  const f = r.ref;
  const docs = f.documents || [];
  const [attach, setAttach] = useState(null); // { file, title, replacing }
  const [viewing, setViewing] = useState(null);
  const [confirming, setConfirming] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const pdfInput = useRef(null);

  useEffect(() => { setAttach(null); setConfirming(null); setError(null); }, [f.id]);

  if (!files || (readOnly && !docs.length)) return null;

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
      await files.attach(f.id, attach.file, attach.title.trim());
      if (attach.replacing) await files.detach(attach.replacing.id);
      setAttach(null);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  const removePdf = async (doc) => {
    setBusy(true); setError(null);
    try { await files.detach(doc.id); setConfirming(null); } catch (e) { setError(e.message); } finally { setBusy(false); }
  };

  return (
    <div className="rw-fpdfs">
      {docs.length > 0 && (
        <ul className="rw-pdfs" aria-label="PDFs on this function">
          {docs.map((d) => (
            <PdfChip key={d.id} doc={d} readOnly={readOnly} busy={busy} onView={setViewing}
                     onReplace={startAttach} onRemove={removePdf} confirming={confirming} setConfirming={setConfirming} />
          ))}
        </ul>
      )}
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
      {!readOnly && !attach && docs.length < MAX_PDFS && (
        <p className="rw-basis-links"><button type="button" className="link" onClick={() => startAttach()}>Attach a PDF…</button></p>
      )}
      {viewing && <DocumentViewer doc={viewing} onClose={() => setViewing(null)} />}
    </div>
  );
}

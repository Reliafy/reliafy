import { useEffect, useState } from "react";
import { getDatasetNotation } from "../api.js";
import Loading from "./ui/Loading.jsx";

// Up to this many rows, a dataset's page offers "Show as text" (the server's limit too).
export const AS_TEXT_MAX_ROWS = 200;

// A dataset's life data as text in SurPyval's notation ("120, 310, 1000+"),
// read as its reading says, to copy out: the same text New dataset's "Type it
// in" reads back. Why it can't be written so (covariates, readings) is said
// in words instead.
export default function DatasetAsText({ datasetId, onClose }) {
  const [out, setOut] = useState(null);
  const [error, setError] = useState(null);
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    let live = true;
    getDatasetNotation(datasetId).then((r) => live && setOut(r)).catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [datasetId]);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(out.text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("Couldn't copy: select the text and copy it yourself.");
    }
  };
  return (
    <section className="ds-astext" aria-label="The data as text">
      <div className="ds-section-h">
        As text{out?.unit ? ` · times in ${String(out.unit).toLowerCase()}` : ""}
      </div>
      {!out && !error && <Loading inline as="p" label="Writing it as text…" />}
      {error && <p className="muted-line m-0" role="status">{error}</p>}
      {out && (
        <>
          <textarea className="paste-area" readOnly value={out.text} aria-label="The data as text"
                    onFocus={(e) => e.target.select()} />
          <p className="hint m-0">
            Plain numbers failed there, <code>1000+</code> was still running at 1000, <code>[a, b]</code> failed
            in that window. Paste it into <strong>New dataset › Type it in</strong> to make the same data again.
          </p>
        </>
      )}
      <div className="ds-astext-actions">
        {out && <button type="button" className="secondary" onClick={copy}>{copied ? "✓ Copied" : "Copy"}</button>}
        <button type="button" className="secondary" onClick={onClose}>Hide the text</button>
      </div>
    </section>
  );
}

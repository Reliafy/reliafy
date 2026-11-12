import { useState } from "react";

export const MODEL_PYTHON_TIP =
  "A script that refits this model with SurPyval from the data it was fitted to, and prints the numbers on this page";

// "Download as Python" in a model page's ⋯ menu: the same item, in the same
// place (first), on every model page. `download` returns a promise; a failure
// goes to `onError` (the page's notice) or, without one (a share page), shows
// under the item.
export default function DownloadPythonItem({ download, onError, title = MODEL_PYTHON_TIP }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const onClick = async () => {
    setBusy(true);
    setError(null);
    try {
      await download();
    } catch (e) {
      if (onError) onError(e.message);
      else setError(e.message || "Download failed.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <button type="button" className="ovm-item" onClick={onClick} disabled={busy} title={title}>
        {busy ? "Preparing…" : "Download as Python"}
      </button>
      {error && <span className="ovm-item muted" role="alert">{error}</span>}
    </>
  );
}

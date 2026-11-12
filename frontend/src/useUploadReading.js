// New dataset's reading (datasetReading.js): the columns of the file or paste
// exactly as the upload will store them (/api/datasets/preview), their facts,
// and the first reading guessed from them (guessReading, the fit flows' own
// first guess), for the user to check before saving.
//
//   const up = useUploadReading(source);
//   source: { file, noHeader, excel } | { text, noHeader } | null
//   up.cols, up.facts, up.nRows, up.reading, up.setReading, up.loading, up.error
import { useEffect, useMemo, useState } from "react";
import { previewDataset, previewPastedDataset } from "./api.js";
import { columnFacts } from "./lifeData.js";
import { guessReading } from "./datasetReading.js";

export function useUploadReading(source) {
  const [cols, setCols] = useState(null);
  const [reading, setReading] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const key = source ? JSON.stringify([source.file?.name, source.file?.size, source.file?.lastModified,
    source.text, source.noHeader, source.excel]) : "";

  useEffect(() => {
    setError(null);
    if (!source || (source.text != null && !source.text.trim())) {
      setCols(null);
      setReading(null);
      return undefined;
    }
    let live = true;
    setLoading(true);
    // A paste is read once typing pauses.
    const t = setTimeout(() => {
      const ask = source.file ? previewDataset(source.file, source.noHeader ?? null, source.excel || null)
        : previewPastedDataset(source.text, source.noHeader ?? null);
      ask.then((out) => {
        if (!live) return;
        const facts = columnFacts(out);
        const nRows = out.n_rows - (out.blank_rows || 0);
        setCols({ ...out, n_rows: nRows });
        setReading(guessReading(out.columns || [], facts, nRows));
      }, (err) => live && (setError(err), setCols(null), setReading(null)))
        .finally(() => live && setLoading(false));
    }, source.text != null ? 400 : 0);
    return () => { live = false; clearTimeout(t); };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  const facts = useMemo(() => (cols ? columnFacts(cols) : {}), [cols]);
  return { cols, facts, nRows: cols?.n_rows || 0, reading, setReading, loading, error };
}

// A saved dataset's reading in a fit flow (datasetReading.js): the reading to
// fit from, where it came from, and Change (edit and keep a new reading for
// the dataset). Every fit flow started from a saved dataset uses it, so none
// asks which column is which.
//
//   const rd = useDatasetReading(detail);   // detail: getDataset(id)
//   rd.reading, rd.source ("saved" | "guessed"), rd.cols, rd.facts
//   rd.startChange() → rd.draft (edit with <ReadingEditor reading={rd.draft} onChange={rd.setDraft} />)
//   rd.keep(rd.draft) → PUT /api/datasets/{id}/reading (a sample or view-only share: this fit only)
//   rd.confirm() → keeps a guessed reading as it is ("Looks right")
//   rd.keepMeasurements({ i, x, m, unit, m_unit }) → the measurements part's reading only
import { useEffect, useMemo, useState } from "react";
import { setDatasetMeasurementsReading, setDatasetReading } from "./api.js";
import { columnFacts } from "./lifeData.js";
import { datasetReading, detailColumns, readingPayload } from "./datasetReading.js";

export function useDatasetReading(detail) {
  const cols = useMemo(() => (detail ? detailColumns(detail) : null), [detail]);
  const facts = useMemo(() => (cols ? columnFacts(cols) : {}), [cols]);
  const start = useMemo(() => (detail && cols ? datasetReading(detail, { ...cols, facts }) : null), [detail, cols, facts]);
  const [reading, setReading] = useState(start?.reading || null);
  const [source, setSource] = useState(start?.source || "saved");
  const [draft, setDraft] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  useEffect(() => {
    setReading(start?.reading || null);
    setSource(start?.source || "saved");
    setDraft(null);
    setError(null);
  }, [start]);
  const readOnly = !!(detail?.read_only || detail?.is_sample);

  const keep = async (next) => {
    setSaving(true);
    setError(null);
    try {
      if (!readOnly) await setDatasetReading(detail.id, readingPayload(next));
      setReading(next);
      setSource(readOnly ? source : "saved");
      setDraft(null);
      return true;
    } catch (err) {
      setError(err);
      return false;
    } finally {
      setSaving(false);
    }
  };

  // Only the measurements part's reading: a guessed main reading stays guessed.
  const keepMeasurements = async (sub) => {
    setSaving(true);
    setError(null);
    try {
      if (!readOnly) await setDatasetMeasurementsReading(detail.id, sub);
      setReading((r) => ({ ...r, measurements: { ...sub, source: "saved" } }));
      return true;
    } catch (err) {
      setError(err);
      return false;
    } finally {
      setSaving(false);
    }
  };

  return {
    keepMeasurements,
    cols, facts, nRows: cols?.n_rows || 0, reading, source, from: start?.from || null, readOnly,
    draft, setDraft, editing: draft !== null, saving, error,
    startChange: () => setDraft(reading),
    cancelChange: () => setDraft(null),
    keep,
    confirm: () => keep(reading),
  };
}

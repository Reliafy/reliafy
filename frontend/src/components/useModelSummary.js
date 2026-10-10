import { useEffect, useState } from "react";
import { rbdBlockModel } from "../api.js";
import { modelMean, modelMedian } from "./rbdModelText.js";

// A block model's mean and median for the dialog's echo (#299), from the
// server (SurPyval's mean() and qf(0.5)), a moment after the typing stops.
// A model the server can't summarise (covariates, a fitted offset) keeps the
// plain mean the block itself shows, and no median.
export default function useModelSummary(model) {
  const [out, setOut] = useState(null);
  const plain = model && model.kind !== "regression" && !model.extras && model.distribution_id
    && (model.params || []).length > 0;
  const key = plain ? JSON.stringify([model.distribution_id, model.params]) : null;
  useEffect(() => {
    if (!key) {
      const mean = modelMean(model);
      setOut(mean == null ? null : { mean, median: modelMedian(model) });
      return undefined;
    }
    let live = true;
    const [distribution_id, params] = JSON.parse(key);
    const t = setTimeout(() => {
      rbdBlockModel({ distribution_id, params })
        .then((r) => live && setOut({ mean: r.mean, median: r.median }))
        .catch(() => {
          if (!live) return;
          const mean = modelMean(model);
          setOut(mean == null ? null : { mean, median: modelMedian(model) });
        });
    }, 200);
    return () => {
      live = false;
      clearTimeout(t);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return model ? out : null;
}

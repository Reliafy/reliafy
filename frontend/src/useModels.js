import { useCallback, useEffect, useState } from "react";
import { listModels } from "./api.js";

// Small hook for the saved-models list with manual refresh. `error` is the
// failed read (models stays [] for callers that only need the names).
export function useModels() {
  const [models, setModels] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const refresh = useCallback(() => {
    setLoading(true);
    setError(null);
    return listModels()
      .then((d) => setModels(d.models))
      .catch((e) => {
        setModels([]);
        setError(e);
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { models, loading, error, refresh };
}

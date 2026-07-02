import { useCallback, useEffect, useState } from "react";
import { listModels } from "./api.js";

// Small hook for the saved-models list with manual refresh.
export function useModels() {
  const [models, setModels] = useState([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(() => {
    setLoading(true);
    return listModels()
      .then((d) => setModels(d.models))
      .catch(() => setModels([]))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { models, loading, refresh };
}

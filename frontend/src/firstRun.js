import { useEffect, useState } from "react";
import {
  getWorkspace,
  listAltModels,
  listDatasets,
  listDegradationModels,
  listModels,
  listRbds,
  listRecurrentModels,
} from "./api.js";

// First-run state (#194): a workspace with no models, datasets or diagrams of
// its own gets three one-click starts instead of an empty list. "Own" is the
// ModellingDashboard rule — anything not flagged ``is_sample`` — so shared
// samples never count, and items shared with you do.

// The starts point at these samples when the workspace can see them.
export const SAMPLE_MODEL = "sample-model-bearings-weibull";
const SAMPLE_RBD = "sample-rbd-pump-station";

// Workspaces seen with work of their own this session. Work rarely goes back to
// zero, so the lists aren't fetched again for them.
const hasOwnWork = new Set();

const own = (items) => (items || []).some((x) => !x.is_sample);

function pick(items, id, prefer = () => true) {
  const samples = (items || []).filter((x) => x.is_sample);
  return (
    samples.find((x) => x.id === id) || samples.find(prefer) || samples[0] || null
  )?.id || null;
}

// Resolves to false (the workspace has its own work, or the lists couldn't be
// read) or to the first-run starts: { sampleModelId, sampleRbdId }, either of
// which is null when no sample of that kind is visible.
export async function loadFirstRun() {
  const ws = getWorkspace();
  if (hasOwnWork.has(ws)) return false;
  const [models, datasets, rbds, alt, recurrent, degradation] = await Promise.all([
    listModels().then((r) => r.models),
    listDatasets().then((r) => r.datasets),
    listRbds().then((r) => r.rbds),
    listAltModels().then((r) => r.models),
    listRecurrentModels().then((r) => r.models),
    listDegradationModels().then((r) => r.models),
  ]).catch(() => [null]);
  if (models === null) return false;
  if ([models, datasets, rbds, alt, recurrent, degradation].some(own)) {
    hasOwnWork.add(ws);
    return false;
  }
  return {
    sampleModelId: pick(models, SAMPLE_MODEL, (m) => m.kind !== "regression"),
    sampleRbdId: pick(rbds, SAMPLE_RBD),
  };
}

// ``pageHasOwn``: whether the calling page's own list already shows work of
// the user's own — undefined while it loads, true to skip the fetch entirely.
// Returns null while unknown, false when hidden, or the starts.
export function useFirstRun(pageHasOwn) {
  const [state, setState] = useState(null);
  useEffect(() => {
    if (pageHasOwn === undefined) return undefined;
    if (pageHasOwn) {
      hasOwnWork.add(getWorkspace());
      setState(false);
      return undefined;
    }
    let live = true;
    loadFirstRun().then((s) => live && setState(s));
    return () => {
      live = false;
    };
  }, [pageHasOwn]);
  return pageHasOwn ? false : state;
}

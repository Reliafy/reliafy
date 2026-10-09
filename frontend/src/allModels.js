import {
  listModels,
  deleteModel,
  listDegradationModels,
  deleteDegradationModel,
  listAltModels,
  deleteAltModel,
  listRecurrentModels,
  deleteRecurrentModel,
} from "./api.js";
import { distColor } from "./instrument.js";

// Every saved model — life data, accelerated life, recurrent, degradation — as
// one list of rows, newest first. Shared by the All models list and the
// Modelling home's "Your recent models".

export const TYPE_LABEL = {
  life: "Life data",
  degradation: "Degradation",
  alt: "Accelerated life",
  recurrent: "Recurrent",
};

export const distLabel = (d = "") => String(d).replace(/\s*\(.*$/, "").replace(/\s+PH$/, "");

export async function loadAllModels() {
  const [lm, dm, am, rm] = await Promise.all([
    listModels(), listDegradationModels(), listAltModels(), listRecurrentModels(),
  ]);
  const common = (m) => ({
    id: m.id,
    name: m.name,
    is_sample: m.is_sample,
    read_only: m.read_only,
    shared_by: m.shared_by,
  });
  const life = (lm.models || []).map((m) => ({
    ...common(m),
    type: "life",
    detail: (distLabel(m.distribution) || "—") + (m.kind === "regression" ? " · PH" : ""),
    noMax: !!m.no_finite_maximum,
    color: distColor(m.distribution),
    created_at: m.created_at,
    to: `/modelling/m/${m.id}`,
  }));
  const deg = (dm.models || []).map((m) => ({
    ...common(m),
    type: "degradation",
    detail: m.path_model || "—",
    color: "#7c3aed",
    created_at: m.updated_at || m.created_at,
    to: `/modelling/degradation/${m.id}`,
  }));
  const acc = (am.models || []).map((m) => ({
    ...common(m),
    type: "alt",
    // e.g. "Weibull · Arrhenius" — the distribution and its life-stress law.
    detail: [distLabel(m.distribution), m.life_model].filter(Boolean).join(" · ") || "—",
    noMax: !!m.no_finite_maximum,
    color: "#0f9ab0",
    created_at: m.created_at,
    to: `/modelling/alt/${m.id}`,
  }));
  const rec = (rm.models || []).map((m) => ({
    ...common(m),
    type: "recurrent",
    detail: m.model || "—",
    color: "#d0762f",
    created_at: m.created_at,
    to: `/modelling/recurrent/${m.id}`,
  }));
  return [...life, ...deg, ...acc, ...rec].sort((a, b) => (a.created_at > b.created_at ? -1 : 1));
}

export function deleteAnyModel(row) {
  if (row.type === "life") return deleteModel(row.id);
  if (row.type === "degradation") return deleteDegradationModel(row.id);
  if (row.type === "alt") return deleteAltModel(row.id);
  return deleteRecurrentModel(row.id);
}

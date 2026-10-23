import {
  listModels,
  deleteModel,
  listDegradationModels,
  deleteDegradationModel,
  listAltModels,
  deleteAltModel,
  listRecurrentModels,
  deleteRecurrentModel,
  listJointModels,
  deleteJointModel,
} from "./api.js";
import { distColor } from "./instrument.js";
import { CATEGORY } from "./plotTheme.js";

// Every saved model — life data, accelerated life, recurrent, degradation — as
// one list of rows, newest first. Shared by the Models list and Home's
// "Recent".

export const TYPE_LABEL = {
  life: "Non-repairable model",
  degradation: "Degradation",
  alt: "Accelerated life",
  recurrent: "Repairable model",
  joint: "Condition and life",
};

// The Models list's type filter: the same names as the menu's children.
export const TYPE_FILTERS = [
  { value: "life", label: "Non-repairable models" },
  { value: "recurrent", label: "Repairable models" },
  { value: "alt", label: "Accelerated life" },
  { value: "degradation", label: "Degradation" },
  { value: "joint", label: "Condition and life" },
];

export const distLabel = (d = "") => String(d).replace(/\s*\(.*$/, "").replace(/\s+PH$/, "");

export async function loadAllModels() {
  const [lm, dm, am, rm, jm] = await Promise.all([
    listModels(), listDegradationModels(), listAltModels(), listRecurrentModels(),
    listJointModels().catch(() => ({ models: [] })),
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
    to: `/models/m/${m.id}`,
  }));
  const deg = (dm.models || []).map((m) => ({
    ...common(m),
    type: "degradation",
    detail: m.path_model || "—",
    color: CATEGORY.violet,
    created_at: m.updated_at || m.created_at,
    to: `/models/degradation/${m.id}`,
  }));
  const acc = (am.models || []).map((m) => ({
    ...common(m),
    type: "alt",
    // e.g. "Weibull · Arrhenius" — the distribution and its life-stress law.
    detail: [distLabel(m.distribution), m.life_model].filter(Boolean).join(" · ") || "—",
    noMax: !!m.no_finite_maximum,
    color: CATEGORY.teal,
    created_at: m.created_at,
    to: `/models/alt/${m.id}`,
  }));
  const rec = (rm.models || []).map((m) => ({
    ...common(m),
    type: "recurrent",
    detail: m.model || "—",
    color: CATEGORY.amber,
    created_at: m.created_at,
    to: `/models/recurrent/${m.id}`,
  }));
  const joint = (jm.models || []).map((m) => ({
    ...common(m),
    type: "joint",
    // e.g. "vibration · Linear path"
    detail: [m.marker, m.path_model && `${m.path_model} path`].filter(Boolean).join(" · ") || "—",
    noMax: m.fit_ok === false,
    color: CATEGORY.blue,
    created_at: m.created_at,
    to: `/models/joint/${m.id}`,
  }));
  return [...life, ...deg, ...acc, ...rec, ...joint].sort((a, b) => (a.created_at > b.created_at ? -1 : 1));
}

export function deleteAnyModel(row) {
  if (row.type === "life") return deleteModel(row.id);
  if (row.type === "degradation") return deleteDegradationModel(row.id);
  if (row.type === "alt") return deleteAltModel(row.id);
  if (row.type === "joint") return deleteJointModel(row.id);
  return deleteRecurrentModel(row.id);
}

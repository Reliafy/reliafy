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
import { modelRows } from "./modelRows.js";

// Every saved model as one list of rows (modelRows.js), read from each kind's
// list. Shared by the Models list; Home has the same lists in its summary.
export { TYPE_LABEL, TYPE_FILTERS, distLabel, modelRows } from "./modelRows.js";

export async function loadAllModels() {
  const [life, degradation, alt, recurrent, joint] = await Promise.all([
    listModels(), listDegradationModels(), listAltModels(), listRecurrentModels(),
    listJointModels().catch(() => ({ models: [] })),
  ]);
  return modelRows({ life, degradation, alt, recurrent, joint });
}

export function deleteAnyModel(row) {
  if (row.type === "life") return deleteModel(row.id);
  if (row.type === "degradation") return deleteDegradationModel(row.id);
  if (row.type === "alt") return deleteAltModel(row.id);
  if (row.type === "joint") return deleteJointModel(row.id);
  return deleteRecurrentModel(row.id);
}

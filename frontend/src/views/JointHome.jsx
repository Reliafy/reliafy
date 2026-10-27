import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listJointModels, deleteJointModel } from "../api.js";
import { relativeTime } from "../instrument.js";
import { CATEGORY } from "../plotTheme.js";
import Chip from "../components/ui/Chip.jsx";
import { PlusIcon, RowActions, itemName } from "../components/LibRows.jsx";
import { SectionHeader, SectionList } from "../components/SectionPage.jsx";
import { useConfirm } from "../components/ConfirmProvider.jsx";
import { deleteOrRemoveConfirm } from "../confirm.js";

const JOINT_COLOR = CATEGORY.blue;
const HELP = { guide: "condition-based-risk" };

// Condition and life models (joint models of readings and failures): the
// list, like the other model types'. The fit lives on /models/joint/new.
export default function JointHome() {
  const navigate = useNavigate();
  const [models, setModels] = useState(null);
  const [error, setError] = useState(null);

  const refresh = () => listJointModels().then((r) => setModels(r.models)).catch(() => setModels([]));
  useEffect(() => { refresh(); }, []);

  const confirm = useConfirm();
  const onDelete = async (m) => {
    if (!(await confirm(deleteOrRemoveConfirm(m, "model", { name: itemName(m) })))) return;
    try {
      await deleteJointModel(m.id);
      refresh();
    } catch (err) {
      setError(err.message);
    }
  };

  const open = (id) => navigate(`/models/joint/${id}`);
  const newModel = <button onClick={() => navigate("/models/joint/new")}><PlusIcon /> New model</button>;

  return (
    <div className="app">
      <SectionHeader
        section="models"
        title="Remaining life from condition readings"
        purpose="Combine readings (vibration, wear, oil debris) and failure history to see each unit's risk and remaining life."
        help={HELP}
        primary={newModel}
      />
      {error && <div className="card error">{error}</div>}
      <SectionList
        rows={models}
        noun={["model", "models"]}
        fields={(m) => [m.name, m.marker, m.path_model]}
        help={HELP}
        empty={{
          title: "No condition and life models yet",
          body: "Fit one from a dataset holding your units' life data (each one's age at failure, or now, and whether it failed) and their measurements (unit, age, value).",
          action: newModel,
        }}
        head={[
          <th key="m" style={{ width: "36%" }}>Model</th>,
          <th key="r">Reading</th>,
          <th key="u" className="lib-opt" style={{ width: 80 }}>Units</th>,
          <th key="n" className="lib-opt" style={{ width: 80 }}>Running</th>,
          <th key="s" className="lib-opt">Saved</th>,
          <th key="a"><span className="sr-only">Actions</span></th>,
        ]}
        render={(m) => (
          <tr key={m.id} className="lib-row" onClick={() => open(m.id)}>
            <td>
              <div className="lib-name">
                {itemName(m)}
                {m.shared_by && <Chip title={`Shared by ${m.shared_by}`}>Shared</Chip>}
              </div>
            </td>
            <td>
              <Chip dot={JOINT_COLOR}>{[m.marker, m.path_model && `${m.path_model} path`].filter(Boolean).join(" · ") || "—"}</Chip>
            </td>
            <td className="lib-n lib-opt">{(m.n_items ?? 0).toLocaleString()}</td>
            <td className="lib-n lib-opt">{(m.n_running ?? 0).toLocaleString()}</td>
            <td className="lib-date lib-opt">{relativeTime(m.created_at)}</td>
            <RowActions item={m} onOpen={() => open(m.id)} onDelete={() => onDelete(m)} />
          </tr>
        )}
      />
    </div>
  );
}

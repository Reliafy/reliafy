import { useCallback, useEffect, useState } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { listDegradationModels, deleteDegradationModel } from "../api.js";
import { relativeTime } from "../instrument.js";
import Chip from "../components/ui/Chip.jsx";
import { PlusIcon, RowActions, RowLink, itemName, rowOpen } from "../components/LibRows.jsx";
import { SectionHeader, SectionList } from "../components/SectionPage.jsx";
import { useConfirm } from "../components/ConfirmProvider.jsx";
import { deleteOrRemoveConfirm } from "../confirm.js";
import { StorageCapNotice } from "../components/StorageCap.jsx";

const HELP = { guide: "degradation-modelling" };

// Models › Degradation: list, create (the New model page,
// /models/degradation/new, fits, saves and opens the new model's page), open,
// delete. Lives inside the Models section.
export default function DegradationHome() {
  const navigate = useNavigate();
  const [models, setModels] = useState(null);
  const [params] = useSearchParams();
  // ?dataset= (an earlier link to the new-model flow) goes to the New model page on that dataset.
  const fromData = params.get("dataset");
  const [error, setError] = useState(null);

  const refresh = useCallback(() => {
    listDegradationModels()
      .then((d) => setModels(d.models))
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => refresh(), [refresh]);


  const confirm = useConfirm();
  const onDelete = async (m) => {
    if (!(await confirm(deleteOrRemoveConfirm(m, "model", { name: itemName(m), extra: "with its tracked items" })))) return;
    try {
      await deleteDegradationModel(m.id);
      refresh();
    } catch (err) {
      setError(err.message);
    }
  };

  const pathOf = (id) => `/models/degradation/${id}`;
  const newModel = <button onClick={() => navigate("/models/degradation/new")}><PlusIcon /> New model</button>;

  if (fromData) return <Navigate to={`/models/degradation/new?dataset=${encodeURIComponent(fromData)}`} replace />;

  return (
    <div className="app">
      <SectionHeader
        section="models"
        title="Degradation models"
        purpose={<>How items wear toward a failure threshold. Track each one in <Link to="/risk">Condition monitoring</Link>.
          Failure times too? Use <Link to="/models/joint">Condition and life</Link>.</>}
        help={HELP}
        primary={newModel}
      />

      {error && <div className="card error">{error}</div>}
      <StorageCapNotice kind="degradation_models" one="degradation model" many="degradation models" refreshKey={models} />

      <SectionList
        rows={models}
        noun={["model", "models"]}
        fields={(m) => [m.name, m.path_model]}
        help={HELP}
        empty={{
          title: "No degradation models yet",
          body: "Fit one from measurement histories to start predicting remaining useful life.",
          action: newModel,
        }}
        head={[
          <th key="m" style={{ width: "36%" }}>Model</th>,
          <th key="p">Path</th>,
          <th key="t" className="lib-opt" style={{ width: 110 }}>Threshold</th>,
          <th key="u" className="lib-opt" style={{ width: 80 }}>Items</th>,
          <th key="k" className="lib-opt" style={{ width: 90 }}>Tracked</th>,
          <th key="s" className="lib-opt">Saved</th>,
          <th key="a"><span className="sr-only">Actions</span></th>,
        ]}
        render={(m) => (
          <tr key={m.id} className="lib-row" onClick={rowOpen(navigate, pathOf(m.id))}>
            <td>
              <div className="lib-name">
                <RowLink to={pathOf(m.id)}>{itemName(m)}</RowLink>
                {m.shared_by && <Chip title={`Shared by ${m.shared_by}`}>Shared</Chip>}
              </div>
            </td>
            <td>{m.path_model || "—"}</td>
            <td className="lib-n lib-opt">{m.threshold}{m.measurement_unit ? ` ${m.measurement_unit}` : ""}</td>
            <td className="lib-n lib-opt">{m.n_units}</td>
            <td className="lib-n lib-opt">{m.n_items}</td>
            <td className="lib-date lib-opt">{relativeTime(m.updated_at || m.created_at)}</td>
            <RowActions item={m} to={pathOf(m.id)} onDelete={() => onDelete(m)} />
          </tr>
        )}
      />
    </div>
  );
}

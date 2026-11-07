import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { deleteMaintainabilityPrediction, listMaintainabilityPredictions } from "../api.js";
import { relativeTime } from "../instrument.js";
import Chip from "../components/ui/Chip.jsx";
import { SectionHeader, SectionList } from "../components/SectionPage.jsx";
import { PlusIcon, RowActions, RowLink, itemName, rowOpen } from "../components/LibRows.jsx";
import { useConfirm } from "../components/ConfirmProvider.jsx";
import { deleteOrRemoveConfirm } from "../confirm.js";
import { MAINTAINABILITY_GUIDE, MAINTAINABILITY_PATH, MAINTAINABILITY_SAMPLE } from "../maintainability.js";

const HELP = { guide: MAINTAINABILITY_GUIDE };

// Modelling › Maintainability prediction: the saved predictions (the sample
// among them), and the way to a new one.
export default function MaintainabilityHome() {
  const navigate = useNavigate();
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);

  const refresh = useCallback(() => {
    listMaintainabilityPredictions()
      .then((d) => setRows(d.predictions || []))
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => refresh(), [refresh]);

  const confirm = useConfirm();
  const onDelete = async (p) => {
    if (!(await confirm(deleteOrRemoveConfirm(p, "prediction", { name: itemName(p) })))) return;
    try {
      await deleteMaintainabilityPrediction(p.id);
      refresh();
    } catch (err) {
      setError(err.message);
    }
  };

  const pathOf = (id) => `${MAINTAINABILITY_PATH}/${encodeURIComponent(id)}`;
  const newPrediction = <button onClick={() => navigate(`${MAINTAINABILITY_PATH}/new`)}><PlusIcon /> New prediction</button>;

  return (
    <div className="app">
      <SectionHeader
        section="maintainability"
        title="Maintainability prediction"
        purpose="How long repairs take: the mean repair time, the time most repairs are done by, and which parts drive it, from a parts list."
        help={HELP}
        primary={newPrediction}
      />

      {error && <div className="card error">{error}</div>}

      <SectionList
        rows={rows}
        noun={["saved prediction", "saved predictions"]}
        placeholder="Search predictions…"
        fields={(p) => [p.name, p.product?.name, p.headline]}
        help={HELP}
        empty={{
          title: "No maintainability predictions yet",
          body: <>Type or paste a parts list, give each line its repair times, and save the result. Or open the{" "}
            <Link to={pathOf(MAINTAINABILITY_SAMPLE)}>sample quadcopter</Link> to see one.</>,
          action: newPrediction,
        }}
        head={[
          <th key="n" style={{ width: "34%" }}>Prediction</th>,
          <th key="p" className="lib-opt">Product</th>,
          <th key="r">Result</th>,
          <th key="s" className="lib-opt">Saved</th>,
          <th key="a"><span className="sr-only">Actions</span></th>,
        ]}
        render={(p) => (
          <tr key={p.id} className="lib-row" onClick={rowOpen(navigate, pathOf(p.id))}>
            <td>
              <div className="lib-name">
                <RowLink to={pathOf(p.id)}>{itemName(p)}</RowLink>
                {p.shared_by && <Chip title={`Shared by ${p.shared_by}`}>Shared</Chip>}
              </div>
              <div className="lib-date">{p.lines} {p.lines === 1 ? "line" : "lines"}</div>
            </td>
            <td className="lib-opt lib-date">{p.product?.name || "—"}</td>
            <td className="lib-date">{p.headline}</td>
            <td className="lib-date lib-opt">{relativeTime(p.updated_at || p.created_at)}</td>
            <RowActions item={p} to={pathOf(p.id)} onDelete={() => onDelete(p)} />
          </tr>
        )}
      />
    </div>
  );
}

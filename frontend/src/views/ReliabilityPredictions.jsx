import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { deletePrediction, listPredictions } from "../api.js";
import { relativeTime } from "../instrument.js";
import { SectionHeader, SectionList } from "../components/SectionPage.jsx";
import { PlusIcon, RowActions, RowLink, itemName, rowOpen } from "../components/LibRows.jsx";
import { useConfirm } from "../components/ConfirmProvider.jsx";
import { deleteOrRemoveConfirm } from "../confirm.js";
import {
  PREDICTIONS_GUIDE, PREDICTIONS_LABEL, PREDICTIONS_PURPOSE, fmtHours, fmtPerMillion, newPredictionPath, predictionPath,
} from "../predictions.js";
import "./Predictions.css";

const HELP = { guide: PREDICTIONS_GUIDE };

// Reliability prediction's landing page: the saved parts counts, the user's
// own then the shared sample, and the way to a new one.
export default function ReliabilityPredictions() {
  const navigate = useNavigate();
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);

  const refresh = useCallback(() => {
    listPredictions()
      .then((d) => setRows(d.predictions || []))
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => refresh(), [refresh]);

  const confirm = useConfirm();
  const onDelete = async (p) => {
    if (!(await confirm(deleteOrRemoveConfirm(p, "prediction", { name: itemName(p) })))) return;
    try {
      await deletePrediction(p.id);
      refresh();
    } catch (err) {
      setError(err.message);
    }
  };

  const newPrediction = (
    <button onClick={() => navigate(newPredictionPath())}><PlusIcon /> New prediction</button>
  );

  return (
    <div className="app">
      <SectionHeader title={PREDICTIONS_LABEL} purpose={PREDICTIONS_PURPOSE} help={HELP} primary={newPrediction} />

      {error && <div className="card error">{error}</div>}

      <SectionList
        rows={rows}
        noun={["prediction", "predictions"]}
        placeholder="Search predictions…"
        fields={(p) => [p.name, p.environment, p.environment_name, p.product?.name, p.headline]}
        help={HELP}
        empty={{
          title: "No predictions yet",
          body: <>A prediction adds up a design's parts list from handbook base rates: paste the parts list or
            pick a product, give each line a part type, choose where the equipment works, and read the failure
            rate, MTBF and reliability. <Link to={newPredictionPath()}>Start a new prediction</Link>.</>,
          action: newPrediction,
        }}
        head={[
          <th key="n" style={{ width: "34%" }}>Prediction</th>,
          <th key="e" className="lib-opt">Environment</th>,
          <th key="p" className="num lib-opt">Lines</th>,
          <th key="r" className="num">Failures / 10⁶ h</th>,
          <th key="m" className="num">MTBF (h)</th>,
          <th key="s" className="lib-opt">Saved</th>,
          <th key="a"><span className="sr-only">Actions</span></th>,
        ]}
        render={(p) => (
          <tr key={p.id} className="lib-row" onClick={rowOpen(navigate, predictionPath(p.id))}>
            <td>
              <div className="lib-name">
                <RowLink to={predictionPath(p.id)}>{itemName(p)}</RowLink>
              </div>
              {p.product?.name && <div className="lib-date">{p.product.name}</div>}
            </td>
            <td className="lib-opt">{p.environment_name ? `${p.environment_name} (${p.environment})` : p.environment}</td>
            <td className="num lib-opt">
              {p.lines}
              {p.assigned != null && p.assigned !== p.lines && <div className="lib-date">{p.assigned} with a part type</div>}
            </td>
            <td className="num">{p.failure_rate_per_million_hours ? fmtPerMillion(p.failure_rate_per_million_hours) : <span className="lib-date">—</span>}</td>
            <td className="num">{p.mtbf_hours ? fmtHours(p.mtbf_hours) : <span className="lib-date">—</span>}</td>
            <td className="lib-date lib-opt">{relativeTime(p.updated_at || p.created_at)}</td>
            <RowActions item={p} to={predictionPath(p.id)} onDelete={() => onDelete(p)} />
          </tr>
        )}
      />
    </div>
  );
}

import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import RecurrentResultView from "../components/RecurrentResultView.jsx";
import { getRecurrentModel, deleteRecurrentModel } from "../api.js";

// A saved recurrent-event model: its MCF / Crow-AMSAA fit and reliability-growth
// verdict.
export default function RecurrentModelPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [model, setModel] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setModel(null);
    getRecurrentModel(id).then(setModel).catch((e) => setError(e.message));
  }, [id]);

  const onDelete = async () => {
    if (!window.confirm(`Delete "${model.name}"?`)) return;
    await deleteRecurrentModel(id);
    navigate("/modelling/recurrent");
  };

  if (error) return <div className="app"><div className="card error">{error}</div></div>;
  if (!model) return <div className="app"><div className="card empty">Loading…</div></div>;

  return (
    <div className="app">
      <header>
        <div>
          <div className="crumb">
            <button className="crumb-link" onClick={() => navigate("/modelling")}>Modelling</button> /{" "}
            <button className="crumb-link" onClick={() => navigate("/modelling/recurrent")}>Recurrent</button> /{" "}
            <b>{model.name}</b>
          </div>
          <h1>{model.name}</h1>
        </div>
        {!model.read_only && (
          <button className="secondary" onClick={onDelete}>Delete</button>
        )}
      </header>
      <RecurrentResultView results={model.results} />
    </div>
  );
}

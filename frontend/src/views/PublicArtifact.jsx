import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import Plot from "react-plotly.js";
import PublicNav from "../components/PublicNav.jsx";
import PublicFooter from "../components/PublicFooter.jsx";
import ResultView from "../components/ResultView.jsx";
import DegradationResultView from "../components/DegradationResultView.jsx";
import ReplacementResult from "../components/ReplacementResult.jsx";
import CompareResult from "../components/CompareResult.jsx";
import FfiResult from "../components/FfiResult.jsx";
import PreviewTable from "../components/PreviewTable.jsx";
import RcmTree from "../components/RcmTree.jsx";
import { RollupBadges } from "../components/RcmStatusBadge.jsx";
import { getPublicArtifact } from "../api.js";

// Public, read-only view of a shared artifact (/p/:token) — no account
// needed. Renders the same payloads as the in-app detail pages through the
// same presentational components. This route is its own lazy chunk so the
// marketing pages don't inherit its Plotly dependency.

const KIND_LABEL = {
  models: "Fitted life model",
  datasets: "Dataset",
  degradation_models: "Degradation model",
  strategy_analyses: "Strategy analysis",
  rcm_studies: "RCM study",
  fleets: "Fleet failure forecast",
};

const fmt = (v, dp = 1) =>
  v === null || v === undefined ? "—" : Number(v).toLocaleString(undefined, { maximumFractionDigits: dp });

function FleetView({ a }) {
  const f = a.forecast || {};
  const unit = f.unit || "";
  return (
    <>
      {f.status === "stale" && (
        <div className="card note">{f.reason || "The linked life model is unavailable."}</div>
      )}
      {f.status === "ok" && (
        <div className="stats">
          <div className="stat"><div className="k">Expected failures</div><div className="v">{fmt(f.expected)}</div></div>
          <div className="stat"><div className="k">Likely range (P10–P90)</div><div className="v sm">{fmt(f.interval?.[0])} – {fmt(f.interval?.[1])}</div></div>
          <div className="stat"><div className="k">Horizon</div><div className="v sm">{f.periods} {f.period_label}</div></div>
          <div className="stat"><div className="k">Counting</div><div className="v sm">{f.method === "renewals" ? "with replacement" : "first failures"}</div></div>
        </div>
      )}
      {(a.items || []).length > 0 && (
        <div className="card" style={{ marginTop: "1rem" }}>
          <h2>Items</h2>
          <table className="lib-table">
            <thead>
              <tr>
                <th>Item</th>
                <th>Current use{unit ? ` (${unit})` : ""}</th>
                <th>P(failure)</th>
                <th>Expected failures</th>
              </tr>
            </thead>
            <tbody>
              {a.items.map((it) => {
                const r = (f.per_item || []).find((p) => p.id === it.id) || {};
                return (
                  <tr key={it.id} className="lib-row">
                    <td>{it.name}</td>
                    <td className="lib-n">{fmt(it.current_use, 0)}</td>
                    <td className="lib-n">{r.prob_any === undefined ? "—" : `${(r.prob_any * 100).toFixed(0)}%`}</td>
                    <td className="lib-n">{r.expected === undefined ? "—" : fmt(r.expected, 2)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {f.status === "ok" && (f.per_period || []).some((v) => v > 0) && (
        <div className="card" style={{ marginTop: "1rem" }}>
          <h2>Expected failures per {String(f.period_label || "period").replace(/s$/, "")}</h2>
          <Plot
            data={[{
              type: "bar",
              x: Array.from({ length: f.periods || 0 }, (_, i) => i + 1),
              y: f.per_period,
              marker: { color: "#2f6df6" },
            }]}
            layout={{
              height: 300,
              margin: { l: 46, r: 16, t: 8, b: 42 },
              xaxis: { title: { text: f.period_label || "period" }, dtick: 1 },
              yaxis: { title: { text: "expected failures" } },
              paper_bgcolor: "transparent",
              plot_bgcolor: "transparent",
            }}
            config={{ displayModeBar: false, responsive: true }}
            style={{ width: "100%" }}
          />
        </div>
      )}
    </>
  );
}

function Body({ collection, a }) {
  switch (collection) {
    case "models":
      return <div className="card"><ResultView result={a.results} /></div>;
    case "degradation_models":
      return <div className="card"><DegradationResultView results={a.results} /></div>;
    case "strategy_analyses":
      return (
        <div className="card">
          {a.kind === "optimal_replacement" && <ReplacementResult result={a.results} />}
          {a.kind === "compare_two" && <CompareResult result={a.results} />}
          {a.kind === "failure_finding" && <FfiResult result={a.results} />}
        </div>
      );
    case "datasets":
      return (
        <div className="card">
          {a.preview?.length ? (
            <>
              <div className="ds-section-h">Preview · first {a.preview.length} rows</div>
              <PreviewTable columns={a.preview_columns} rows={a.preview} />
            </>
          ) : (
            <p className="muted-line">No preview available.</p>
          )}
        </div>
      );
    case "rcm_studies":
      return (
        <>
          {a.rollup && <RollupBadges rollup={a.rollup} />}
          <div className="card" style={{ marginTop: "0.8rem" }}>
            <RcmTree functions={a.functions || []} readOnly onChange={() => {}} onEditDecision={() => {}} />
          </div>
        </>
      );
    case "fleets":
      return <FleetView a={a} />;
    default:
      return <div className="card empty">This artifact type doesn't have a public view.</div>;
  }
}

export default function PublicArtifact() {
  const { token } = useParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setData(null);
    setError(null);
    getPublicArtifact(token)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [token]);

  return (
    <div className="landing">
      <PublicNav />
      <div className="public-artifact">
        {error && (
          <div className="card empty" style={{ margin: "3rem auto", maxWidth: 520 }}>
            <h2>Link unavailable</h2>
            <p>{error}</p>
          </div>
        )}
        {!error && !data && <div className="card empty" style={{ margin: "3rem auto", maxWidth: 520 }}>Loading…</div>}
        {data && (
          <div className="app" style={{ margin: "0 auto", maxWidth: 1080 }}>
            <header>
              <div>
                <div className="crumb">{KIND_LABEL[data.collection] || "Analysis"} · shared by {data.shared_by}</div>
                <h1>{data.artifact.name}</h1>
                <p>
                  Read-only view, shared via Reliafy.{" "}
                  <Link to="/login?signup" className="evidence-link">Create a free account</Link>{" "}
                  to build your own.
                </p>
              </div>
            </header>
            <Body collection={data.collection} a={data.artifact} />
          </div>
        )}
      </div>
      <PublicFooter />
    </div>
  );
}

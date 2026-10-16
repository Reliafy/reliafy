import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { listAllPublicLinks, listReportItems, listReports, listStrategyAnalyses } from "../api.js";
import { relativeTime } from "../instrument.js";
import { itemPath } from "../navigation.js";
import Chip from "../components/ui/Chip.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";
import { SampleGroups, itemName } from "../components/LibRows.jsx";

const ANALYSIS_KIND = {
  optimal_replacement: "Optimal replacement",
  compare_two: "Two-model comparison",
  failure_finding: "Failure finding",
  demonstration_test: "Demonstration test",
};

const LINK_KIND = {
  models: "Life model",
  recurrent_models: "Recurrent-event model",
  degradation_models: "Degradation model",
  rbds: "Block diagram",
  strategy_analyses: "Strategy analysis",
  fleets: "Fleet forecast",
  rcm_studies: "RCM study",
  datasets: "Dataset",
  reports: "Report",
};

function SavedAnalyses() {
  const navigate = useNavigate();
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    listStrategyAnalyses().then((d) => setRows(d.analyses || [])).catch((e) => setError(e.message));
  }, []);
  const open = (id) => navigate(`/strategy/analyses/${id}`);
  return (
    <section aria-labelledby="reports-analyses" className="home-card">
      <div className="recent-models-head">
        <h2 id="reports-analyses">Saved strategy analyses</h2>
        <Link to="/strategy">Strategy →</Link>
      </div>
      {error ? <div className="card error">{error}</div> : rows === null ? (
        <div className="card empty">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="card empty"><p>No saved analyses yet. Run a <Link to="/strategy">Strategy</Link> tool and save its result.</p></div>
      ) : (
        <div className="lib">
          <table className="lib-table">
            <thead>
              <tr>
                <th style={{ width: "36%" }}>Analysis</th>
                <th className="lib-opt" style={{ width: 180 }}>Kind</th>
                <th>Result</th>
                <th className="lib-opt">Saved</th>
              </tr>
            </thead>
            <tbody>
              <SampleGroups rows={rows} cols={4} render={(a) => (
                <tr key={a.id} className="lib-row" onClick={() => open(a.id)}>
                  <td>
                    <Link className="lib-name" to={`/strategy/analyses/${a.id}`} onClick={(e) => e.stopPropagation()}>
                      {itemName(a)}
                    </Link>
                  </td>
                  <td className="lib-opt">{ANALYSIS_KIND[a.kind] || a.kind}</td>
                  <td className="lib-date">{a.headline}</td>
                  <td className="lib-date lib-opt">{relativeTime(a.updated_at || a.created_at)}</td>
                </tr>
              )} />
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// Every live share link the user has made, with what it shows.
function SharedLinks() {
  const [links, setLinks] = useState(null);
  const [names, setNames] = useState({});
  const [error, setError] = useState(null);
  useEffect(() => {
    listAllPublicLinks().then((d) => setLinks(d.links || [])).catch((e) => setError(e.message));
    Promise.all([
      listReportItems().then((d) => d.items || []).catch(() => []),
      listReports().then((d) => d.reports || []).catch(() => []),
    ]).then(([items, reports]) => {
      const out = {};
      for (const it of items) out[`${it.collection}:${it.artifact_id}`] = it.name;
      for (const r of reports) out[`reports:${r.id}`] = r.title || "Untitled report";
      setNames(out);
    });
  }, []);
  return (
    <section aria-labelledby="reports-links" className="home-card">
      <div className="recent-models-head">
        <h2 id="reports-links">Shared links</h2>
      </div>
      {error ? <div className="card error">{error}</div> : links === null ? (
        <div className="card empty">Loading…</div>
      ) : links.length === 0 ? (
        <div className="card empty">
          <p>No shared links yet. Share a model, diagram, study or analysis (its Share button) to get a link anyone can open.</p>
        </div>
      ) : (
        <div className="lib maint-scroll">
          <table className="lib-table">
            <thead>
              <tr>
                <th style={{ width: "34%" }}>Shows</th>
                <th className="lib-opt">Kind</th>
                <th>Link</th>
                <th className="lib-opt">Made</th>
              </tr>
            </thead>
            <tbody>
              {links.map((l) => {
                const name = names[`${l.collection}:${l.artifact_id}`] || "Untitled";
                const inApp = itemPath(l.collection, l.artifact_id);
                return (
                  <tr key={l.token}>
                    <td>
                      <div className="lib-name">
                        {inApp ? <Link to={inApp}>{name}</Link> : name}
                        {l.protected && <Chip>Password</Chip>}
                      </div>
                      {l.label && <div className="lib-date">{l.label}</div>}
                    </td>
                    <td className="lib-opt">{LINK_KIND[l.collection] || l.collection}</td>
                    <td>
                      <a href={l.path} target="_blank" rel="noreferrer">Open the shared page</a>
                      {l.expires_at && <div className="lib-date">until {new Date(l.expires_at).toLocaleDateString()}</div>}
                    </td>
                    <td className="lib-date lib-opt">{relativeTime(l.created_at)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// Reports (#438): what's been written up and shared, in one place: the saved
// strategy analyses, and every live share link.
export default function ReportsPage() {
  return (
    <div className="app">
      <PageHeader
        title="Reports"
        meta="Saved analyses and everything you've shared. To put several items on one page, use “Add to a report…” in any item's Share dialog."
      />
      <SavedAnalyses />
      <SharedLinks />
    </div>
  );
}

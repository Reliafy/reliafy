import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { listAllPublicLinks, listReportItems, listReports, listStrategyAnalyses } from "../api.js";
import { relativeTime } from "../instrument.js";
import { itemPath } from "../navigation.js";
import Chip from "../components/ui/Chip.jsx";
import { SectionHeader } from "../components/SectionPage.jsx";
import { PlusIcon, SampleGroups, itemName } from "../components/LibRows.jsx";

const ReportComposer = lazy(() => import("../components/ReportComposer.jsx"));

const HELP = { guide: "share-your-work" };

const ANALYSIS_KIND = {
  optimal_replacement: "Optimal replacement",
  compare_two: "Two-model comparison",
  failure_finding: "Failure finding",
  demonstration_test: "Demonstration test",
};

const LINK_KIND = {
  models: "Non-repairable model",
  recurrent_models: "Repairable model",
  alt_models: "Accelerated life model",
  degradation_models: "Degradation model",
  rbds: "Block diagram",
  strategy_analyses: "Strategy analysis",
  fleets: "Failure forecast",
  datasets: "Dataset",
  reports: "Report",
};

const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

function Panel({ id, title, all, children }) {
  return (
    <section aria-labelledby={id} className="home-card reports-panel">
      <div className="recent-models-head">
        <h2 id={id}>{title}</h2>
        {all && <Link to={all.to}>{all.label} →</Link>}
      </div>
      {children}
    </section>
  );
}

// The user's own reports: several saved items on one page with a title and
// notes, ready to print or share (made here, or from any item's Share dialog).
function YourReports({ rows, error, onOpen, onNew }) {
  return (
    <Panel id="reports-own" title="Your reports">
      {error ? <div className="card error">{error}</div> : rows === null ? (
        <div className="card empty">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="card empty">
          <p>
            No reports yet. A report puts several models, diagrams, forecasts or analyses on one page, with
            your notes, to print or share as one link.
          </p>
          <button type="button" onClick={onNew}><PlusIcon /> New report</button>
        </div>
      ) : (
        <div className="lib maint-scroll">
          <table className="lib-table">
            <thead>
              <tr>
                <th style={{ width: "44%" }}>Report</th>
                <th>Holds</th>
                <th className="lib-opt">Saved</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="lib-row" onClick={() => onOpen(r.id)}>
                  <td>
                    <button type="button" className="linkish lib-name" onClick={(e) => { e.stopPropagation(); onOpen(r.id); }}>
                      {r.title || "Untitled report"}
                    </button>
                    {r.author && <div className="lib-date">{r.author}</div>}
                  </td>
                  <td className="lib-date">{plural((r.sections || []).length, "item")}</td>
                  <td className="lib-date lib-opt">{relativeTime(r.updated_at || r.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

function SavedAnalyses() {
  const navigate = useNavigate();
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    listStrategyAnalyses().then((d) => setRows(d.analyses || [])).catch((e) => setError(e.message));
  }, []);
  const open = (id) => navigate(`/strategy/analyses/${id}`);
  return (
    <Panel id="reports-analyses" title="Saved analyses" all={{ to: "/strategy", label: "Strategy" }}>
      {error ? <div className="card error">{error}</div> : rows === null ? (
        <div className="card empty">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="card empty"><p>No saved analyses yet. Run a <Link to="/strategy">Strategy</Link> tool and save its result.</p></div>
      ) : (
        <div className="lib maint-scroll">
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
    </Panel>
  );
}

// Every live share link the user has made, with what it shows.
function SharedLinks({ reports }) {
  const [links, setLinks] = useState(null);
  const [names, setNames] = useState({});
  const [error, setError] = useState(null);
  useEffect(() => {
    listAllPublicLinks().then((d) => setLinks(d.links || [])).catch((e) => setError(e.message));
    listReportItems().then((d) => {
      const out = {};
      for (const it of d.items || []) out[`${it.collection}:${it.artifact_id}`] = it.name;
      setNames(out);
    }).catch(() => {});
  }, []);
  const nameOf = (l) => (l.collection === "reports"
    ? (reports || []).find((r) => r.id === l.artifact_id)?.title || "Untitled report"
    : names[`${l.collection}:${l.artifact_id}`] || "Untitled");
  return (
    <Panel id="reports-links" title="Shared links">
      {error ? <div className="card error">{error}</div> : links === null ? (
        <div className="card empty">Loading…</div>
      ) : links.length === 0 ? (
        <div className="card empty">
          <p>No shared links yet. Use the Share button on a model, diagram, forecast, analysis or report to get a link anyone can open.</p>
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
                const inApp = itemPath(l.collection, l.artifact_id);
                return (
                  <tr key={l.token}>
                    <td>
                      <div className="lib-name">
                        {inApp ? <Link to={inApp}>{nameOf(l)}</Link> : nameOf(l)}
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
    </Panel>
  );
}

// Reports: what's been written up and shared, in one place: the user's
// reports (several items on one page), their saved analyses, and every live
// share link.
export default function ReportsPage() {
  const [reports, setReports] = useState(null);
  const [error, setError] = useState(null);
  const [composer, setComposer] = useState(null); // null | { openId }
  const load = useCallback(() => {
    listReports().then((d) => setReports(d.reports || [])).catch((e) => setError(e.message));
  }, []);
  useEffect(() => load(), [load]);
  const close = () => {
    setComposer(null);
    load();
  };
  return (
    <div className="app">
      <SectionHeader
        title="Reports"
        purpose="Your reports, saved analyses and everything you've shared."
        help={HELP}
        primary={<button onClick={() => setComposer({ openId: "" })}><PlusIcon /> New report</button>}
      />
      <YourReports rows={reports} error={error} onOpen={(id) => setComposer({ openId: id })}
                   onNew={() => setComposer({ openId: "" })} />
      <SavedAnalyses />
      <SharedLinks reports={reports} />
      {composer && (
        <Suspense fallback={null}>
          <ReportComposer openId={composer.openId} onClose={close} />
        </Suspense>
      )}
    </div>
  );
}

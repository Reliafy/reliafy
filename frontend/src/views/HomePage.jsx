import { useEffect, useState } from "react";
import {
  getMaintenanceAccess,
  getMaintenanceOverview,
  getWorkspaceChanges,
  listDatasets,
  listFleets,
  listRbds,
  listRcmStudies,
  listStrategyAnalyses,
  listTrackedFleets,
} from "../api.js";
import { useAppConfig } from "../ConfigProvider.jsx";
import { SAMPLE_MODEL, useFirstRun } from "../firstRun.js";
import { TYPE_LABEL, loadAllModels } from "../allModels.js";
import { ATTENTION_ROWS, NEAR_EMPTY, RECENT_ROWS, attentionRows, recentRows } from "../home.js";
import { SectionHeader } from "../components/SectionPage.jsx";
import { StartHere, StartHereCompact, useActivation } from "../components/FirstRun.jsx";
import WhatChangedPanel, { ChangeList } from "../components/WhatChanged.jsx";
import UnsavedFitReminder from "../components/UnsavedFitReminder.jsx";

// A list that can't be read counts as empty: Home is a summary, and each
// section's own page reports its errors.
const quiet = (p, key) => p.then((d) => (key ? d[key] : d) || []).catch(() => []);

function HomeList({ id, title, count, rows, children }) {
  return (
    <section className="wc-panel home-list" aria-labelledby={id}>
      <div className="recent-models-head">
        <h2 id={id}>{title}</h2>
        {count != null && <span className="home-count">{count}</span>}
      </div>
      <div className="wc-card">
        {children}
        {rows.length > 0 && <ChangeList rows={rows} />}
      </div>
    </section>
  );
}

// Home: where the app opens. What changed across every section, what needs
// attention, the user's recent work, and the ways to start — large for a new
// or near-empty workspace, one compact row otherwise.
export default function HomePage() {
  const { maintenance: maintenanceEnabled } = useAppConfig();
  const [lists, setLists] = useState(null);
  const [changes, setChanges] = useState(undefined);
  const [maintenance, setMaintenance] = useState(null);

  useEffect(() => {
    let live = true;
    Promise.all([
      loadAllModels().catch(() => []),
      quiet(listDatasets(), "datasets"),
      quiet(listRbds(), "rbds"),
      quiet(listRcmStudies(), "studies"),
      quiet(listFleets(), "fleets"),
      quiet(listStrategyAnalyses(), "analyses"),
      quiet(listTrackedFleets(), "fleets"),
    ]).then(([models, datasets, rbds, studies, forecasts, analyses, tracked]) => {
      if (live) setLists({ models, datasets, rbds, studies, forecasts, analyses, tracked });
    });
    getWorkspaceChanges().then((d) => live && setChanges(d)).catch(() => live && setChanges(null));
    return () => {
      live = false;
    };
  }, []);

  // Maintenance work, for operators only: the same check as the menu's.
  useEffect(() => {
    if (!maintenanceEnabled) return undefined;
    let live = true;
    getMaintenanceAccess()
      .then((a) => (a.allowed ? getMaintenanceOverview() : null))
      .then((o) => live && setMaintenance(o))
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [maintenanceEnabled]);

  useActivation(lists?.models);

  const recent = lists
    ? recentRows({ ...lists, models: lists.models.map((m) => ({ ...m, kind: TYPE_LABEL[m.type] })) })
    : [];
  const ownCount = recent.length;
  const firstRun = useFirstRun(lists ? ownCount > 0 : undefined);
  const nearEmpty = lists !== null && ownCount < NEAR_EMPTY;
  const lifeSamples = (lists?.models || []).filter((r) => r.is_sample && r.type === "life");
  const sampleModelId = (lifeSamples.find((r) => r.id === SAMPLE_MODEL) || lifeSamples[0])?.id || null;
  const attention = attentionRows({ changes, tracked: lists?.tracked, maintenance });

  return (
    <div className="app home">
      <SectionHeader
        title="Home"
        purpose="What changed, what needs you, and your recent work, across every section."
      />

      {/* A fit left without saving, with its one-click save (#434). */}
      <UnsavedFitReminder />

      {lists === null ? (
        <div className="card empty view-loading">Loading…</div>
      ) : (
        <>
          {nearEmpty && <StartHere info={firstRun} sampleModelId={sampleModelId} />}

          <WhatChangedPanel data={changes === undefined ? null : changes} />

          {attention.length > 0 && (
            <HomeList id="home-attention" title="Needs attention" rows={attention.slice(0, ATTENTION_ROWS)}
                      count={attention.length > ATTENTION_ROWS ? `${ATTENTION_ROWS} of ${attention.length}` : null} />
          )}

          {recent.length > 0 && (
            <HomeList id="home-recent" title="Recent" rows={recent.slice(0, RECENT_ROWS)}>
              <p className="home-note">Your most recently saved or edited work.</p>
            </HomeList>
          )}

          {!nearEmpty && <StartHereCompact sampleModelId={sampleModelId} />}
        </>
      )}
    </div>
  );
}

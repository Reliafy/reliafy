import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  getMaintenanceOverview,
  getWorkspaceChanges,
  getWorkspaceRcm,
  listDatasets,
  listFleets,
  listRbds,
  listStrategyAnalyses,
  listTrackedFleets,
} from "../api.js";
import { SAMPLE_MODEL, useFirstRun } from "../firstRun.js";
import { TYPE_LABEL, loadAllModels } from "../allModels.js";
import {
  ATTENTION_ROWS, NEAR_EMPTY, RECENT_ROWS, attentionRows, dueRows, fleetRows, otherRecent, recentFor, recentRows,
  sparesRows, waitingFigures, workTodayRows,
} from "../home.js";
import { RBDS_LABEL, RBDS_PATH, homeCards } from "../navigation.js";
import { useRoles } from "../RolesProvider.jsx";
import { SectionHeader } from "../components/SectionPage.jsx";
import { RolesCard } from "../components/RolePicker.jsx";
import { StartHere, StartHereCompact, useActivation } from "../components/FirstRun.jsx";
import WhatChangedPanel, { ChangeList } from "../components/WhatChanged.jsx";
import UnsavedFitReminder from "../components/UnsavedFitReminder.jsx";

// A list that can't be read counts as empty: Home is a summary, and each
// section's own page reports its errors.
const quiet = (p, key) => p.then((d) => (key ? d[key] : d) || []).catch(() => []);

const CARD_ROWS = 5;

// One of Home's lists: a heading (with a link to the whole list, or a note),
// then rows in the "What changed" style, or `empty` while there are none.
function HomeList({ id, title, note, all, rows, empty, children }) {
  return (
    <section className="wc-panel home-list" aria-labelledby={id} data-card={id}>
      <div className="recent-models-head">
        <h2 id={id}>{title}</h2>
        {note && <span className="home-note">{note}</span>}
        {all && <Link to={all.to}>{all.label} →</Link>}
      </div>
      <div className="wc-card">
        {children}
        {rows.length > 0 ? <ChangeList rows={rows} /> : empty && <p className="home-none">{empty}</p>}
      </div>
    </section>
  );
}

// Figures in a row (each { label, n, to, alert }), for the at-a-glance cards.
function Figures({ items }) {
  return (
    <ul className="home-figures">
      {items.map((f) => (
        <li key={f.label}>
          <Link to={f.to} className={"home-figure" + (f.alert && f.n > 0 ? " alert" : "")}>
            <span className="home-figure-n">{f.n}</span>
            <span className="home-figure-label">{f.label}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

// A role's card (navigation.js ROLES `home`), from what Home loaded. Cards
// that need Reliafy Maintenance draw nothing without it.
function RoleCard({ card, recent, attention, maintenance, rcm, has }) {
  const id = `home-${card}`;
  const first = (rows) => rows.slice(0, CARD_ROWS);
  switch (card) {
    case "recent-models":
      return (
        <HomeList id={id} title="Your recent models" all={{ to: "/models", label: "Models" }}
                  rows={first(recentFor(card, recent))}
                  empty={<>No models of your own yet. <Link to="/models/new">Fit some data</Link>.</>} />
      );
    case "recent-data":
      return (
        <HomeList id={id} title="Your recent data" all={{ to: "/data", label: "Data" }}
                  rows={first(recentFor(card, recent))}
                  empty={<>No datasets of your own yet. <Link to="/data">Upload or paste some</Link>.</>} />
      );
    case "recent-systems":
      return (
        <HomeList id={id} title={`Your recent ${RBDS_LABEL}`} all={{ to: RBDS_PATH, label: RBDS_LABEL }}
                  rows={first(recentFor(card, recent))}
                  empty={<>No block diagrams of your own yet. <Link to="/systems/b">Build one</Link>.</>} />
      );
    case "fleets":
      return (
        <HomeList id={id} title="Your fleets" all={{ to: "/forecasts", label: "Forecasts" }}
                  rows={first(fleetRows(attention, recent))}
                  empty={<>No fleets of your own yet. <Link to="/forecasts?new=1">Forecast one</Link>.</>} />
      );
    case "due": {
      if (!has.maintenance) return null;
      const due = dueRows(maintenance);
      return (
        <HomeList id={id} title="Due and at risk" all={{ to: "/maintenance", label: "Maintenance" }}
                  rows={first(due)} empty={maintenance ? "Nothing due in the next 30 days." : "Loading…"}>
          {maintenance && (
            <Figures items={[
              { label: "overdue", n: (maintenance.due || []).filter((t) => t.overdue).length, to: "/maintenance", alert: true },
              { label: "due in 30 days", n: (maintenance.due || []).length, to: "/maintenance" },
              { label: "critical spares short", n: (maintenance.critical_spares || []).length, to: "/asset-register/parts", alert: true },
              { label: "changes proposed", n: (maintenance.proposals || []).length, to: "/maintenance" },
            ]} />
          )}
        </HomeList>
      );
    }
    case "work-today": {
      if (!has.maintenance) return null;
      const open = maintenance?.open_work_orders || [];
      return (
        <HomeList id={id} title="Today's work orders" all={{ to: "/maintenance", label: `All ${open.length} open` }}
                  rows={first(workTodayRows(maintenance))}
                  empty={!maintenance ? "Loading…" : open.length ? "Nothing due today." : "No open work orders."} />
      );
    }
    case "spares":
      if (!has.maintenance) return null;
      return (
        <HomeList id={id} title="Critical spares short" all={{ to: "/asset-register/parts", label: "Parts and stock" }}
                  rows={first(sparesRows(maintenance))}
                  empty={maintenance ? "Every critical spare is stocked." : "Loading…"} />
      );
    case "waiting": {
      // The RCM on the asset tree and the maintenance overview: both are
      // Reliafy Maintenance's, so the card draws nothing without it.
      if (!has.maintenance) return null;
      const figures = waitingFigures(rcm, maintenance);
      return (
        <HomeList id={id} title="Targets and what's waiting" all={{ to: "/reports", label: "Reports" }} rows={[]}
                  empty={figures.length ? null : "Loading…"}>
          {figures.length > 0 && <Figures items={figures} />}
        </HomeList>
      );
    }
    default:
      return null;
  }
}

// Home: where the app opens. With roles picked (Settings › What do you do?),
// it leads with each role's cards, the primary role's first. Then what
// changed across every section, what needs attention, the rest of the user's
// recent work, and the ways to start: large for a new or near-empty
// workspace, one compact row otherwise.
export default function HomePage() {
  const { roles, offer, has } = useRoles();
  const [lists, setLists] = useState(null);
  const [changes, setChanges] = useState(undefined);
  const [maintenance, setMaintenance] = useState(null);
  // The RCM on the asset tree, as one rollup of every decision's evidence check.
  const [rcm, setRcm] = useState(null);

  useEffect(() => {
    let live = true;
    Promise.all([
      loadAllModels().catch(() => []),
      quiet(listDatasets(), "datasets"),
      quiet(listRbds(), "rbds"),
      quiet(listFleets(), "fleets"),
      quiet(listStrategyAnalyses(), "analyses"),
      quiet(listTrackedFleets(), "fleets"),
    ]).then(([models, datasets, rbds, forecasts, analyses, tracked]) => {
      if (live) setLists({ models, datasets, rbds, forecasts, analyses, tracked });
    });
    getWorkspaceChanges().then((d) => live && setChanges(d)).catch(() => live && setChanges(null));
    return () => {
      live = false;
    };
  }, []);

  // Maintenance work and the tree's RCM, for Reliafy Maintenance's operators
  // only (the menu's check).
  useEffect(() => {
    if (!has.maintenance) return undefined;
    let live = true;
    getMaintenanceOverview().then((o) => live && setMaintenance(o)).catch(() => {});
    getWorkspaceRcm().then((d) => live && setRcm(d?.rollup || null)).catch(() => {});
    return () => {
      live = false;
    };
  }, [has.maintenance]);

  useActivation(lists?.models);

  const recent = lists
    ? recentRows({ ...lists, models: lists.models.map((m) => ({ ...m, kind: TYPE_LABEL[m.type] })) })
    : [];
  const ownCount = recent.length;
  const firstRun = useFirstRun(lists ? ownCount > 0 : undefined);
  const nearEmpty = lists !== null && ownCount < NEAR_EMPTY;
  const lifeSamples = (lists?.models || []).filter((r) => r.is_sample && r.type === "life");
  const sampleModelId = (lifeSamples.find((r) => r.id === SAMPLE_MODEL) || lifeSamples[0])?.id || null;
  const attention = attentionRows({ changes, tracked: lists?.tracked, maintenance: has.maintenance ? maintenance : null });

  // The roles' cards, and what they already show (left out of the lists below).
  const cards = homeCards(roles).filter((c) => has.maintenance || !["due", "work-today", "spares", "waiting"].includes(c));
  const cardShows = (r) => (cards.includes("due") && r.key.startsWith("due-"))
    || (cards.includes("fleets") && (r.key.startsWith("alert-") || r.key.startsWith("track-")));
  const needs = attention.filter((r) => !cardShows(r));
  const rest = otherRecent(cards, recent);

  return (
    <div className="app home">
      <SectionHeader
        title="Home"
        purpose={cards.length
          ? "What your roles look at first, then what changed and what needs you, across every section."
          : "What changed, what needs you, and your recent work, across every section."}
      />

      {/* Asked once, of a new user; Settings keeps the picker. */}
      {offer && <RolesCard offer />}

      {/* A fit left without saving, with its one-click save (#434). */}
      <UnsavedFitReminder />

      {lists === null ? (
        <div className="card empty view-loading">Loading…</div>
      ) : (
        <>
          {nearEmpty && <StartHere info={firstRun} sampleModelId={sampleModelId} />}

          {cards.map((card) => (
            <div key={card} className="home-slot">
              <RoleCard card={card} recent={recent} attention={attention} maintenance={maintenance}
                        rcm={rcm} has={has} />
            </div>
          ))}

          <WhatChangedPanel data={changes === undefined ? null : changes} />

          {/* Once the changes are in: "nothing" before then would be a guess. */}
          {changes !== undefined && (
            <HomeList id="home-attention" title="Needs attention" rows={needs.slice(0, ATTENTION_ROWS)}
                      note={needs.length > ATTENTION_ROWS ? `${ATTENTION_ROWS} of ${needs.length}` : null}
                      empty="Nothing needs you right now." />
          )}

          {rest.length > 0 && (
            <HomeList id="home-recent" title={rest.length < recent.length ? "Other recent work" : "Recent"}
                      rows={rest.slice(0, RECENT_ROWS)}
                      note="Your work, most recently saved or edited first" />
          )}

          {!nearEmpty && <StartHereCompact sampleModelId={sampleModelId} />}
        </>
      )}
    </div>
  );
}
